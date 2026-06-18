"""任务通知 Agent - 负责在任务创建后发送消息通知"""

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, Employee, TranscriptSegment, TaskStatus, MessageType
from app.services.message import create_task_notification, create_response_message

if TYPE_CHECKING:
    from app.agents.task_extract import AgentState


async def send_task_notifications(db: AsyncSession, tasks: list[Task]) -> list[int]:
    """为创建的任务发送通知消息

    任务分配逻辑（声纹识别 + AI 姓名匹配）：

    1. 优先使用转写片段中声纹识别到的 employee_id
    2. 如果没有，尝试 AI 从文本提取的姓名进行模糊匹配
    3. 如果都没匹配到，executor_id 为 null，不发送通知

    Returns:
        创建的消息数量
    """
    message_count = 0

    for task in tasks:
        if not task.executor_id:
            continue

        # 获取执行人信息
        emp_result = await db.execute(select(Employee).where(Employee.id == task.executor_id))
        executor = emp_result.scalar_one_or_none()

        if not executor:
            continue

        # 创建任务通知消息
        await create_task_notification(
            db=db,
            task=task,
            employee_id=executor.id,
        )
        message_count += 1

    await db.commit()
    return message_count


def match_executor_from_segment(
    segments: list["TranscriptSegment"],
    employees: list[dict],
    source_segment_ids: list[int] | None = None,
) -> tuple[int | None, str | None]:
    """从转写片段匹配执行人

    结合两种方式：
    1. 声纹识别：如果片段中有 employee_id，使用它
    2. AI 姓名匹配：作为备用方案

    Args:
        segments: 转写片段列表
        employees: 员工列表
        source_segment_ids: 任务来源的片段 ID 列表

    Returns:
        (matched_employee_id, match_method)
        match_method: "voiceprint", "name_match", 或 None
    """
    if not source_segment_ids:
        return None, None

    # 1. 优先使用声纹识别结果
    for seg in segments:
        if seg.id in source_segment_ids and seg.employee_id:
            return seg.employee_id, "voiceprint"

    # 2. AI 姓名匹配（由 task_extract.py 已完成，这里只做备用）
    # 如果所有片段都没有识别到员工，返回 None
    return None, None


async def notify_task_creation(
    db: AsyncSession,
    task: Task,
    source_segments: list[TranscriptSegment] | None = None,
) -> bool:
    """通知单个任务创建

    这个函数可以在任务提取后单独调用，也可以在定时任务中使用

    Returns:
        是否成功发送通知
    """
    if not task.executor_id:
        return False

    try:
        message = await create_task_notification(
            db=db,
            task=task,
            employee_id=task.executor_id,
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
    """通知任务状态变更

    当任务状态发生重要变更时，通知相关人员

    Returns:
        是否成功发送通知
    """
    if old_status == new_status:
        return False

    # 如果任务有来源会议，通知会议创建者
    if task.meeting_id and task.executor_id:
        try:
            emp_result = await db.execute(select(Employee).where(Employee.id == task.executor_id))
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
