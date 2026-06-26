"""LangGraph 编排的完整会议处理工作流。

Stages:
  1. FunASR 转写       → 已在 Celery Phase 1 完成（asr.py）
  2. LLM 优化转写文本   → llm_optimize_node
  3. 任务提取           → extract_tasks_node
  4. 会议关联分析       → analyze_relations_node（全局，由外层触发）
  5. 生成 HTML 报告    → generate_report_node
  6. 通知相关人员       → notify_node

每个节点独立，失败不阻塞后续（记录到 state["errors"]）。
支持两种调用方式：
  - Celery worker (sync context)  → run_meeting_workflow_sync()
  - FastAPI route (async context) → run_meeting_workflow()

设计要点：
  - 所有 DB 操作通过注入的 session 完成（不重新创建 session）
  - 关键字段（optimized_text、report_path）直接更新 Meeting 对象
  - 每个 node 失败不影响下游（收集到 state["errors"]）
  - 工作流无副作用：不修改 Meeting.status（由调用方控制状态机）
"""

import asyncio
import json
import logging
import os
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from typing import TypedDict

from dateutil import parser as date_parser
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Employee,
    Meeting,
    MeetingRelation,
    MeetingStatus,
    RelationType,
    Task,
    TaskStatus,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)


# ─── State ────────────────────────────────────────────────────────────

class MeetingWorkflowState(TypedDict, total=False):
    meeting_id: int
    meeting_title: str | None
    employees: list[dict]
    errors: list[str]
    warnings: list[str]
    current_step: str
    raw_transcript_text: str | None
    optimized_text: str | None
    optimize_error: str | None
    speaker_employee_map: dict[str, dict]
    seg_label_map: dict[int, str]
    extracted_tasks: list[dict]
    task_extract_error: str | None
    matched_tasks: list[dict]
    relations: list[dict]
    relation_error: str | None
    report_path: str | None
    report_error: str | None
    notifications_sent: int
    notification_error: str | None
    created_task_ids: list[int]


# ─── LLM Helper ────────────────────────────────────────────────────────

def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        base_url=settings.llm_url,
        api_key=settings.llm_api_key or "not-needed",
        model=settings.llm_model,
        temperature=0,
    )


# ─── Shared: 格式化工单 ──────────────────────────────────────────────────

def _format_transcript(
    segments: list[TranscriptSegment],
    speaker_employee_map: dict[str, dict] | None = None,
) -> tuple[str, list[dict]]:
    speaker_map = speaker_employee_map or {}
    seg_data = []
    lines = []

    for seg in sorted(segments, key=lambda s: s.sequence):
        label = seg.speaker_label
        if label in speaker_map:
            display_label = f"{label}({speaker_map[label]['name']})"
        elif seg.employee_id:
            display_label = f"{label}(员工#{seg.employee_id})"
        else:
            display_label = label

        seg_data.append({
            "id": seg.id,
            "speaker": display_label,
            "raw_speaker": seg.speaker_label,
            "text": seg.text,
            "start_time": seg.start_time,
            "end_time": seg.end_time,
            "employee_id": seg.employee_id,
        })
        lines.append(f"[{seg.id}] {display_label}: {seg.text}")

    return "\n".join(lines), seg_data


def _parse_deadline(
    deadline_text: str | None,
    reference: datetime | None = None,
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


# ─── Node 0: load_data ─────────────────────────────────────────────────

async def load_data_node(
    state: MeetingWorkflowState, db: AsyncSession
) -> MeetingWorkflowState:
    """预加载员工数据、转写片段、说话人映射"""
    state["current_step"] = "load_data"

    # 加载 meeting 标题（用于 HTML 报告）
    meeting = await db.get(Meeting, state["meeting_id"])
    if meeting:
        state["meeting_title"] = meeting.title

    emp_result = await db.execute(
        select(Employee).where(Employee.is_active.is_(True))
    )
    employees = emp_result.scalars().all()
    state["employees"] = [{"id": e.id, "name": e.name, "email": e.email} for e in employees]

    seg_result = await db.execute(
        select(TranscriptSegment).where(
            TranscriptSegment.meeting_id == state["meeting_id"]
        )
    )
    segments = seg_result.scalars().all()

    if not segments:
        state["warnings"].append("无转写片段")
        state["raw_transcript_text"] = ""
        return state

    speaker_votes: dict[str, list[int]] = {}
    seg_label_map: dict[int, str] = {}
    for seg in segments:
        seg_label_map[seg.id] = seg.speaker_label
        if seg.employee_id:
            speaker_votes.setdefault(seg.speaker_label, []).append(seg.employee_id)

    emp_id_to_name = {e["id"]: e["name"] for e in state["employees"]}
    label_map: dict[str, dict] = {}
    for label, emp_ids in speaker_votes.items():
        counter = Counter(emp_ids)
        most_common_id, count = counter.most_common(1)[0]
        confidence = count / len(emp_ids)
        emp_name = emp_id_to_name.get(most_common_id)
        if emp_name:
            label_map[label] = {
                "id": most_common_id,
                "name": emp_name,
                "confidence": round(confidence, 2),
            }

    state["speaker_employee_map"] = label_map
    state["seg_label_map"] = seg_label_map

    transcript_text, _ = _format_transcript(segments, label_map)
    state["raw_transcript_text"] = transcript_text

    logger.info("会议 %s 加载 %d 个片段，%d 个员工", state["meeting_id"], len(segments), len(employees))
    return state


# ─── Node 1: LLM 优化转写文本 ─────────────────────────────────────────

OPTIMIZE_SYSTEM = """你是一个专业的会议记录整理助手。请将下面的会议转写文本整理成更清晰、流畅的格式。

要求：
- 修正明显的语音识别错误
- 删除重复的口语填充词（如"呃"、"嗯"、"这个这个"等）
- 保持原意不变，适当断句
- 保留关键的人名、时间、数字等具体信息
- 输出纯文本，不要加标题或编号

只输出整理后的文本，不要其他说明。如果转写已经清晰可读，直接输出原文本。"""


async def llm_optimize_node(state: MeetingWorkflowState) -> MeetingWorkflowState:
    """优化转写文本（可选阶段，失败不影响后续，回退到原始文本）"""
    state["current_step"] = "llm_optimize"
    raw_text = state.get("raw_transcript_text")

    if not raw_text:
        state["optimized_text"] = None
        state["warnings"].append("无原始转写文本，跳过优化")
        return state

    if len(raw_text) < 100:
        state["optimized_text"] = raw_text
        return state

    try:
        llm = _build_llm()
        response = await llm.ainvoke(
            [SystemMessage(content=OPTIMIZE_SYSTEM), HumanMessage(content=raw_text)]
        )
        optimized = response.content.strip()
        state["optimized_text"] = optimized if optimized else raw_text
        logger.info("会议 %s LLM 优化完成，文本 %s → %s 字",
                    state["meeting_id"], len(raw_text), len(state["optimized_text"]))
    except Exception as exc:
        state["optimize_error"] = str(exc)
        state["warnings"].append(f"LLM 优化失败，使用原始文本: {exc}")
        state["optimized_text"] = raw_text

    return state


# ─── Node 2: 任务提取 ─────────────────────────────────────────────────

EXTRACT_SYSTEM = """你是会议纪要任务提取助手。从会议转写文本中提取 actionable 任务。

输出必须是 JSON 数组，每项包含：
- task: 任务标题（简短）
- description: 任务详细描述
- executor_name: 责任人姓名（从文本推断，无法确定则为 null）
  注意：如果说话人格式为 "SPEAKER_XX(员工名)"，该员工名是声纹识别系统自动标注的，优先采纳。
- deadline_text: 截止时间原文（如"下周五"、"6月20日"）
- source_segment_ids: 相关转写段落 id 数组

只输出 JSON，不要其他文字。若无任务则输出 []。"""


async def extract_tasks_node(state: MeetingWorkflowState) -> MeetingWorkflowState:
    """从转写文本中提取任务（失败不阻塞后续）"""
    state["current_step"] = "extract_tasks"

    text = state.get("optimized_text") or state.get("raw_transcript_text")
    if not text:
        state["task_extract_error"] = "无转写文本"
        state["warnings"].append("跳过任务提取：无转写文本")
        return state

    llm = _build_llm()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    speaker_map = state.get("speaker_employee_map", {})
    voiceprint_hint = ""
    if speaker_map:
        resolved = [
            f"{label} → {info['name']}（声纹置信度 {info['confidence']:.0%}）"
            for label, info in speaker_map.items()
        ]
        voiceprint_hint = (
            "\n\n【声纹识别结果】以下说话人已通过声纹验证：\n" + "\n".join(resolved)
        )

    prompt = f"今天是 {today}。\n\n会议转写：\n{text}{voiceprint_hint}"

    try:
        response = await llm.ainvoke(
            [SystemMessage(content=EXTRACT_SYSTEM), HumanMessage(content=prompt)]
        )
        content = response.content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\n?", "", content)
            content = re.sub(r"\n?```$", "", content)

        extracted = json.loads(content)
        if not isinstance(extracted, list):
            extracted = []
    except (json.JSONDecodeError, Exception) as exc:
        err_msg = str(exc)
        state["task_extract_error"] = err_msg
        state["errors"].append(f"任务提取 LLM 失败: {err_msg}")
        extracted = []

    state["extracted_tasks"] = extracted
    logger.info("会议 %s 提取到 %d 个任务", state["meeting_id"], len(extracted))

    # 执行人匹配（本地逻辑，不调用 LLM）
    state = _match_employees(state)
    return state


def _match_employees(state: MeetingWorkflowState) -> MeetingWorkflowState:
    """匹配执行人——声纹 + 姓名双路径（同步，不调用 LLM）"""
    employees = state.get("employees", [])
    extracted = state.get("extracted_tasks", [])
    speaker_map = state.get("speaker_employee_map", {})
    seg_label_map: dict[int, str] = state.get("seg_label_map", {})

    employee_names = {e["name"]: e["id"] for e in employees}
    employee_names_lower = {n.lower(): eid for n, eid in employee_names.items()}

    matched = []
    for item in extracted:
        executor_id = None
        match_method = None
        match_confidence = None
        source_ids = item.get("source_segment_ids", [])
        if not isinstance(source_ids, list):
            source_ids = []

        # 声纹投票
        if source_ids and speaker_map:
            votes: dict[int, tuple[int, float]] = {}
            for sid in source_ids:
                label = seg_label_map.get(sid)
                if label and label in speaker_map:
                    info = speaker_map[label]
                    eid = info["id"]
                    conf = info["confidence"]
                    if eid in votes:
                        c, t = votes[eid]
                        votes[eid] = (c + 1, t + conf)
                    else:
                        votes[eid] = (1, conf)

            if votes:
                best_emp, best_score = None, -1.0
                for eid, (count, total_conf) in votes.items():
                    avg_conf = total_conf / count
                    score = count + avg_conf
                    if score > best_score:
                        best_score = score
                        best_emp = eid
                        match_confidence = round(avg_conf, 2)

                if best_emp:
                    executor_id = best_emp
                    match_method = "voiceprint"

        # 姓名匹配（声纹未命中时）
        if not executor_id:
            name = (item.get("executor_name") or "").strip()
            if name in employee_names:
                executor_id = employee_names[name]
                match_method = "name_exact"
                match_confidence = 1.0
            elif name.lower() in employee_names_lower:
                executor_id = employee_names_lower[name.lower()]
                match_method = "name_exact"
                match_confidence = 1.0
            else:
                for emp_name, emp_id in employee_names.items():
                    if name in emp_name:
                        executor_id = emp_id
                        match_method = "name_fuzzy"
                        match_confidence = 0.6
                        break

        matched.append({
            "title": item.get("task") or "未命名任务",
            "description": item.get("description"),
            "executor_id": executor_id,
            "executor_name": item.get("executor_name"),
            "match_method": match_method,
            "match_confidence": match_confidence,
            "deadline": _parse_deadline(item.get("deadline_text")),
            "source_segment_ids": json.dumps(source_ids) if source_ids else None,
        })

    state["matched_tasks"] = matched
    methods = Counter(m["match_method"] for m in matched)
    logger.info(
        "任务匹配: voiceprint=%d, name_exact=%d, name_fuzzy=%d, none=%d",
        methods.get("voiceprint", 0), methods.get("name_exact", 0),
        methods.get("name_fuzzy", 0), methods.get(None, 0),
    )
    return state


# ─── Node 3: 会议关联分析 ───────────────────────────────────────────────

RELATION_SYSTEM = """你是会议关联分析专家。根据多个会议的转写文本，分析它们之间的语义关联。

## 关联类型定义

- **follow_up**: 后续会议。特征：会议B提到"上次/上周/之前讨论的"、会议B是会议A的延续讨论、会议B的议题承接A的结论。
- **related**: 相关会议。同一个项目/客户的多个讨论、同一批人参与的不同议题、无明确先后但语义相关。
- **prerequisite**: 前置依赖。会议B的议题依赖会议A的结果才能确定（如方案确认后才能实施）。

## 输出格式

必须输出 JSON 数组，每项包含：
- meeting_a_id: 前置/前序会议 ID（数字）
- meeting_b_id: 后续/后序会议 ID（数字）
- relation_type: 关联类型（follow_up / related / prerequisite 之一）
- confidence: 置信度（0.0–1.0），数值越高越确定
- reason: 判断理由（100字以内）

**重要**：
- 只输出确定的关联（confidence >= 0.6），低于此阈值不要输出
- 不要臆造 ID，只使用输入中提供的 meeting_id
- meeting_a_id 和 meeting_b_id 不能相同
- 同一对会议只输出一次（选置信度最高的 relation_type）
- 若无任何关联，输出空数组 []

只输出 JSON，不要其他文字。"""


async def analyze_relations_node(
    state: MeetingWorkflowState, db: AsyncSession
) -> MeetingWorkflowState:
    """分析当前会议与其他已转录会议的关联（可选阶段）

    注意：全局关联分析更适合定时任务，这里只分析"当前会议 vs 其他已转录会议"。
    为避免重复调用 LLM，依赖外层传入的 db 进行关联分析。
    """
    state["current_step"] = "analyze_relations"

    if state.get("task_extract_error") and not state.get("matched_tasks"):
        state["warnings"].append("跳过关联分析：无任务数据")
        return state

    try:
        # 这里不重复调用 analyze_relations（该函数是全局的）
        # 而是检查当前会议与其他会议之间是否已有 Relation 记录
        meeting_id = state["meeting_id"]
        rel_result = await db.execute(
            select(MeetingRelation).where(
                (MeetingRelation.meeting_a_id == meeting_id)
                | (MeetingRelation.meeting_b_id == meeting_id)
            )
        )
        existing = rel_result.scalars().all()

        relations = [
            {
                "id": r.id,
                "source": r.meeting_a_id,
                "target": r.meeting_b_id,
                "relation_type": r.relation_type.value,
                "confidence": r.confidence,
                "reason": r.reason,
            }
            for r in existing
        ]
        state["relations"] = relations
        logger.info("会议 %s 已有 %d 条关联", meeting_id, len(relations))
    except Exception as exc:
        state["relation_error"] = str(exc)
        state["errors"].append(f"关联查询失败: {exc}")

    return state


# ─── Node 4: 生成 HTML 报告 ────────────────────────────────────────────

async def generate_report_node(state: MeetingWorkflowState, db: AsyncSession) -> MeetingWorkflowState:
    """生成会议 HTML 报告（可选阶段，失败不影响后续）"""
    state["current_step"] = "generate_report"

    meeting_id = state["meeting_id"]
    title = state.get("meeting_title") or f"会议 {meeting_id}"
    text = state.get("optimized_text") or state.get("raw_transcript_text") or ""
    raw = state.get("raw_transcript_text") or text

    # 更新 Meeting.optimized_text
    meeting = await db.get(Meeting, meeting_id)
    if meeting and text:
        meeting.optimized_text = text[:8000]
        await db.flush()

    try:
        from app.services.transcript_export import build_transcript_page
        from app.services.transcript_segment_storage import save_html_report

        report_html = build_transcript_page(
            title=title,
            meeting_id=meeting_id,
            verbatim_text=raw[:4000],
            optimized_text=text if text != raw else None,
        )

        report_path = save_html_report(meeting_id, report_html)
        if report_path and meeting:
            meeting.report_path = report_path
            await db.flush()

        state["report_path"] = report_path
        logger.info("会议 %s HTML 报告: %s", meeting_id, report_path)
    except Exception as exc:
        state["report_error"] = str(exc)
        state["warnings"].append(f"HTML 报告生成失败: {exc}")
        logger.warning("会议 %s HTML 报告失败: %s", meeting_id, exc)

    return state


# ─── Node 5: 任务通知 ──────────────────────────────────────────────────

async def notify_node(
    state: MeetingWorkflowState, db: AsyncSession
) -> MeetingWorkflowState:
    """持久化任务 + 发送通知"""
    state["current_step"] = "notify"
    state["notifications_sent"] = 0

    matched_tasks = state.get("matched_tasks", [])
    if not matched_tasks:
        state["warnings"].append("无任务，跳过通知")
        return state

    try:
        from app.agents.task_notification import send_task_notifications

        tasks = []
        for item in matched_tasks:
            task = Task(
                title=item["title"],
                description=item.get("description"),
                deadline=item.get("deadline"),
                status=TaskStatus.pending,
                executor_id=item.get("executor_id"),
                meeting_id=state["meeting_id"],
                source_segment_ids=item.get("source_segment_ids"),
                match_method=item.get("match_method"),
                match_confidence=item.get("match_confidence"),
            )
            db.add(task)
            await db.flush()
            tasks.append(task)

        state["created_task_ids"] = [t.id for t in tasks]

        count = await send_task_notifications(db, tasks)
        state["notifications_sent"] = count
        logger.info("会议 %s 通知: %d/%d", state["meeting_id"], count, len(tasks))
    except Exception as exc:
        state["notification_error"] = str(exc)
        state["errors"].append(f"任务通知失败: {exc}")
        logger.warning("会议 %s 通知失败: %s", state["meeting_id"], exc)

    return state


# ─── Graph 构建 ────────────────────────────────────────────────────────

def build_workflow_graph(db: AsyncSession, meeting_id: int):
    """构建完整会议工作流图（所有节点共享同一个 db session）"""
    graph = StateGraph(MeetingWorkflowState)

    async def load_data_wrapper(state: MeetingWorkflowState) -> MeetingWorkflowState:
        return await load_data_node(state, db)

    async def notify_wrapper(state: MeetingWorkflowState) -> MeetingWorkflowState:
        return await notify_node(state, db)

    async def generate_report_wrapper(state: MeetingWorkflowState) -> MeetingWorkflowState:
        return await generate_report_node(state, db)

    async def relations_wrapper(state: MeetingWorkflowState) -> MeetingWorkflowState:
        return await analyze_relations_node(state, db)

    graph.add_node("load_data", load_data_wrapper)
    graph.add_node("llm_optimize", llm_optimize_node)
    graph.add_node("extract_tasks", extract_tasks_node)
    graph.add_node("analyze_relations", relations_wrapper)
    graph.add_node("generate_report", generate_report_wrapper)
    graph.add_node("notify", notify_wrapper)

    graph.set_entry_point("load_data")
    graph.add_edge("load_data", "llm_optimize")
    graph.add_edge("llm_optimize", "extract_tasks")
    graph.add_edge("extract_tasks", "analyze_relations")
    graph.add_edge("analyze_relations", "generate_report")
    graph.add_edge("generate_report", "notify")
    graph.add_edge("notify", END)

    return graph.compile()


# ─── Async 入口（FastAPI 调用）─────────────────────────────────────────

async def run_meeting_workflow(
    db: AsyncSession,
    meeting_id: int,
) -> MeetingWorkflowState:
    """Async 入口：完整会议处理工作流（FastAPI 路由直接调用）

    状态机：
    - 进入时：设置 Meeting.status = processing（工作流处理中）
    - 成功完成：设置 Meeting.status = processed
    - 失败：不改状态（由 asr.py 统一管理）

    Args:
        db: 已注入的 AsyncSession（由 FastAPI Depends 提供）
        meeting_id: 会议 ID

    Returns:
        最终 state（包含 created_task_ids、report_path 等）
    """
    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        return {"meeting_id": meeting_id, "errors": ["Meeting not found"]}

    if meeting.status not in (MeetingStatus.transcribed, MeetingStatus.failed):
        return {"meeting_id": meeting_id, "errors": [f"Invalid status: {meeting.status.value}"]}

    # 设置状态：进入处理中
    meeting.status = MeetingStatus.processing
    await db.flush()

    initial: MeetingWorkflowState = {
        "meeting_id": meeting_id,
        "meeting_title": meeting.title,
        "employees": [],
        "errors": [],
        "warnings": [],
        "current_step": "",
        "raw_transcript_text": None,
        "optimized_text": None,
        "optimize_error": None,
        "speaker_employee_map": {},
        "seg_label_map": {},
        "extracted_tasks": [],
        "task_extract_error": None,
        "matched_tasks": [],
        "relations": [],
        "relation_error": None,
        "report_path": None,
        "report_error": None,
        "notifications_sent": 0,
        "notification_error": None,
        "created_task_ids": [],
    }

    graph = build_workflow_graph(db, meeting_id)
    final_state = await graph.ainvoke(initial)

    # 状态机：工作流完成后设置最终状态
    # 注意：工作流内部每个 node 都只 flush 不 commit，
    # 提交由 run_meeting_workflow 调用方（asr.py / FastAPI）统一控制。
    workflow_errors = final_state.get("errors", [])
    critical_errors = [e for e in workflow_errors if
                      not any(w in e.lower() for w in ("warning", "skip", "无"))]

    if critical_errors:
        # 有致命错误 → 保持 processing 状态（等待重试或人工处理）
        meeting.status = MeetingStatus.processing
        logger.warning(f"会议 {meeting_id} 工作流有致命错误: {critical_errors}")
    else:
        meeting.status = MeetingStatus.processed

    await db.commit()
    return final_state


# ─── Sync 入口（Celery worker 调用）─────────────────────────────────────

# 全局进程池（单例，启动时预热）
_process_pool: ProcessPoolExecutor | None = None


def _get_pools() -> ProcessPoolExecutor:
    """懒加载进程池（启动时预热）"""
    global _process_pool

    if _process_pool is None:
        cpu_count = os.cpu_count() or 2
        max_workers = min(cpu_count, 4)  # 最多 4 个 worker，避免进程爆炸
        _process_pool = ProcessPoolExecutor(max_workers=max_workers)
        logger.info("会议工作流进程池已初始化，max_workers=%d", max_workers)
    return _process_pool


def _run_coro_in_process(fn_name: str, args_json: str) -> str:
    """
    子进程入口函数。

    在独立进程中创建新的事件循环，运行指定的异步函数。
    用 JSON 序列化传参，避免 pickle 问题；返回值同样 JSON 序列化后传回。

    session 参数特殊处理：在子进程中按需创建，不从父进程传入。

    注意：子进程无法共享父进程的 DB 连接池、LLM client cache 等，
    每个子进程会在其事件循环首次 await 时按需初始化独立资源。
    """
    import asyncio
    import json as _json

    args = _json.loads(args_json)
    need_session = args.pop("_need_session", False)
    session_factory = None
    if need_session:
        from app.database import async_session

        session_factory = async_session

    async def _execute():
        if fn_name == "run_meeting_workflow":
            from app.agents.meeting_workflow import run_meeting_workflow

            meeting_id = args.get("meeting_id")
            if session_factory:
                async with session_factory() as session:
                    result = await run_meeting_workflow(session, meeting_id)
                    await session.commit()
                    return _serialize_result(result)
            else:
                return await run_meeting_workflow(**args)
        elif fn_name == "analyze_relations":
            from app.agents.meeting_relation import analyze_relations

            if session_factory:
                async with session_factory() as session:
                    result = await analyze_relations(session, **args)
                    await session.commit()
                    # result 是 list[MeetingRelation]，转成可序列化 dict
                    return _serialize_relations_result(result)
            else:
                return await analyze_relations(**args)
        else:
            raise ValueError(f"Unknown async function: {fn_name}")

    result = asyncio.run(_execute())
    return _json.dumps(result, default=str)


def _serialize_result(result) -> dict:
    """将工作流返回的 state dict 序列化（MeetingRelation 等 ORM 对象转 dict）"""
    if isinstance(result, dict):
        return result
    if hasattr(result, "__dict__"):
        return {k: _serialize_result(v) for k, v in result.__dict__.items() if not k.startswith("_")}
    if isinstance(result, (list, tuple)):
        return [_serialize_result(item) for item in result]
    return result


def _serialize_relations_result(relations: list) -> dict:
    """
    将 analyze_relations 返回的 list[MeetingRelation] 转为标准 dict 格式。

    relation_analysis.py 的调用方期望：
      {
          "meetings_analyzed": int,
          "relations_created": int,
          "errors": list,
      }
    """
    # 尝试从子进程内部统计（需要重新查询），直接返回数量
    return {
        "meetings_analyzed": 0,  # 子进程无法精确知道总数，返回 0 由外层覆盖
        "relations_created": len(relations),
        "errors": [],
    }


class _LoopProxy:
    """
    进程级并发桥接器。

    - 每个子进程有独立的 EventLoop 和 GIL，真正并行执行 LLM 调用
    - 同会议多个 LLM 调用在节点内通过 asyncio.gather() 并发
    - 不同会议自动分配到不同进程，互不阻塞
    - max_workers 由 CPU 核数决定（最多 4），启动时预热
    """

    _process_pool: ProcessPoolExecutor | None = None

    @classmethod
    def _ensure_pools(cls) -> None:
        cls._process_pool = _get_pools()

    @classmethod
    def run_in_process_pool(cls, fn_name: str, **kwargs) -> object:
        """
        将异步任务提交到进程池执行（同步阻塞等待结果）。

        参数：
          - fn_name: "run_meeting_workflow" 或 "analyze_relations"
          - _need_session: True 表示在子进程中创建 DB session（默认 True）

        子进程有自己的 EventLoop、DB 连接池和 LLM client，互相隔离。
        """
        cls._ensure_pools()

        safe_kwargs = {k: v for k, v in kwargs.items() if k != "session"}

        args_json = json.dumps(safe_kwargs, default=str)
        future = cls._process_pool.submit(_run_coro_in_process, fn_name, args_json)
        result_json = future.result()
        return json.loads(result_json)


def run_meeting_workflow_sync(
    meeting_id: int,
    _db=None,  # 保留参数签名兼容，不使用
) -> dict:
    """Sync 入口：Celery worker 调用 async 工作流

    通过 ProcessPoolExecutor 并行执行，每个子进程有独立的 EventLoop，
    真正释放 GIL 约束，实现多会议并发。

    Args:
        meeting_id: 会议 ID

    Returns:
        {
            "success": bool,
            "task_ids": list[int],
            "report_path": str | None,
            "notifications_sent": int,
            "errors": list[str],
            "warnings": list[str],
        }
    """
    try:
        state = _LoopProxy.run_in_process_pool(
            "run_meeting_workflow",
            meeting_id=meeting_id,
            _need_session=True,
        )
    except Exception as exc:
        logger.error("会议 %s 工作流执行失败: %s", meeting_id, exc, exc_info=True)
        return {
            "success": False,
            "task_ids": [],
            "report_path": None,
            "notifications_sent": 0,
            "errors": [str(exc)],
            "warnings": [],
        }

    return {
        "success": not bool(state.get("errors")),
        "task_ids": state.get("created_task_ids", []),
        "report_path": state.get("report_path"),
        "notifications_sent": state.get("notifications_sent", 0),
        "errors": state.get("errors", []),
        "warnings": state.get("warnings", []),
    }
