"""消息服务 - 负责消息的创建、查询和操作"""
import secrets
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Message, MessageAction, MessageType, Task, TaskStatus


def generate_action_token() -> str:
    """生成唯一的操作令牌"""
    return secrets.token_urlsafe(32)


async def create_message(
    db: AsyncSession,
    *,
    msg_type: MessageType,
    title: str,
    recipient_id: int,
    content: str | None = None,
    task_id: int | None = None,
    sender_id: int | None = None,
) -> Message:
    """创建一条新消息"""
    token = generate_action_token()
    message = Message(
        type=msg_type,
        title=title,
        content=content,
        recipient_id=recipient_id,
        task_id=task_id,
        sender_id=sender_id,
        action_token=token,
        action_url=f"/tasks/{task_id}/reply?token={token}" if task_id else None,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


async def get_user_messages(
    db: AsyncSession,
    user_id: int,
    *,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Message], int]:
    """获取用户的消息列表"""
    query = (
        select(Message)
        .options(selectinload(Message.actions))
        .where(Message.recipient_id == user_id)
    )
    if unread_only:
        query = query.where(Message.is_read == False)
    query = query.order_by(Message.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    messages = list(result.scalars().all())

    # 获取总数
    count_query = select(func.count()).select_from(Message).where(Message.recipient_id == user_id)
    if unread_only:
        count_query = count_query.where(Message.is_read == False)
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    return messages, total


async def get_unread_count(db: AsyncSession, user_id: int) -> int:
    """获取用户未读消息数量"""
    query = select(func.count()).select_from(Message).where(
        Message.recipient_id == user_id,
        Message.is_read == False,
    )
    result = await db.execute(query)
    return result.scalar() or 0


async def mark_message_read(db: AsyncSession, message_id: int, user_id: int) -> Message | None:
    """标记消息为已读"""
    query = select(Message).where(
        Message.id == message_id,
        Message.recipient_id == user_id,
    )
    result = await db.execute(query)
    message = result.scalar_one_or_none()
    if message and not message.is_read:
        message.is_read = True
        message.read_at = datetime.utcnow()
        await db.flush()
        await db.refresh(message)
    return message


async def get_message_by_id(db: AsyncSession, message_id: int, user_id: int) -> Message | None:
    """获取消息详情"""
    query = select(Message).options(selectinload(Message.actions)).where(
        Message.id == message_id,
        Message.recipient_id == user_id,
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def record_message_action(
    db: AsyncSession,
    message_id: int,
    action: str,
    reason: str | None = None,
) -> MessageAction:
    """记录消息操作（接受/拒绝/完成/未完成）"""
    action_record = MessageAction(
        message_id=message_id,
        action=action,
        reason=reason,
    )
    db.add(action_record)
    await db.flush()
    await db.refresh(action_record)
    return action_record


async def get_message_by_token(db: AsyncSession, token: str) -> Message | None:
    """通过 token 获取消息（用于外部链接操作）"""
    query = select(Message).where(Message.action_token == token)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_task_notification(
    db: AsyncSession,
    task: Task,
    employee_id: int,
    content: str | None = None,
) -> Message:
    """创建任务通知消息"""
    if content is None:
        deadline_str = task.deadline.strftime("%Y-%m-%d %H:%M") if task.deadline else "未设置截止时间"
        content = f"会议任务：{task.title}\n截止时间：{deadline_str}"

    return await create_message(
        db,
        msg_type=MessageType.task_created,
        title=f"📋 新任务：{task.title}",
        content=content,
        recipient_id=employee_id,
        task_id=task.id,
    )


async def create_reminder_message(
    db: AsyncSession,
    task: Task,
    employee_id: int,
    reminder_type: str = "deadline_soon",
) -> Message:
    """创建任务到期提醒消息"""
    if reminder_type == "deadline_soon":
        title = f"⏰ 任务即将到期：{task.title}"
        content = f"任务「{task.title}」即将到达截止时间，请尽快处理。"
    else:
        title = f"⚠️ 任务已逾期：{task.title}"
        content = f"任务「{task.title}」已超过截止时间，请及时处理。"

    return await create_message(
        db,
        msg_type=MessageType.task_reminder,
        title=title,
        content=content,
        recipient_id=employee_id,
        task_id=task.id,
    )


async def create_escalation_message(
    db: AsyncSession,
    task: Task,
    manager_id: int,
    executor_name: str,
    reason: str,
) -> Message:
    """创建任务升级通知消息"""
    title = f"📈 任务升级：{task.title}"
    content = f"员工「{executor_name}」无法完成任务「{task.title}」。\n\n原因：{reason}\n\n请及时处理或分配给其他人。"

    return await create_message(
        db,
        msg_type=MessageType.task_escalation,
        title=title,
        content=content,
        recipient_id=manager_id,
        task_id=task.id,
    )


async def create_response_message(
    db: AsyncSession,
    task: Task,
    recipient_id: int,
    action: str,
    actor_name: str,
) -> Message:
    """创建任务回复通知消息（如员工接受了任务，通知创建者）"""
    action_text = {
        "accepted": "接受了",
        "rejected": "拒绝了",
        "completed": "完成了",
        "incomplete": "标记未完成",
    }.get(action, action)

    title = f"📝 任务状态更新：{task.title}"
    content = f"员工「{actor_name}」{action_text}了任务「{task.title}」。"

    return await create_message(
        db,
        msg_type=MessageType.task_response,
        title=title,
        content=content,
        recipient_id=recipient_id,
        task_id=task.id,
    )
