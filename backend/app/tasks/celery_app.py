"""Celery 应用（RabbitMQ Broker + Redis Result Backend）。"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "travel",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        # 任务模块按需在此登记，保证 worker 启动时能发现
        "app.tasks.schedule.popularity",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=settings.celery_task_time_limit,
    task_soft_time_limit=settings.celery_task_soft_time_limit,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    "popularity-hourly": {
        "task": "app.tasks.schedule.popularity.recalculate_popularity",
        # 每小时第 5 分钟执行，避开整点高峰
        "schedule": crontab(minute=5),
    },
}
