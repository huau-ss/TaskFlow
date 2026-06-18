"""任务通知 Agent - 负责在任务创建后发送消息通知

声纹融合：根据匹配方式定制通知内容，让接收方了解任务来源的可信度。
"""

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, Employee, TranscriptSegment, TaskStatus, MessageType
from app.services.message import create_task_notification, create_response_message

if TYPE_CHECKING:
    from app.agents.task_extract import AgentState


# 匹配方式 → 通知内容描述
MATCH_METHOD_LABEL = {
    "voiceprint": "（🎙️ 声纹识别确认）",
    "name_exact": "（📝 姓名精确匹配）",
    "name_fuzzy": "（📝 姓名模糊匹配）",
}


def _build_notification_content(task: Task) -> str:
    """构建通知内容，根据匹配方式定制"""
    deadline_str = (
        task.deadline.strftime("%Y-%m-%d %H:%M") if task.deadline else "未设置截止时间"
    )

    match_note = ""
    if task.match_method and task.match_method in MATCH_METHOD_LABEL:
        match_note = f"\n分配方式：{MATCH_METHOD_LABEL[task.match_method]}"
        if task.match_confidence is not None:
            match_note += f" 置信度 {task.match_confidence:.0%}"

    return f"会议任务：{task.title}\n截止时间：{deadline_str}{match_note}"


async def send_task_notifications(
    db: AsyncSession, tasks: list[Task]
) -> int:
    """为创建的任务发送通知消息

    声纹融合说明：
    - 优先使用声纹识别结果（TranscriptSegment.employee_id）
    - 如果没有声纹结果，回退到 AI 姓名匹配
    - 通知内容会标明匹配方式，提升透明度

    Returns:
        创建的消息数量
    """
    message_count = 0

    for task in tasks:
        if not task.executor_id:
            continue

        # 获取执行人信息
        emp_result = await db.execute(
            select(Employee).where(Employee.id == task.executor_id)
        )
        executor = emp_result.scalar_one_or_none()

        if not executor:
            continue

        # 构建带声纹上下文的通知内容
        content = _build_notification_content(task)

        # 创建任务通知消息
        await create_task_notification(
            db=db,
            task=task,
            employee_id=executor.id,
            content=content,
        )
        message_count += 1

    await db.commit()
    return message_count


def match_executor_from_segment(
    segments: list["TranscriptSegment"],
    employees: list[dict],
    source_segment_ids: list[int] | None = None,
) -> tuple[int | None, str | None, float | None]:
    """从转写片段匹配执行人

    声纹融合 + AI 姓名匹配的备用函数（供外部调用）。

    Returns:
        (employee_id, match_method, confidence)
        match_method: "voiceprint", "name_exact", "name_fuzzy", 或 None
    """
    if not source_segment_ids:
        return None, None, None

    # 构建员工名称映射
    employee_names = {emp["name"]: emp["id"] for emp in employees}

    # 1. 优先声纹识别
    # 注意：此函数无法获取实际余弦相似度（不存储在 TranscriptSegment 中），
    # 返回保守估计值。主流程 task_extract.py 使用 speaker_employee_map 中的置信度。
    for seg in segments:
        if seg.id in source_segment_ids and seg.employee_id:
            return seg.employee_id, "voiceprint", 0.5  # 保守估计，仅标记为声纹匹配

    # 2. AI 姓名匹配备用
    # 此逻辑在主 task_extract.py 中完成
    return None, None, None


async def notify_task_creation(
    db: AsyncSession,
    task: Task,
    source_segments: list[TranscriptSegment] | None = None,
) -> bool:
    """通知单个任务创建，带声纹上下文"""
    if not task.executor_id:
        return False

    try:
        content = _build_notification_content(task)
        message = await create_task_notification(
            db=db,
            task=task,
            employee_id=task.executor_id,
            content=content,
        )
        await db.commit()
        return True
    except Exception:
        await db.rollback()
        return False


async def notify_task_status_change(
    db: AsyncSession,
    task: Task,
    old_status: TaskStatus,
    new_status: TaskStatus,
) -> bool:
    """通知任务状态变更"""
    if old_status == new_status:
        return False

    if task.meeting_id and task.executor_id:
        try:
            emp_result = await db.execute(
                select(Employee).where(Employee.id == task.executor_id)
            )
            executor = emp_result.scalar_one_or_none()

            if executor and executor.manager_id:
                await create_response_message(
                    db=db,
                    task=task,
                    recipient_id=executor.manager_id,
                    action=new_status.value,
                    actor_name=executor.name or "未知",
                )
                await db.commit()
                return True
        except Exception:
            await db.rollback()

    return False
