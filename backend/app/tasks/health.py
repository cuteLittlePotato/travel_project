"""Celery 连通性验证任务。

用途：验证 worker 正常运行、Broker 与 Result Backend 可用。
M0-T07 的 DoD 要求「worker 可启动并消费一个 echo 任务」，用本模块验证。

生产环境可用于部署后的冒烟检查：
    celery -A app.tasks.celery_app.celery_app call app.tasks.health.echo --args='["hello"]'
"""

from __future__ import annotations

import logging

from app.tasks.base import BaseTask
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(base=BaseTask, bind=True, name="app.tasks.health.echo")
def echo(self, message: str = "ping") -> dict[str, str]:
    """原样回显消息，用于验证任务链路。"""
    logger.info("echo 任务执行 task_id=%s message=%s", self.request.id, message)
    return {"echo": message, "task_id": str(self.request.id)}
