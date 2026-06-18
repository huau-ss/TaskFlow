"""LangGraph agent: extract tasks from transcript and match employees."""

import json
import re
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


def _format_transcript(segments: list[TranscriptSegment]) -> tuple[str, list[dict]]:
    seg_data = []
    lines = []
    for seg in sorted(segments, key=lambda s: s.sequence):
        seg_data.append(
            {
                "id": seg.id,
                "speaker": seg.speaker_label,
                "text": seg.text,
                "start_time": seg.start_time,
                "end_time": seg.end_time,
            }
        )
        lines.append(f"[{seg.id}] {seg.speaker_label}: {seg.text}")
    return "\n".join(lines), seg_data


EXTRACT_SYSTEM = """你是会议纪要任务提取助手。从会议转写文本中提取 actionable 任务。
输出必须是 JSON 数组，每项包含：
- task: 任务标题（简短）
- description: 任务详细描述
- executor_name: 责任人姓名（从文本推断，无法确定则为 null）
- deadline_text: 截止时间原文（如"下周五"、"6月20日"）
- source_segment_ids: 相关转写段落 id 数组

只输出 JSON，不要其他文字。若无任务则输出 []。"""


async def extract_tasks_node(state: AgentState) -> AgentState:
    llm = _build_llm()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    prompt = f"今天是 {today}。\n\n会议转写：\n{state['transcript_text']}"
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
    """加载员工列表和转写片段信息"""
    from sqlalchemy.orm import selectinload

    # 加载员工列表
    emp_result = await db.execute(select(Employee).where(Employee.is_active.is_(True)))
    employees = emp_result.scalars().all()
    state["employees"] = [{"id": e.id, "name": e.name, "email": e.email} for e in employees]

    # 加载转写片段信息（包含声纹识别结果）
    seg_result = await db.execute(
        select(TranscriptSegment).where(TranscriptSegment.meeting_id == state["meeting_id"])
    )
    segments = seg_result.scalars().all()

    # 将片段信息添加到 state（用于声纹识别匹配）
    state["segments"] = [
        {
            "id": seg.id,
            "speaker_label": seg.speaker_label,
            "employee_id": seg.employee_id,  # 声纹识别结果
            "text": seg.text,
        }
        for seg in segments
    ]

    return state


def _fuzzy_match_name(name: str | None, employees: list[dict]) -> int | None:
    if not name or not employees:
        return None
    name = name.strip()
    for emp in employees:
        if emp["name"] == name:
            return emp["id"]
    for emp in employees:
        if name in emp["name"] or emp["name"] in name:
            return emp["id"]
    return None


def _parse_deadline(deadline_text: str | None, reference: datetime | None = None) -> datetime | None:
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


async def match_employees_node(state: AgentState) -> AgentState:
    """匹配执行人 - 结合声纹识别和AI姓名匹配

    优先级：
    1. 声纹识别结果（片段中已有 employee_id）
    2. AI 姓名匹配（从文本提取责任人姓名）
    """
    # 构建片段映射：segment_id -> employee_id (声纹识别)
    segment_to_employee = {}
    for seg in state.get("segments", []):
        if seg.get("employee_id"):
            segment_to_employee[seg["id"]] = seg["employee_id"]

    # 构建员工名称映射
    employee_names = {emp["name"]: emp["id"] for emp in state["employees"]}

    matched = []
    for item in state["extracted_tasks"]:
        executor_id = None
        match_method = None

        # 1. 优先使用声纹识别结果
        source_segment_ids = item.get("source_segment_ids", [])
        if source_segment_ids and segment_to_employee:
            for seg_id in source_segment_ids:
                if seg_id in segment_to_employee:
                    executor_id = segment_to_employee[seg_id]
                    match_method = "voiceprint"
                    break

        # 2. 如果没有声纹结果，使用 AI 姓名匹配
        if not executor_id:
            extracted_name = item.get("executor_name")
            if extracted_name:
                # 精确匹配
                if extracted_name in employee_names:
                    executor_id = employee_names[extracted_name]
                    match_method = "name_exact"
                else:
                    # 模糊匹配
                    for emp_name, emp_id in employee_names.items():
                        if extracted_name in emp_name or emp_name in extracted_name:
                            executor_id = emp_id
                            match_method = "name_fuzzy"
                            break

        segment_ids = item.get("source_segment_ids", [])
        if isinstance(segment_ids, list):
            segment_ids_str = json.dumps(segment_ids)
        else:
            segment_ids_str = None

        matched.append(
            {
                "title": item.get("task", "未命名任务"),
                "description": item.get("description"),
                "executor_id": executor_id,
                "executor_name": item.get("executor_name"),
                "match_method": match_method,
                "deadline": _parse_deadline(item.get("deadline_text")),
                "source_segment_ids": segment_ids_str,
            }
        )

    state["matched_tasks"] = matched
    return state


async def persist_tasks_node(state: AgentState, db: AsyncSession, meeting_id: int) -> AgentState:
    """持久化任务并发送通知"""
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
        )
        db.add(task)
        await db.flush()
        created_ids.append(task.id)
        created_tasks.append(task)

    state["created_task_ids"] = created_ids

    # 发送任务通知（结合声纹识别 + AI姓名匹配的结果）
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
    transcript_text, _ = _format_transcript(meeting.segments)
    if not transcript_text.strip():
        return []

    initial: AgentState = {
        "meeting_id": meeting.id,
        "transcript_text": transcript_text,
        "segments": [],
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
    result = await db.execute(select(Task).where(Task.id.in_(created_ids)).order_by(Task.id))
    return list(result.scalars().all())
