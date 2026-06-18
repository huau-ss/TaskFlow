"""Celery 定时任务 - 任务通知和升级处理"""

import asyncio
from datetime import datetime, timedelta, UTC

from sqlalchemy import select

from app.agents.escalation import auto_escalate_overdue_tasks, escalate_task_to_top
from app.config import settings
from app.database import async_session_maker
from app.models import Task, TaskStatus
from app.services.message import create_reminder_message


def run_async(coro):
    """在同步环境中运行异步函数"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _check_deadline_reminders():
    """检查即将到期的任务并发送提醒"""
    async with async_session_maker() as db:
        # 找出 deadline 在未来 N 小时内的未完成任务
        reminder_hours = getattr(settings, 'reminder_before_hours', 24)
        threshold = datetime.now(UTC) + timedelta(hours=reminder_hours)

        query = (
            select(Task)
            .where(Task.deadline.isnot(None))
            .where(Task.deadline <= threshold)
            .where(Task.status.in_([TaskStatus.pending, TaskStatus.accepted, TaskStatus.in_progress]))
        )

        result = await db.execute(query)
        tasks = list(result.scalars().all())

        sent_count = 0
        for task in tasks:
            if task.executor_id:
                try:
                    await create_reminder_message(
                        db=db,
                        task=task,
                        employee_id=task.executor_id,
                        reminder_type="deadline_soon",
                    )
                    sent_count += 1
                except Exception:
                    continue

        await db.commit()
        return sent_count


async def _check_overdue_tasks():
    """检查已逾期的任务并更新状态"""
    async with async_session_maker() as db:
        now = datetime.now(UTC)

        # 找出已过期的未完成任务
        query = (
            select(Task)
            .where(Task.deadline.isnot(None))
            .where(Task.deadline < now)
            .where(Task.status.in_([TaskStatus.pending, TaskStatus.accepted, TaskStatus.in_progress]))
        )

        result = await db.execute(query)
        tasks = list(result.scalars().all())

        updated_count = 0
        for task in tasks:
            if task.status != TaskStatus.overdue:
                task.status = TaskStatus.overdue
                updated_count += 1

                # 发送逾期提醒
                if task.executor_id:
                    try:
                        await create_reminder_message(
                            db=db,
                            task=task,
                            employee_id=task.executor_id,
                            reminder_type="overdue",
                        )
                    except Exception:
                        continue

        await db.commit()
        return updated_count


async def _escalate_long_overdue_tasks():
    """升级长期逾期的任务"""
    async with async_session_maker() as db:
        escalated = await auto_escalate_overdue_tasks(db, overdue_days=3)
        return escalated


# ==================== Celery Tasks ====================

def check_deadline_reminders():
    """Celery 任务：检查即将到期的任务"""
    return run_async(_check_deadline_reminders())


def check_overdue_tasks():
    """Celery 任务：检查已逾期的任务"""
    return run_async(_check_overdue_tasks())


def escalate_long_overdue_tasks():
    """Celery 任务：升级长期逾期的任务"""
    return run_async(_escalate_long_overdue_tasks())


# ==================== 手动触发函数（供 API 调用）====================

def trigger_reminder_check():
    """手动触发提醒检查"""
    return run_async(_check_deadline_reminders())


def trigger_overdue_check():
    """手动触发逾期检查"""
    return run_async(_check_overdue_tasks())


def trigger_escalation_check():
    """手动触发升级检查"""
    return run_async(_escalate_long_overdue_tasks())
