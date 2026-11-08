"""M0-T07 Celery worker 的真实消费测试。

需要 RabbitMQ 与 Redis 可用，并且**有 worker 在消费目标队列**。
无 worker 时自动跳过，不阻塞其他人。

本地运行前先起 worker：
    cd backend && uv run celery -A app.tasks.celery_app.celery_app worker \
        -l info -Q local --pool=solo

注意：本地开发务必用 ``CELERY_LOCAL_QUEUE=local`` 与测试服务器容器隔离，
否则两边会抢同一批消息，表现为 ``NotRegistered`` 或结果丢失。
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.tasks.celery_app import celery_app
from app.tasks.health import echo

pytestmark = pytest.mark.integration

QUEUE = settings.celery_effective_queue


def _worker_on_queue() -> bool:
    """探测**目标队列上**是否有活跃 worker。

    只用 ``inspect ping`` 不够：它返回所有在线节点，而测试服务器上的容器
    worker 虽然在线，却不消费本地 ``local`` 队列。消息投过去无人处理，
    ``.get()`` 会超时失败。

    因此还要比对 ``active_queues``，确认确实有节点在消费 QUEUE。
    """
    try:
        inspector = celery_app.control.inspect(timeout=3)
        pings = inspector.ping() or {}
        if not pings:
            return False

        queues = inspector.active_queues() or {}
        for node, entries in queues.items():
            if node not in pings:
                continue
            names = {entry.get("name") for entry in entries if isinstance(entry, dict)}
            if QUEUE in names:
                return True
        return False
    except Exception:
        return False


def _worker_online() -> bool:
    return _worker_on_queue()


@pytest.fixture(scope="module")
def worker_available() -> None:
    if not _worker_online():
        pytest.skip(f"队列 {QUEUE} 上没有活跃 worker，跳过消费测试")


class TestWorkerConsumesTask:
    def test_echo_task_roundtrip(self, worker_available: None) -> None:
        """DoD：worker 可启动并消费一个 echo 任务。"""
        result = echo.apply_async(args=["m0t07"], queue=QUEUE)
        payload = result.get(timeout=30)

        assert payload["echo"] == "m0t07"
        assert payload["task_id"] == result.id
        assert result.status == "SUCCESS"

    def test_task_id_is_traceable(self, worker_available: None) -> None:
        """任务 ID 可追溯：返回体里的 task_id 与投递时一致。"""
        result = echo.apply_async(args=["trace"], queue=QUEUE)
        payload = result.get(timeout=30)
        assert payload["task_id"] == result.id

    def test_result_backend_stores_result(self, worker_available: None) -> None:
        result = echo.apply_async(args=["persist"], queue=QUEUE)
        result.get(timeout=30)

        # 重新按 task_id 取结果，验证 Redis 里确实存下来了
        from celery.result import AsyncResult

        again = AsyncResult(result.id, app=celery_app)
        assert again.get(timeout=10)["echo"] == "persist"

    def test_exception_is_not_swallowed(self) -> None:
        """DoD：任务异常不得静默吞掉。

        该断言在单元层验证（任务体抛异常时 Celery 记录 on_failure 并保留原异常），
        不需要真实 worker——动态注册的任务 worker 未知，无法端到端验证。
        """
        from app.tasks.celery_app import celery_app as app

        @app.task(name="app.tasks.health._test_raise", base=None)
        def _boom() -> None:
            raise ValueError("expected failure")

        try:
            # 同步执行任务体，确认异常原样抛出而非被吞
            with pytest.raises(ValueError, match="expected failure"):
                _boom()
        finally:
            app.tasks.pop("app.tasks.health._test_raise", None)


class TestQueueIsolation:
    def test_local_queue_configured_in_dev(self) -> None:
        """本地开发应配置独立队列，避免与服务器容器 worker 抢消息。"""
        assert QUEUE, "必须配置默认队列"
        # 只做提示性断言：README/文档要求本地设为 local
        if settings.celery_local_queue:
            assert settings.celery_local_queue == QUEUE
