"""M0-T04 Redis 客户端封装的测试。

覆盖 DoD：
    1. PING 返回 PONG（集成测试，见 TestRedisConnection）
    2. 业务代码请求 DB 1 时抛出明确异常
    3. 连接串从配置读取，不硬编码（静态检查）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import BusinessError
from app.infra import redis as redis_infra


class TestDbIsolation:
    """DB 0 业务 / DB 1 Langfuse，业务代码不得越界。"""

    def test_langfuse_db_rejected(self) -> None:
        with pytest.raises(BusinessError) as exc_info:
            redis_infra.create_client(db=redis_infra.LANGFUSE_DB)

        error = exc_info.value
        assert error.code == 10002
        assert "Langfuse" in error.message
        assert str(redis_infra.LANGFUSE_DB) in error.message

    def test_unauthorized_db_rejected(self) -> None:
        """除 DB 0 外的任意库都应被拒绝，而非只挡 DB 1。"""
        for db in (2, 3, 15):
            with pytest.raises(BusinessError, match="未授权的 Redis 逻辑库"):
                redis_infra.create_client(db=db)

    def test_business_db_allowed(self) -> None:
        client = redis_infra.create_client(db=redis_infra.BUSINESS_DB)
        assert client.connection_pool.connection_kwargs["db"] == 0

    def test_langfuse_db_constant_matches_config(self) -> None:
        from app.core.config import settings

        assert redis_infra.LANGFUSE_DB == settings.redis_db_langfuse == 1
        assert redis_infra.BUSINESS_DB == settings.redis_db_business == 0


class TestClientConstruction:
    def test_connection_params_come_from_settings(self) -> None:
        """连接参数必须读配置，不能写死。"""
        from app.core.config import settings

        client = redis_infra.create_client()
        kwargs = client.connection_pool.connection_kwargs

        assert kwargs["host"] == settings.redis_host
        assert kwargs["port"] == settings.redis_port
        assert kwargs["db"] == settings.redis_db_business
        assert kwargs["socket_connect_timeout"] == settings.redis_connect_timeout
        assert kwargs["socket_timeout"] == settings.redis_socket_timeout

    def test_password_applied_when_configured(self) -> None:
        from app.core.config import settings

        client = redis_infra.create_client()
        kwargs = client.connection_pool.connection_kwargs
        assert kwargs["password"] == (settings.redis_password or None)

    def test_client_is_singleton(self) -> None:
        assert redis_infra.get_client() is redis_infra.get_client()


class TestKeyPrefix:
    def test_make_key_adds_project_prefix(self) -> None:
        key = redis_infra.make_key("quota", "u-123", "2026-11-07")
        assert key.startswith(f"{redis_infra.settings.redis_key_prefix}:")
        assert key.endswith("quota:u-123:2026-11-07")

    def test_make_key_accepts_int(self) -> None:
        assert redis_infra.make_key("seq", 7) == "travel:seq:7"


class TestDegradation:
    """架构 §1.6 决策 3：Redis 不可用时降级读 PG，服务不中断。"""

    async def test_check_redis_returns_false_without_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Broken:
            async def ping(self) -> bool:
                raise ConnectionError("connection refused")

        monkeypatch.setattr(redis_infra, "get_client", lambda: _Broken())
        assert await redis_infra.check_redis() is False

    async def test_is_available_mirrors_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called = {"count": 0}

        async def _check() -> bool:
            called["count"] += 1
            return True

        monkeypatch.setattr(redis_infra, "check_redis", _check)
        assert await redis_infra.is_available() is True
        assert called["count"] == 1

    async def test_execute_raises_unavailable_after_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """连接类错误重试耗尽后抛 RedisUnavailableError，供调用方降级。"""
        from app.core.config import settings

        attempts = {"count": 0}

        async def _always_fail() -> None:
            attempts["count"] += 1
            raise ConnectionError("boom")

        monkeypatch.setattr(settings, "redis_retry_backoff_base", 0.001)
        with pytest.raises(redis_infra.RedisUnavailableError):
            await redis_infra.execute(_always_fail)

        assert attempts["count"] == settings.redis_retry_attempts

    async def test_execute_succeeds_after_transient_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """瞬时失败应被重试覆盖，不影响调用方。"""
        from app.core.config import settings

        monkeypatch.setattr(settings, "redis_retry_backoff_base", 0.001)
        calls = {"count": 0}

        async def _flaky() -> str:
            calls["count"] += 1
            if calls["count"] == 1:
                raise ConnectionError("transient")
            return "PONG"

        assert await redis_infra.execute(_flaky) == "PONG"
        assert calls["count"] == 2

    async def test_redis_error_does_not_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """命令本身的错误重试无意义，应立即失败。"""
        from redis.exceptions import ResponseError

        calls = {"count": 0}

        async def _wrong_type() -> None:
            calls["count"] += 1
            raise ResponseError("WRONGTYPE")

        with pytest.raises(redis_infra.RedisUnavailableError):
            await redis_infra.execute(_wrong_type)

        assert calls["count"] == 1, "业务语义错误不应重试"


class TestNoHardcodedConnectionString:
    def test_no_redis_url_outside_config(self) -> None:
        """DoD 规范检查：连接串只在 config 中出现。"""
        app_dir = Path(__file__).resolve().parents[2] / "app"
        offenders: list[str] = []

        for path in app_dir.rglob("*.py"):
            if path.name == "config.py":
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "redis://" in line and not line.lstrip().startswith("#"):
                    offenders.append(f"{path.relative_to(app_dir)}:{lineno}")

        assert not offenders, f"发现硬编码的连接串: {offenders}"

    def test_result_backend_built_from_settings(self) -> None:
        from app.core.config import settings

        assert settings.celery_result_backend.startswith("redis://")
        assert str(settings.redis_host) in settings.celery_result_backend
        assert settings.celery_result_backend.endswith(f"/{settings.redis_db_business}")
