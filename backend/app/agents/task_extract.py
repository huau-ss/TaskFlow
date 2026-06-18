"""LangGraph agent: extract tasks from transcript and match employees.

Voiceprint fusion — 声纹识别结果融合：

1. 转写格式化时将声纹识别的员工姓名注入文本（SPEAKER_00 → SPEAKER_00(张三)）
   让 LLM 可以直接利用已识别的人员信息
2. 多段落声纹投票：如果任务跨多个 segment，用多数表决确定执行人
3. 记录匹配方式和置信度到 Task 模型，便于追溯和审计
"""

import json
import re
from collections import Counter
from datetime import UTC, datetime
from typing import TypedDict

from dateutil import parser as date_parser
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Employee, Meeting, Task, TaskStatus, TranscriptSegment


class AgentState(TypedDict, total=False):
    meeting_id: int
    transcript_text: str
    segments: list[dict]
    # speaker_label → employee 映射（声纹识别结果）
    speaker_employee_map: dict[str, dict]  # {"SPEAKER_00": {"id": 1, "name": "张三", "confidence": 0.85}}
    extracted_tasks: list[dict]
    employees: list[dict]
    matched_tasks: list[dict]
    errors: list[str]
    created_task_ids: list[int]


def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        base_url=settings.llm_url,
        api_key=settings.llm_api_key or "not-needed",
        model=settings.llm_model,
        temperature=0,
    )


def _format_transcript(
    segments: list[TranscriptSegment],
    speaker_employee_map: dict[str, dict] | None = None,
) -> tuple[str, list[dict]]:
    """
    格式化转写文本供 LLM 消费。

    声纹融合：如果 speaker_label 匹配到员工，用 "SPEAKER_00(张三)" 替代 "SPEAKER_00"，
    让 LLM 在提取任务时就能直接获得员工身份信息。
    """
    speaker_map = speaker_employee_map or {}
    seg_data = []
    lines = []

    for seg in sorted(segments, key=lambda s: s.sequence):
        label = seg.speaker_label

        # 声纹融合：替换为可读名称
        if label in speaker_map:
            emp_name = speaker_map[label]["name"]
            display_label = f"{label}({emp_name})"
        elif seg.employee_id:
            # segment 有 employee_id 但 map 里还没建好（fallback）
            display_label = f"{label}(员工#{seg.employee_id})"
        else:
            display_label = label

        seg_data.append(
            {
                "id": seg.id,
                "speaker": display_label,
                "raw_speaker": seg.speaker_label,
                "text": seg.text,
                "start_time": seg.start_time,
                "end_time": seg.end_time,
                "employee_id": seg.employee_id,  # 声纹识别结果
            }
        )
        lines.append(f"[{seg.id}] {display_label}: {seg.text}")

    return "\n".join(lines), seg_data


EXTRACT_SYSTEM = """你是会议纪要任务提取助手。从会议转写文本中提取 actionable 任务。

输出必须是 JSON 数组，每项包含：
- task: 任务标题（简短）
- description: 任务详细描述
- executor_name: 责任人姓名（从文本推断，无法确定则为 null）
  注意：如果说话人格式为 "SPEAKER_XX(员工名)"，该员工名是声纹识别系统自动标注的，优先采纳。
- deadline_text: 截止时间原文（如"下周五"、"6月20日"）
- source_segment_ids: 相关转写段落 id 数组

只输出 JSON，不要其他文字。若无任务则输出 []。"""


async def extract_tasks_node(state: AgentState) -> AgentState:
    llm = _build_llm()
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    # 构建声纹识别提示
    voiceprint_hint = ""
    speaker_map = state.get("speaker_employee_map", {})
    if speaker_map:
        resolved = [
            f"{label} → {info['name']}（声纹置信度 {info['confidence']:.0%}）"
            for label, info in speaker_map.items()
        ]
        voiceprint_hint = (
            "\n\n【声纹识别结果】以下说话人已通过声纹验证：\n" + "\n".join(resolved)
        )

    prompt = f"今天是 {today}。\n\n会议转写：\n{state['transcript_text']}{voiceprint_hint}"
    response = await llm.ainvoke(
        [SystemMessage(content=EXTRACT_SYSTEM), HumanMessage(content=prompt)]
    )
    content = response.content.strip()
    # Strip markdown code fences if present
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
    try:
        tasks = json.loads(content)
        if not isinstance(tasks, list):
            tasks = []
    except json.JSONDecodeError:
        state["errors"].append(f"Failed to parse LLM output: {content[:200]}")
        tasks = []
    state["extracted_tasks"] = tasks
    return state


async def load_employees_node(state: AgentState, db: AsyncSession) -> AgentState:
    """加载员工列表、转写片段，并构建说话人→员工声纹映射"""
    # 加载员工列表
    emp_result = await db.execute(
        select(Employee).where(Employee.is_active.is_(True))
    )
    employees = emp_result.scalars().all()
    state["employees"] = [
        {"id": e.id, "name": e.name, "email": e.email} for e in employees
    ]

    # 加载转写片段（包含声纹识别后的 employee_id）
    seg_result = await db.execute(
        select(TranscriptSegment).where(
            TranscriptSegment.meeting_id == state["meeting_id"]
        )
    )
    segments = seg_result.scalars().all()

    # 构建员工 ID → name 快速查找
    emp_id_to_name = {e.id: e.name for e in employees}

    # 构建 speaker_label → employee 声纹映射
    # 策略：同一 speaker_label 的多个 segment，用出现次数最多的 employee_id
    speaker_employee_votes: dict[str, list[int]] = {}
    for seg in segments:
        if seg.employee_id:
            speaker_employee_votes.setdefault(seg.speaker_label, []).append(
                seg.employee_id
            )

    speaker_employee_map: dict[str, dict] = {}
    for label, emp_ids in speaker_employee_votes.items():
        # 多数表决
        counter = Counter(emp_ids)
        most_common_id, count = counter.most_common(1)[0]
        total = len(emp_ids)
        confidence = count / total  # 同一说话人被识别为同一员工的占比
        emp_name = emp_id_to_name.get(most_common_id)
        if emp_name:
            speaker_employee_map[label] = {
                "id": most_common_id,
                "name": emp_name,
                "confidence": round(confidence, 2),
                "votes": count,
                "total": total,
            }

    state["speaker_employee_map"] = speaker_employee_map

    # 重新格式化转写文本（注入声纹识别结果）
    transcript_text, seg_data = _format_transcript(segments, speaker_employee_map)
    state["transcript_text"] = transcript_text
    state["segments"] = seg_data

    return state


async def match_employees_node(state: AgentState) -> AgentState:
    """匹配执行人 —— 声纹识别 + AI 姓名匹配双路径融合

    优先级（从高到低）：
    1. 声纹多数表决（同一 speaker 的多段 segment 都指向同一员工）→ confidence 高
    2. 声纹单次命中（只有一个 segment 匹配到员工）→ confidence 中等
    3. AI 姓名精确匹配 → confidence = 1.0
    4. AI 姓名模糊匹配 → confidence = 0.6
    5. 无匹配 → executor_id = null
    """
    # 构建映射
    segment_employee_map: dict[int, tuple[int, float]] = {}
    for seg in state.get("segments", []):
        if seg.get("employee_id"):
            seg_id = seg["id"]
            emp_id = seg["employee_id"]
            # 查找该 segment 对应 speaker 的置信度
            speaker_label = seg.get("raw_speaker", "")
            speaker_info = state.get("speaker_employee_map", {}).get(speaker_label, {})
            confidence = speaker_info.get("confidence", 0.5)
            segment_employee_map[seg_id] = (emp_id, confidence)

    # 构建员工名称映射
    employee_names = {emp["name"]: emp["id"] for emp in state["employees"]}
    employee_names_lower = {
        name.lower(): emp_id for name, emp_id in employee_names.items()
    }

    matched = []
    for item in state["extracted_tasks"]:
        executor_id = None
        match_method = None
        match_confidence = None

        source_segment_ids = item.get("source_segment_ids", [])
        if not isinstance(source_segment_ids, list):
            source_segment_ids = []

        # ─── 路径 1: 声纹多段落表决 ───
        if source_segment_ids and segment_employee_map:
            voiceprint_votes: list[tuple[int, float]] = []
            for seg_id in source_segment_ids:
                if seg_id in segment_employee_map:
                    voiceprint_votes.append(segment_employee_map[seg_id])

            if voiceprint_votes:
                # 按员工聚合：取平均置信度 × 命中次数
                emp_scores: dict[int, tuple[int, float]] = {}
                for emp_id, conf in voiceprint_votes:
                    if emp_id in emp_scores:
                        count, total_conf = emp_scores[emp_id]
                        emp_scores[emp_id] = (count + 1, total_conf + conf)
                    else:
                        emp_scores[emp_id] = (1, conf)

                # 评分 = 命中次数 + 平均置信度
                best_emp = None
                best_score = -1.0
                for emp_id, (count, total_conf) in emp_scores.items():
                    avg_conf = total_conf / count
                    score = count + avg_conf  # 综合命中次数和置信度
                    if score > best_score:
                        best_score = score
                        best_emp = emp_id
                        match_confidence = round(avg_conf, 2)

                if best_emp:
                    executor_id = best_emp
                    match_method = "voiceprint"

        # ─── 路径 2: AI 姓名匹配（声纹未命中时） ───
        if not executor_id:
            extracted_name = item.get("executor_name")
            if extracted_name:
                extracted_name = extracted_name.strip()
                # 精确匹配
                if extracted_name in employee_names:
                    executor_id = employee_names[extracted_name]
                    match_method = "name_exact"
                    match_confidence = 1.0
                else:
                    # 模糊匹配（大小写不敏感）
                    name_lower = extracted_name.lower()
                    if name_lower in employee_names_lower:
                        executor_id = employee_names_lower[name_lower]
                        match_method = "name_exact"
                        match_confidence = 1.0
                    else:
                        # 子串匹配
                        for emp_name, emp_id in employee_names.items():
                            if (
                                extracted_name in emp_name
                                or emp_name in extracted_name
                            ):
                                executor_id = emp_id
                                match_method = "name_fuzzy"
                                match_confidence = 0.6
                                break

        segment_ids_str = (
            json.dumps(source_segment_ids) if source_segment_ids else None
        )

        matched.append(
            {
                "title": item.get("task", "未命名任务"),
                "description": item.get("description"),
                "executor_id": executor_id,
                "executor_name": item.get("executor_name"),
                "match_method": match_method,
                "match_confidence": match_confidence,
                "deadline": _parse_deadline(item.get("deadline_text")),
                "source_segment_ids": segment_ids_str,
            }
        )

    # 统计匹配方式分布
    methods = Counter(m["match_method"] for m in matched)
    state["errors"].append(
        f"任务匹配统计: voiceprint={methods.get('voiceprint', 0)}, "
        f"name_exact={methods.get('name_exact', 0)}, "
        f"name_fuzzy={methods.get('name_fuzzy', 0)}, "
        f"none={methods.get(None, 0)}"
    )

    state["matched_tasks"] = matched
    return state


def _parse_deadline(
    deadline_text: str | None, reference: datetime | None = None
) -> datetime | None:
    if not deadline_text:
        return None
    ref = reference or datetime.now(UTC)
    try:
        dt = date_parser.parse(deadline_text, default=ref.replace(tzinfo=None))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None


async def persist_tasks_node(
    state: AgentState, db: AsyncSession, meeting_id: int
) -> AgentState:
    """持久化任务，包含声纹匹配元数据"""
    from app.agents.task_notification import send_task_notifications

    created_ids: list[int] = []
    created_tasks = []

    for item in state["matched_tasks"]:
        task = Task(
            title=item["title"],
            description=item["description"],
            deadline=item["deadline"],
            status=TaskStatus.pending,
            executor_id=item["executor_id"],
            meeting_id=meeting_id,
            source_segment_ids=item["source_segment_ids"],
            match_method=item["match_method"],
            match_confidence=item["match_confidence"],
        )
        db.add(task)
        await db.flush()
        created_ids.append(task.id)
        created_tasks.append(task)

    state["created_task_ids"] = created_ids

    # 发送任务通知
    if created_tasks:
        try:
            await send_task_notifications(db, created_tasks)
        except Exception as e:
            state["errors"].append(f"Failed to send notifications: {str(e)}")

    return state


def build_graph(db: AsyncSession, meeting_id: int):
    graph = StateGraph(AgentState)

    async def load_employees_wrapper(state: AgentState) -> AgentState:
        return await load_employees_node(state, db)

    async def persist_wrapper(state: AgentState) -> AgentState:
        return await persist_tasks_node(state, db, meeting_id)

    graph.add_node("extract", extract_tasks_node)
    graph.add_node("load_employees", load_employees_wrapper)
    graph.add_node("match", match_employees_node)
    graph.add_node("persist", persist_wrapper)

    graph.set_entry_point("load_employees")
    graph.add_edge("load_employees", "extract")
    graph.add_edge("extract", "match")
    graph.add_edge("match", "persist")
    graph.add_edge("persist", END)

    return graph.compile()


async def run_task_extraction(db: AsyncSession, meeting: Meeting) -> list[Task]:
    segments = meeting.segments
    if not segments:
        return []

    # 简单检查：是否有任何文本内容
    transcript_text, _ = _format_transcript(segments)
    if not transcript_text.strip():
        return []

    initial: AgentState = {
        "meeting_id": meeting.id,
        "transcript_text": transcript_text,
        "segments": [],
        "speaker_employee_map": {},
        "extracted_tasks": [],
        "employees": [],
        "matched_tasks": [],
        "errors": [],
    }

    graph = build_graph(db, meeting.id)
    final_state = await graph.ainvoke(initial)

    created_ids = final_state.get("created_task_ids", [])
    if not created_ids:
        return []

    result = await db.execute(
        select(Task).where(Task.id.in_(created_ids)).order_by(Task.id)
    )
    return list(result.scalars().all())
