"""任务基类：统一日志与错误处理。"""

from __future__ import annotations

import logging

from celery import Task

logger = logging.getLogger(__name__)


class BaseTask(Task):
    """所有业务任务的基类。

    约束：任务异常不得静默吞掉，需记录完整堆栈后重新抛出，
    由 Celery 的重试策略接管。
    """

    autoretry_for: tuple[type[Exception], ...] = ()
    max_retries = 3
    acks_late = True

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: object,
    ) -> None:
        logger.exception(
            "任务失败 task=%s task_id=%s args=%s kwargs=%s",
            self.name,
            task_id,
            args,
            kwargs,
        )
