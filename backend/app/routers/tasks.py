"""任务管理 API 路由"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.deps import get_current_user
from app.models import Employee, Task, TaskStatus, Message
from app.schemas import (
    TaskDetailResponse,
    TaskListResponse,
    TaskReplyRequest,
    TaskReplyResponse,
    TaskResponse,
)
from app.services import message as message_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    status_filter: str | None = Query(None, alias="status", description="过滤状态: pending, accepted, in_progress, completed, overdue"),
    executor_id: int | None = Query(None, description="执行人ID"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """获取任务列表"""
    query = (
        select(Task)
        .options(selectinload(Task.executor), selectinload(Task.meeting), selectinload(Task.updates))
        .where(Task.executor_id == current_user.id)
    )

    if status_filter:
        try:
            status_enum = TaskStatus(status_filter)
            query = query.where(Task.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter}")

    query = query.order_by(Task.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    tasks = list(result.scalars().all())

    count_query = select(func.count()).select_from(Task).where(Task.executor_id == current_user.id)
    if status_filter:
        count_query = count_query.where(Task.status == TaskStatus(status_filter))
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    task_responses = []
    for t in tasks:
        task_responses.append(TaskDetailResponse(
            id=t.id,
            title=t.title,
            description=t.description,
            deadline=t.deadline,
            status=t.status,
            executor_id=t.executor_id,
            meeting_id=t.meeting_id,
            source_segment_ids=t.source_segment_ids,
            created_at=t.created_at,
            executor_name=t.executor.name if t.executor else None,
            meeting_title=t.meeting.title if t.meeting else None,
            actions=[],
        ))

    return TaskListResponse(tasks=task_responses, total=total)


@router.get("/{task_id}", response_model=TaskDetailResponse)
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """获取任务详情"""
    query = (
        select(Task)
        .options(selectinload(Task.executor), selectinload(Task.meeting), selectinload(Task.updates))
        .where(Task.id == task_id)
    )
    result = await db.execute(query)
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskDetailResponse(
        id=task.id,
        title=task.title,
        description=task.description,
        deadline=task.deadline,
        status=task.status,
        executor_id=task.executor_id,
        meeting_id=task.meeting_id,
        source_segment_ids=task.source_segment_ids,
        created_at=task.created_at,
        executor_name=task.executor.name if task.executor else None,
        meeting_title=task.meeting.title if task.meeting else None,
        actions=[],
    )


@router.post("/{task_id}/reply", response_model=TaskReplyResponse)
async def reply_to_task(
    task_id: int,
    body: TaskReplyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """任务操作回复

    支持的操作：
    - accept: 接受任务
    - reject: 拒绝任务（需填写 reason）
    - complete: 完成任务
    - incomplete: 标记未完成（需填写 reason）
    """
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    action = body.action.lower()
    if action not in ("accept", "reject", "complete", "incomplete"):
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

    if action in ("reject", "incomplete") and not body.reason:
        raise HTTPException(status_code=400, detail=f"Reason required for action: {action}")

    # 更新任务状态
    status_mapping = {
        "accept": TaskStatus.in_progress,
        "reject": TaskStatus.rejected,
        "complete": TaskStatus.completed,
        "incomplete": TaskStatus.incomplete,
    }
    task.status = status_mapping[action]
    await db.flush()

    # 记录操作到消息
    msg_query = select(Message).where(Message.task_id == task_id, Message.action_token.isnot(None))
    msg_result = await db.execute(msg_query)
    message = msg_result.scalar_one_or_none()

    if message:
        await message_service.record_message_action(
            db, message.id, action, body.reason
        )

    # 通知任务执行人的上级：员工接受了/拒绝了/完成了/未完成任务
    if task.executor_id:
        executor_result = await db.execute(
            select(Employee).where(Employee.id == task.executor_id)
        )
        executor = executor_result.scalar_one_or_none()

        if executor and executor.manager_id:
            await message_service.create_response_message(
                db, task, executor.manager_id, action, executor.name or "未知"
            )

    await db.commit()
    await db.refresh(task)

    return TaskReplyResponse(
        success=True,
        message=f"Task {action}d successfully",
        task=TaskResponse.model_validate(task),
    )


@router.post("/{task_id}/reply-by-token", response_model=TaskReplyResponse)
async def reply_to_task_by_token(
    task_id: int,
    body: TaskReplyRequest,
    token: str = Query(..., description="操作令牌"),
    db: AsyncSession = Depends(get_db),
):
    """通过 token 匿名操作任务（用于外部链接）"""
    message = await message_service.get_message_by_token(db, token)
    if not message:
        raise HTTPException(status_code=404, detail="Invalid token")
    if message.task_id != task_id:
        raise HTTPException(status_code=400, detail="Token does not match task")

    # 临时设置当前用户为接收者，以便复用 reply_to_task 逻辑
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    action = body.action.lower()
    if action not in ("accept", "reject", "complete", "incomplete"):
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

    if action in ("reject", "incomplete") and not body.reason:
        raise HTTPException(status_code=400, detail=f"Reason required for action: {action}")

    status_mapping = {
        "accept": TaskStatus.in_progress,
        "reject": TaskStatus.rejected,
        "complete": TaskStatus.completed,
        "incomplete": TaskStatus.incomplete,
    }
    task.status = status_mapping[action]

    await message_service.record_message_action(db, message.id, action, body.reason)

    # 通知任务执行人的上级
    if task.executor_id:
        executor_result = await db.execute(
            select(Employee).where(Employee.id == task.executor_id)
        )
        executor = executor_result.scalar_one_or_none()

        if executor and executor.manager_id:
            await message_service.create_response_message(
                db, task, executor.manager_id, action, executor.name or "未知"
            )

    await db.commit()
    await db.refresh(task)

    return TaskReplyResponse(
        success=True,
        message=f"Task {action}d successfully",
        task=TaskResponse.model_validate(task),
    )
