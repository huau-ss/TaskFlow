"""任务升级 Agent - 处理任务升级流程"""

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Employee, Task, TaskStatus
from app.services.message import create_escalation_message

if TYPE_CHECKING:
    from app.routers.tasks import TaskReplyRequest


async def process_incomplete_task(
    db: AsyncSession,
    task: Task,
    reason: str,
) -> bool:
    """处理任务未完成情况，触发升级流程

    当员工标记任务为"未完成"时：
    1. 获取执行人的上级领导
    2. 创建升级消息通知领导
    3. 更新任务状态为 escalated

    Returns:
        是否成功处理升级
    """
    if not task.executor_id:
        return False

    try:
        # 获取执行人信息
        emp_result = await db.execute(select(Employee).where(Employee.id == task.executor_id))
        executor = emp_result.scalar_one_or_none()

        if not executor:
            return False

        # 获取上级领导
        if not executor.manager_id:
            # 没有上级，跳过升级
            return False

        manager_result = await db.execute(select(Employee).where(Employee.id == executor.manager_id))
        manager = manager_result.scalar_one_or_none()

        if not manager:
            return False

        # 创建升级消息
        await create_escalation_message(
            db=db,
            task=task,
            manager_id=manager.id,
            executor_name=executor.name or "未知",
            reason=reason,
        )

        # 更新任务状态
        task.status = TaskStatus.escalated

        await db.commit()
        return True

    except Exception:
        await db.rollback()
        return False


async def get_escalation_chain(
    db: AsyncSession,
    employee_id: int,
) -> list[Employee]:
    """获取员工的升级链（直属领导 -> 领导的领导 -> ...）

    用于确定任务升级的路径

    Returns:
        升级链上的所有上级领导列表（不包括员工本人）
    """
    chain = []
    current_id = employee_id

    # 最多向上追溯 5 层
    for _ in range(5):
        emp_result = await db.execute(select(Employee).where(Employee.id == current_id))
        employee = emp_result.scalar_one_or_none()

        if not employee or not employee.manager_id:
            break

        manager_result = await db.execute(select(Employee).where(Employee.id == employee.manager_id))
        manager = manager_result.scalar_one_or_none()

        if manager:
            chain.append(manager)
            current_id = manager.id
        else:
            break

    return chain


async def escalate_task_to_top(
    db: AsyncSession,
    task: Task,
    reason: str,
    exclude_employee_id: int | None = None,
) -> int:
    """将任务升级到最高领导

    当员工无法完成任务时，将任务升级到最高领导

    Args:
        db: 数据库会话
        task: 任务对象
        reason: 升级原因
        exclude_employee_id: 要排除的员工ID（通常是当前执行人）

    Returns:
        发送的升级消息数量
    """
    if not task.executor_id or task.executor_id == exclude_employee_id:
        return 0

    message_count = 0

    # 获取升级链
    escalation_chain = await get_escalation_chain(db, task.executor_id)

    # 获取执行人名称
    emp_result = await db.execute(select(Employee).where(Employee.id == task.executor_id))
    executor = emp_result.scalar_one_or_none()
    executor_name = executor.name if executor else "未知"

    # 向链上的每个上级发送升级消息（通常只发给第一个上级）
    for manager in escalation_chain[:1]:  # 只发给直属领导
        try:
            await create_escalation_message(
                db=db,
                task=task,
                manager_id=manager.id,
                executor_name=executor_name,
                reason=reason,
            )
            message_count += 1
        except Exception:
            continue

    if message_count > 0:
        task.status = TaskStatus.escalated
        await db.commit()

    return message_count


async def auto_escalate_overdue_tasks(
    db: AsyncSession,
    overdue_days: int = 3,
) -> int:
    """自动升级长期逾期的任务

    定时任务调用：将超过 N 天仍未完成的任务升级

    Args:
        db: 数据库会话
        overdue_days: 逾期天数阈值

    Returns:
        升级的任务数量
    """
    from datetime import datetime, timedelta, UTC

    # 找出逾期超过指定天数的任务
    threshold = datetime.now(UTC) - timedelta(days=overdue_days)

    query = (
        select(Task)
        .where(Task.status == TaskStatus.overdue)
        .where(Task.deadline < threshold)
    )

    result = await db.execute(query)
    overdue_tasks = list(result.scalars().all())

    escalated_count = 0
    for task in overdue_tasks:
        if await escalate_task_to_top(db, task, f"任务已逾期超过 {overdue_days} 天"):
            escalated_count += 1

    return escalated_count
