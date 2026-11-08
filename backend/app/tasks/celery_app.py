"""Celery 应用（RabbitMQ Broker + Redis Result Backend）。

架构 §1.6 决策 4：异步任务使用 Celery + RabbitMQ + Redis。

关键配置说明：
    - ``task_acks_late=True``：任务执行完才确认，worker 崩溃时任务会被重新投递
    - ``worker_prefetch_multiplier=1``：一次只取一个任务，避免长任务阻塞队列
    - ``task_time_limit`` / ``task_soft_time_limit``：硬/软超时，防止任务卡死
    - ``broker_connection_retry_on_startup``：启动时 Broker 不可达会重试而非直接退出
    - ``result_expires``：结果过期后 Redis 自动清理，避免无限增长

新增任务模块时必须加入 ``include`` 列表，否则 worker 启动时发现不了。
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

#: worker 启动时需扫描的任务模块
TASK_MODULES = [
    "app.tasks.health",
    "app.tasks.schedule.popularity",
]

celery_app = Celery(
    "travel",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=TASK_MODULES,
)

celery_app.conf.update(
    # ---------- 序列化 ----------
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # ---------- 时区 ----------
    timezone="Asia/Shanghai",
    enable_utc=True,
    # ---------- 可靠性与超时 ----------
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=settings.celery_task_time_limit,
    task_soft_time_limit=settings.celery_task_soft_time_limit,
    task_reject_on_worker_lost=True,
    # ---------- 重试 ----------
    task_default_retry_delay=10,
    task_retry_backoff=settings.celery_retry_backoff,
    task_retry_backoff_max=settings.celery_retry_backoff_max,
    task_retry_jitter=settings.celery_retry_jitter,
    # ---------- 结果 ----------
    result_expires=settings.celery_result_expires,
    result_extended=True,  # 结果里带上 args/kwargs/worker，便于排查
    # ---------- Broker 连接 ----------
    broker_connection_retry_on_startup=settings.celery_broker_connection_retry_on_startup,
    broker_connection_max_retries=settings.celery_broker_connection_max_retries,
    broker_transport_options={"max_retries": settings.celery_broker_connection_max_retries},
    # ---------- 默认队列 ----------
    # 本地开发时取 CELERY_LOCAL_QUEUE，避免与服务器容器 worker 抢消息
    task_default_queue=settings.celery_effective_queue,
    # ---------- 其他 ----------
    worker_hijack_root_logger=False,  # 交给 app.core.logging 统一管理
    task_send_sent_event=True,
)


def _register_tasks() -> None:
    """导入任务模块，确保装饰器注册生效。

    ``include`` 只对 worker 启动生效；投递方进程（如 API 进程、脚本）若
    没导入任务模块，``task.delay()`` 会报 ``NotRegistered``。
    在模块导入时统一注册一次，避免调用方遗漏。
    """
    import importlib

    for module in TASK_MODULES:
        importlib.import_module(module)


_register_tasks()


celery_app.conf.beat_schedule = {
    "popularity-hourly": {
        "task": "app.tasks.schedule.popularity.recalculate_popularity",
        # 每小时第 5 分钟执行，避开整点高峰
        "schedule": crontab(minute=5),
        "options": {"queue": settings.celery_effective_queue},
    },
}
