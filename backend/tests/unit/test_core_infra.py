"""全局前置基础设施的单元测试（M0-T01 ~ M0-T12）。"""

from __future__ import annotations

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


class TestConfig:
    def test_missing_required_setting_fails_loudly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """缺失必填配置时启动失败，并指出字段名。"""
        from app.core.config import Settings

        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        with pytest.raises(Exception) as exc_info:
            Settings(_env_file=None)  # type: ignore[call-arg]
        message = str(exc_info.value)
        assert "jwt_secret_key" in message.lower() or "postgres_password" in message.lower()


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
        assert payload["sub"] == str(uid)
        assert payload["user_type"] == "user"
        assert payload["token_version"] == 3

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
    def test_version_and_ordering(self) -> None:
        first = uuid7()
        second = uuid7()
        assert first.version == 7
        # 时间有序：后生成的 UUID 字典序更大
        assert second.int > first.int


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

    def test_unknown_route_uses_unified_error_shape(self, client) -> None:
        response = client.get("/api/v1/not-exists")
        assert response.status_code == 404
        body = response.json()
        assert body["code"] == ErrorCode.NOT_FOUND
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
