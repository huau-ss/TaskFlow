from celery import Celery

from app.config import settings

celery_app = Celery("taskflow", broker=settings.redis_url, backend=settings.redis_url)
    celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    imports=[
        "app.tasks.asr",
        "app.tasks.notifications",
        "app.tasks.relation_analysis",
    ],
    beat_schedule={
        "check-deadline-reminders": {
            "task": "app.tasks.notifications.check_deadline_reminders",
            "schedule": 3600.0,  # 每小时检查一次
        },
        "check-overdue-tasks": {
            "task": "app.tasks.notifications.check_overdue_tasks",
            "schedule": 7200.0,  # 每2小时检查一次
        },
        "escalate-old-tasks": {
            "task": "app.tasks.notifications.escalate_long_overdue_tasks",
            "schedule": 14400.0,  # 每4小时升级一次长期逾期任务
        },
        "global-relation-analysis": {
            "task": "app.tasks.relation_analysis.run_global_relation_analysis",
            "schedule": 259200.0,  # 每3天（72小时）
        },
    },
)
