"""任务基类：统一日志、重试策略与错误上报。

约束（M0-T07 边界与异常）：
    - 任务异常**不得静默吞掉**：记录完整堆栈后重新抛出，由 Celery 的重试策略接管
    - 每条日志含 ``task_id``，便于按任务串联排查
    - Result Backend 不可用不应阻塞任务执行（Celery 默认行为，此处不额外干预）

用法：
    @celery_app.task(base=BaseTask, bind=True, name="app.tasks.xxx.do_something")
    def do_something(self, arg: str) -> dict:
        ...
"""

from __future__ import annotations

import logging
from typing import Any

from celery import Task

from app.core.config import settings

logger = logging.getLogger(__name__)


class BaseTask(Task):
    """所有业务任务的基类。

    子类可通过类属性覆盖重试行为：
        autoretry_for      需要自动重试的异常类型
        max_retries        最大重试次数（默认取配置）
        retry_backoff      指数退避（默认取配置）
    """

    #: 默认不自动重试；子类按需指定 ``(ConnectionError, TimeoutError)`` 等
    autoretry_for: tuple[type[Exception], ...] = ()
    max_retries: int = settings.celery_max_retries
    acks_late: bool = True
    #: 任务失败后是否记录到结果后端，便于事后排查
    store_errors_even_if_ignored: bool = True

    # ---------------- 生命周期钩子 ----------------

    def before_start(
        self, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None:
        """任务开始执行。日志带 task_id 与任务名，便于串联。"""
        logger.info(
            "任务开始 task=%s task_id=%s retries=%s",
            self.name,
            task_id,
            self.request.retries,
            extra={"extra_fields": {"task_id": task_id, "task_name": self.name}},
        )

    def on_success(
        self, retval: Any, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None:
        logger.info(
            "任务成功 task=%s task_id=%s",
            self.name,
            task_id,
            extra={"extra_fields": {"task_id": task_id, "task_name": self.name}},
        )

    def on_retry(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: object,
    ) -> None:
        logger.warning(
            "任务重试 task=%s task_id=%s retries=%s error=%s",
            self.name,
            task_id,
            self.request.retries,
            exc,
            extra={"extra_fields": {"task_id": task_id, "task_name": self.name}},
        )

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: object,
    ) -> None:
        """任务最终失败。

        用 ``logger.exception`` 记录完整堆栈；异常本身由 Celery 继续向上传播，
        不会因为这里的日志处理而被吞掉。
        """
        logger.exception(
            "任务失败 task=%s task_id=%s retries=%s args=%s kwargs=%s",
            self.name,
            task_id,
            self.request.retries,
            args,
            kwargs,
            extra={"extra_fields": {"task_id": task_id, "task_name": self.name}},
        )


class RetryableTask(BaseTask):
    """可重试任务的基类。

    适用于调用外部服务的任务（LLM、地图 API、对象存储等）：
    连接类错误自动指数退避重试，其余异常直接失败。
    """

    autoretry_for = (ConnectionError, TimeoutError, OSError)
    retry_backoff = settings.celery_retry_backoff
    retry_backoff_max = settings.celery_retry_backoff_max
    retry_jitter = settings.celery_retry_jitter


def echo(message: str = "ping") -> dict[str, str]:
    """连通性验证用的最小任务体。

    不依赖 Broker，可在单测中直接调用验证任务逻辑。
    """
    return {"echo": message}
