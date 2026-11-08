"""全局前置基础设施的单元测试（M0-T01 ~ M0-T12）。"""

from __future__ import annotations

import itertools
import time
import uuid

import pytest

from app.core.exceptions import BusinessError, ErrorCode
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.infra import redis as redis_infra
from app.schemas.pagination import PageQuery, build_page
from app.utils.ids import uuid7
from app.utils.query import parse_sort_order

REQUIRED_SETTINGS = {
    "jwt_secret_key": "x" * 40,
    "postgres_password": "p",
    "neo4j_password": "n",
    "minio_access_key": "a",
    "minio_secret_key": "s",
    "rabbitmq_password": "r",
}


def make_settings(**overrides: object):
    """构造不读 .env 的 Settings，避免测试受开发者本地配置影响。"""
    from app.core.config import Settings

    values = {**REQUIRED_SETTINGS, **overrides, "_env_file": None}
    return Settings(**values)  # type: ignore[call-arg]


class TestConfig:
    def test_missing_required_setting_fails_loudly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """缺失必填配置时启动失败，并指出字段名。"""
        from pydantic import ValidationError

        from app.core.config import Settings

        for key in ("JWT_SECRET_KEY", "POSTGRES_PASSWORD"):
            monkeypatch.delenv(key, raising=False)

        # 缺两处必填项：只传其余四项，应因缺失而报错并点名
        partial = {
            k: v for k, v in REQUIRED_SETTINGS.items() if k != "postgres_password"
        }
        with pytest.raises(ValidationError) as exc_info:
            Settings(**partial, _env_file=None)  # type: ignore[call-arg]
        assert "postgres_password" in str(exc_info.value).lower()

    def test_placeholder_external_services_default_to_disabled(self) -> None:
        """地图/短信/邮件为占位，默认关闭且地址为空，避免误调真实服务。"""
        cfg = make_settings()
        assert cfg.map_enabled is False
        assert cfg.sms_enabled is False
        assert cfg.email_enabled is False
        assert cfg.map_base_url == ""
        assert cfg.sms_base_url == ""

    def test_api_prefix_default_matches_api_spec(self) -> None:
        """API §1.1：C 端前缀为 /api/v1。"""
        assert make_settings().api_prefix == "/api/v1"


class TestRouteMounting:
    """路由前缀必须来自配置，不得在路由层硬编码，也不得重复拼接。"""

    def test_health_is_mounted_under_api_without_version(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.api.v1 import health as health_module

        async def _up() -> bool:
            return True

        async def _external_up() -> dict[str, bool]:
            return {"milvus": True, "neo4j": True, "elasticsearch": True, "minio": True}

        # 单元测试不打真实网络，用替身返回「全部健康」
        monkeypatch.setattr(health_module, "check_database", _up)
        monkeypatch.setattr(health_module, "check_redis", _up)
        monkeypatch.setattr(health_module, "check_all", _external_up)

        assert client.get("/api/health").status_code == 200
        ready = client.get("/api/health/ready")
        assert ready.status_code == 200
        assert ready.json()["data"]["status"] == "ready"
        assert "postgres" in ready.json()["data"]["dependencies"]

    def test_no_prefix_duplication(self, client) -> None:
        """main.py 与 api_router 都加前缀会拼成 /api/api/v1，必须避免。"""
        assert client.get("/api/api/health").status_code == 404
        assert client.get("/api/v1/v1/health").status_code == 404

    def test_b_end_prefix_is_admin_suffixed(self) -> None:
        """API §1.1：B 端前缀为 C 端前缀 + /admin。"""
        from app.core.config import settings

        assert settings.api_prefix == "/api/v1"
        assert f"{settings.api_prefix}/admin" == "/api/v1/admin"


class TestSecurity:
    def test_password_hash_roundtrip(self) -> None:
        hashed = hash_password("Passw0rd!")
        assert hashed != "Passw0rd!"
        assert verify_password("Passw0rd!", hashed)
        assert not verify_password("wrong", hashed)

    def test_access_token_roundtrip(self) -> None:
        uid = uuid7()
        token = create_access_token(str(uid), "user", 3)
        payload = decode_token(token, expected_type="access")
        assert payload.subject_id == uid
        assert payload.user_type == "user"
        assert payload.token_version == 3
        assert payload.token_type == "access"

    def test_token_type_mismatch_rejected(self) -> None:
        token = create_refresh_token(str(uuid7()), "user", 0)
        with pytest.raises(BusinessError) as exc_info:
            decode_token(token, expected_type="access")
        assert exc_info.value.code == ErrorCode.UNAUTHORIZED

    def test_alg_none_rejected(self) -> None:
        """算法混淆攻击：alg=none 的 Token 必须被拒绝。"""
        import jwt

        forged = jwt.encode(
            {"sub": str(uuid7()), "user_type": "user", "token_version": 0, "token_type": "access"},
            key="",
            algorithm="none",
        )
        with pytest.raises(BusinessError) as exc_info:
            decode_token(forged, expected_type="access")
        assert exc_info.value.code == ErrorCode.UNAUTHORIZED

    def test_tampered_token_rejected(self) -> None:
        token = create_access_token(str(uuid7()), "user", 0)
        with pytest.raises(BusinessError):
            decode_token(token[:-2] + "xx", expected_type="access")


class TestPagination:
    def test_page_offset(self) -> None:
        assert PageQuery(page=1, page_size=20).offset == 0
        assert PageQuery(page=3, page_size=20).offset == 40

    def test_page_size_over_limit_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PageQuery(page_size=101)

    def test_page_zero_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PageQuery(page=0)

    def test_build_page_structure(self) -> None:
        data = build_page(items=[], total=0, page=1, page_size=20)
        assert set(data) == {"items", "total", "page", "page_size", "total_pages"}
        assert data["total_pages"] == 0

    def test_total_pages_rounding(self) -> None:
        assert build_page(items=[1], total=41, page=1, page_size=20)["total_pages"] == 3


class TestQueryGuard:
    def test_invalid_sort_order_rejected(self) -> None:
        with pytest.raises(BusinessError) as exc_info:
            parse_sort_order("drop table")
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED

    def test_sort_order_defaults_to_desc(self) -> None:
        assert parse_sort_order(None) == "desc"
        assert parse_sort_order("ASC") == "asc"


class TestUUIDv7:
    def test_version_and_variant_bits(self) -> None:
        value = uuid7()
        assert value.version == 7
        # RFC 9562：变体位必须为 0b10
        assert value.variant == uuid.RFC_4122

    def test_monotonic_within_same_millisecond(self) -> None:
        """同一毫秒内连续生成也必须严格递增（RFC 9562 §6.2 Method 1）。"""
        batch = [uuid7() for _ in range(1000)]
        assert all(later.int > earlier.int for earlier, later in itertools.pairwise(batch))

    def test_embedded_timestamp_is_current(self) -> None:
        before = int(time.time() * 1000)
        embedded = uuid7().int >> 80
        after = int(time.time() * 1000)
        # 计数器溢出时可能借用下一毫秒，允许 2ms 容差
        assert before - 2 <= embedded <= after + 2


class TestRedisGuard:
    def test_business_code_cannot_touch_langfuse_db(self) -> None:
        with pytest.raises(BusinessError) as exc_info:
            redis_infra.create_client(db=redis_infra.LANGFUSE_DB)
        assert exc_info.value.code == ErrorCode.INTERNAL_ERROR


class TestHealthEndpoint:
    def test_liveness(self, client) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"code": 0, "message": "ok", "data": {"status": "ok"}}

    def test_readiness_degrades_instead_of_crashing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """依赖不可达时必须返回 degraded，而不是抛异常。

        健康检查的价值恰在于故障时仍能给出诊断信息；探针崩溃会掩盖真实原因。
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api.v1 import health as health_module

        async def _down() -> bool:
            raise ConnectionError("service unreachable")

        monkeypatch.setattr(health_module, "check_database", _down)
        monkeypatch.setattr(health_module, "check_redis", _down)

        async def _external_down() -> dict[str, bool]:
            raise ConnectionError("external unreachable")

        monkeypatch.setattr(health_module, "check_all", _external_down)

        probe = FastAPI()
        probe.include_router(health_module.router, prefix="/api")

        response = TestClient(probe, raise_server_exceptions=False).get("/api/health/ready")
        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["status"] == "degraded"
        assert payload["dependencies"]["postgres"] is False
        assert payload["dependencies"]["redis"] is False

    def test_unknown_route_uses_unified_error_shape(self, client) -> None:
        response = client.get("/api/v1/not-exists")
        assert response.status_code == 404
        body = response.json()
        assert body["code"] == ErrorCode.ROUTE_NOT_FOUND
        assert "data" in body

    def test_unhandled_exception_does_not_leak_traceback(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.core.error_handlers import register_exception_handlers

        probe = FastAPI()
        register_exception_handlers(probe)

        @probe.get("/boom")
        async def boom() -> None:
            raise RuntimeError("internal secret detail")

        response = TestClient(probe, raise_server_exceptions=False).get("/boom")
        assert response.status_code == 500
        body = response.text
        assert "Traceback" not in body
        assert "internal secret detail" not in body
        assert response.json()["code"] == ErrorCode.INTERNAL_ERROR
