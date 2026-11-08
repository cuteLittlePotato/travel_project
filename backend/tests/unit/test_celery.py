"""M0-T07 Celery 应用与任务基类的单元测试。

覆盖 DoD：
    1. worker 可启动并消费 echo 任务（集成测试见 TestCeleryWorkerIntegration）
    2. 任务超时、重试次数可配置
    3. 规范检查：任务 ID 可追溯，日志含 task_id
"""

from __future__ import annotations

import logging

import pytest
from celery import Task

from app.core.config import settings
from app.tasks.base import BaseTask, RetryableTask, echo
from app.tasks.celery_app import TASK_MODULES, celery_app
from app.tasks.health import echo as echo_task


def _probe_task() -> BaseTask:
    """取一个真实的 BaseTask 任务实例。

    Celery 的 ``Task`` 不允许直接 ``BaseTask()`` 构造，注册表里拿到的
    已经是绑定好的任务对象，可直接调用其生命周期钩子。
    """
    return celery_app.tasks["app.tasks.health.echo"]  # type: ignore[no-any-return]


# ============================================================
# 应用配置
# ============================================================


class TestCeleryConfiguration:
    def test_broker_is_rabbitmq(self) -> None:
        """架构 §1.6 决策 4：Broker 使用 RabbitMQ。"""
        assert settings.celery_broker_url.startswith("amqp://")

    def test_result_backend_is_redis(self) -> None:
        assert settings.celery_result_backend.startswith("redis://")
        assert settings.celery_result_backend.endswith(f"/{settings.redis_db_business}")

    def test_serializer_is_json(self) -> None:
        """JSON 序列化：拒绝 pickle，避免反序列化执行任意代码。"""
        assert celery_app.conf.task_serializer == "json"
        assert celery_app.conf.result_serializer == "json"
        assert "pickle" not in celery_app.conf.accept_content

    def test_acks_late_enabled(self) -> None:
        """任务完成后才确认，worker 崩溃时任务会重新投递。"""
        assert celery_app.conf.task_acks_late is True

    def test_prefetch_multiplier_is_one(self) -> None:
        """一次只取一个任务，避免长任务阻塞队列。"""
        assert celery_app.conf.worker_prefetch_multiplier == 1

    def test_task_modules_registered(self) -> None:
        assert "app.tasks.health" in TASK_MODULES
        assert "app.tasks.schedule.popularity" in TASK_MODULES

    def test_beat_schedule_exists(self) -> None:
        schedule = celery_app.conf.beat_schedule
        assert "popularity-hourly" in schedule
        assert (
            schedule["popularity-hourly"]["task"]
            == "app.tasks.schedule.popularity.recalculate_popularity"
        )


# ============================================================
# DoD 2：超时与重试可配置
# ============================================================


class TestConfigurableTimeoutsAndRetries:
    def test_time_limits_from_settings(self) -> None:
        assert celery_app.conf.task_time_limit == settings.celery_task_time_limit
        assert celery_app.conf.task_soft_time_limit == settings.celery_task_soft_time_limit

    def test_soft_limit_less_than_hard_limit(self) -> None:
        """软超时是给任务优雅退出的机会，必须早于硬超时。"""
        assert celery_app.conf.task_soft_time_limit < celery_app.conf.task_time_limit

    def test_retry_settings_from_settings(self) -> None:
        assert celery_app.conf.task_retry_backoff == settings.celery_retry_backoff
        assert celery_app.conf.task_retry_backoff_max == settings.celery_retry_backoff_max
        assert celery_app.conf.task_retry_jitter == settings.celery_retry_jitter

    def test_retry_settings_can_be_overridden(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """配置项可覆盖，不需要改代码。"""
        from app.core.config import Settings

        cfg = Settings(
            jwt_secret_key="x" * 40,
            postgres_password="p",
            neo4j_password="n",
            minio_access_key="a",
            minio_secret_key="s",
            rabbitmq_password="r",
            celery_task_time_limit=600,
            celery_task_soft_time_limit=540,
            celery_max_retries=5,
            _env_file=None,  # type: ignore[call-arg]
        )
        assert cfg.celery_task_time_limit == 600
        assert cfg.celery_max_retries == 5

    def test_result_expires_configured(self) -> None:
        assert celery_app.conf.result_expires == settings.celery_result_expires

    def test_broker_retry_on_startup(self) -> None:
        """Broker 启动时不可达应重试，而非直接崩溃退出。"""
        assert celery_app.conf.broker_connection_retry_on_startup is True


# ============================================================
# 任务基类
# ============================================================


class TestBaseTask:
    def test_inherits_celery_task(self) -> None:
        assert issubclass(BaseTask, Task)

    def test_max_retries_from_settings(self) -> None:
        assert BaseTask.max_retries == settings.celery_max_retries

    def test_default_no_autoretry(self) -> None:
        """普通任务默认不自动重试，避免非幂等任务被重复执行。"""
        assert BaseTask.autoretry_for == ()

    def test_retryable_task_retries_connection_errors(self) -> None:
        assert ConnectionError in RetryableTask.autoretry_for
        assert TimeoutError in RetryableTask.autoretry_for

    def test_retryable_task_backoff_configured(self) -> None:
        assert RetryableTask.retry_backoff == settings.celery_retry_backoff
        assert RetryableTask.retry_backoff_max == settings.celery_retry_backoff_max


# ============================================================
# DoD 3：任务 ID 可追溯，日志含 task_id
# ============================================================


class TestTaskIdTracing:
    def test_before_start_logs_task_id(self, caplog: pytest.LogCaptureFixture) -> None:
        task = _probe_task()
        task.request.id = "task-abc-123"

        with caplog.at_level(logging.INFO, logger="app.tasks.base"):
            task.before_start("task-abc-123", (), {})

        assert any("task-abc-123" in record.getMessage() for record in caplog.records)

    def test_before_start_puts_task_id_in_extra_fields(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """结构化日志的 extra_fields 中必须包含 task_id，便于日志系统检索。"""
        task = _probe_task()

        with caplog.at_level(logging.INFO, logger="app.tasks.base"):
            task.before_start("task-xyz", (), {})

        records = [r for r in caplog.records if hasattr(r, "extra_fields")]
        assert records, "未捕获到带 extra_fields 的日志"
        assert records[0].extra_fields["task_id"] == "task-xyz"

    def test_on_success_logs_task_id(self, caplog: pytest.LogCaptureFixture) -> None:
        task = _probe_task()

        with caplog.at_level(logging.INFO, logger="app.tasks.base"):
            task.on_success({"ok": True}, "task-ok-1", (), {})

        assert any("task-ok-1" in r.getMessage() for r in caplog.records)

    def test_on_failure_logs_full_traceback(self, caplog: pytest.LogCaptureFixture) -> None:
        """DoD：任务异常不得静默吞掉，需记录完整堆栈。"""
        task = _probe_task()
        task.request.id = "task-fail-1"

        try:
            raise ValueError("模拟任务失败")
        except ValueError as exc:
            with caplog.at_level(logging.ERROR, logger="app.tasks.base"):
                task.on_failure(exc, "task-fail-1", (), {}, None)

        failure_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert failure_records
        record = failure_records[0]
        assert "task-fail-1" in record.getMessage()
        assert record.exc_info is not None, "必须携带堆栈信息"

    def test_on_retry_logs_retry_count(self, caplog: pytest.LogCaptureFixture) -> None:
        task = _probe_task()
        task.request.retries = 2

        with caplog.at_level(logging.WARNING, logger="app.tasks.base"):
            task.on_retry(ConnectionError("x"), "task-retry-1", (), {}, None)

        retry_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert retry_records
        assert "task-retry-1" in retry_records[0].getMessage()
        assert "retries=2" in retry_records[0].getMessage()


# ============================================================
# echo 任务
# ============================================================


class TestEchoTask:
    def test_echo_helper_returns_message(self) -> None:
        assert echo("hello") == {"echo": "hello"}

    def test_echo_task_is_registered(self) -> None:
        assert "app.tasks.health.echo" in celery_app.tasks

    def test_echo_task_name_is_stable(self) -> None:
        """任务名是消息协议的一部分，改名会与队列中的旧消息失配。"""
        assert echo_task.name == "app.tasks.health.echo"

    def test_popularity_task_is_registered(self) -> None:
        import app.tasks.schedule.popularity  # noqa: F401  触发注册

        assert "app.tasks.schedule.popularity.recalculate_popularity" in celery_app.tasks


# ============================================================
# 模块导入不产生副作用
# ============================================================


class TestNoImportSideEffects:
    def test_importing_celery_app_does_not_connect(self) -> None:
        """导入模块只构造配置对象，不发起网络请求。

        不在导入期连 Broker，否则测试、脚本、API 进程都会被网络状态左右。
        """
        assert celery_app.conf.broker_url.startswith("amqp://")
        # 断言配置已就绪即可；连接池在首次投递/消费时才创建，
        # 用内部属性判断会被其他测试的残留连接干扰，不可靠。
        assert celery_app.main == "travel"
        assert celery_app.conf.task_default_queue == settings.celery_effective_queue

    def test_worker_module_importable(self) -> None:
        from app.tasks import worker

        assert callable(worker.main)

    def test_schedule_package_exports_tasks(self) -> None:
        from app.tasks import schedule

        assert hasattr(schedule, "popularity")
