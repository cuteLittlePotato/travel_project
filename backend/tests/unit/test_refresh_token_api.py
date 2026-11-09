"""M01-T08 Token 刷新接口的测试。

覆盖 DoD：
    1. 有效 Refresh Token 返回新双 Token
    2. 旧 Refresh Token 再次使用返回 11010（401）
    3. 账号封禁状态下刷新返回 11002
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import jwt
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.exceptions import ErrorCode
from app.infra import redis as redis_infra
from app.main import create_app
from app.modules.account import service, token_service
from app.modules.account.constants import UserStatus, VerifyScene

pytestmark = pytest.mark.integration


# ============================================================
# 夹具
# ============================================================


class _FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._ttl: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):  # type: ignore[no-untyped-def]
        if nx and key in self._data:
            return None
        self._data[key] = value
        if ex:
            self._ttl[key] = ex
        return True

    async def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            if self._data.pop(k, None) is not None:
                self._ttl.pop(k, None)
                n += 1
        return n

    async def incr(self, key: str) -> int:
        v = int(self._data.get(key, "0")) + 1
        self._data[key] = str(v)
        return v

    async def decr(self, key: str) -> int:
        v = int(self._data.get(key, "0")) - 1
        self._data[key] = str(v)
        return v

    async def expire(self, key: str, seconds: int) -> bool:
        self._ttl[key] = seconds
        return True

    async def ttl(self, key: str) -> int:
        return self._ttl.get(key, -1)


@pytest.fixture
async def db_ready() -> None:
    from app.db.session import SessionLocal, check_database

    try:
        if not await check_database():
            pytest.skip("数据库不可达")
    except Exception:
        pytest.skip("数据库不可达")

    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT to_regclass('public.oauth_binding') IS NOT NULL")
        )
        if not result.scalar_one():
            pytest.skip("表未创建（先执行 alembic upgrade head）")


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    client = _FakeRedis()
    monkeypatch.setattr(redis_infra, "get_client", lambda: client)
    monkeypatch.setattr(service.redis_infra, "get_client", lambda: client)
    monkeypatch.setattr(token_service.redis_infra, "get_client", lambda: client)
    from app.modules.account import verification

    monkeypatch.setattr(verification.redis_infra, "get_client", lambda: client)
    return client


@pytest.fixture
async def client(db_ready: None) -> httpx.AsyncClient:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def account(db_ready: None, fake_redis: _FakeRedis) -> Any:
    """创建测试账号，返回 user_id 与初始双 Token。"""
    from app.db.session import SessionLocal

    phone = f"139{uuid.uuid4().int % 100000000:08d}"
    from app.modules.account import verification

    await fake_redis.set(
        verification._code_key(VerifyScene.REGISTER, phone), "123456", ex=300
    )

    async with SessionLocal() as session:
        result = await service.register(
            session, target=phone, verify_code_str="123456", password="Passw0rd"
        )

    yield {
        "user_id": result.user_id,
        "refresh_token": result.refresh_token,
    }

    async with SessionLocal() as session:
        for table in ("user_setting", "user_profile", "oauth_binding"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE user_id = :uid"), {"uid": result.user_id}
            )
        await session.execute(
            text('DELETE FROM "user" WHERE id = :uid'), {"uid": result.user_id}
        )
        await session.commit()


# ============================================================
# DoD 1：刷新成功
# ============================================================


class TestRefreshSuccess:
    async def test_returns_new_token_pair(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": account["refresh_token"]},
        )

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert set(data) == {"access_token", "refresh_token", "expires_in"}
        assert data["access_token"] != data["refresh_token"]
        assert data["refresh_token"] != account["refresh_token"], "应签发新 Refresh Token"

    async def test_new_access_token_works(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": account["refresh_token"]},
        )
        new_access = response.json()["data"]["access_token"]

        # 用新 Access Token 访问受保护接口
        # （当前无业务接口，只验证 Token 可解码且 subject 正确）
        from app.core.security import decode_token

        payload = decode_token(new_access, expected_type="access")
        assert payload.subject_id == account["user_id"]

    async def test_refresh_via_cookie(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """评审 §Q1：浏览器场景从 httpOnly Cookie 读 Refresh Token。"""
        client.cookies.set(settings.refresh_cookie_name, account["refresh_token"])
        try:
            response = await client.post("/api/v1/auth/refresh", json={})
            assert response.status_code == 200
            assert response.json()["data"]["access_token"]
        finally:
            client.cookies.clear()

    async def test_body_takes_priority_over_cookie(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """请求体优先于 Cookie（非浏览器客户端场景）。"""
        client.cookies.set(settings.refresh_cookie_name, "invalid-cookie-token")
        try:
            response = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": account["refresh_token"]},
            )
            assert response.status_code == 200, "应使用请求体的有效 Token"
        finally:
            client.cookies.clear()


# ============================================================
# DoD 2：轮换机制（旧 Token 失效）
# ============================================================


class TestRotation:
    async def test_old_token_rejected_after_use(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：旧 Refresh Token 再次使用返回 11010（401）。"""
        old_token = account["refresh_token"]

        first = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": old_token}
        )
        assert first.status_code == 200

        # 再用旧 Token
        second = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": old_token}
        )
        assert second.status_code == 401
        assert second.json()["code"] == ErrorCode.REFRESH_TOKEN_REVOKED == 11010

    async def test_new_token_works_after_rotation(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """轮换后的新 Token 应可用。"""
        first = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": account["refresh_token"]}
        )
        new_token = first.json()["data"]["refresh_token"]

        second = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": new_token}
        )
        assert second.status_code == 200

    async def test_jti_is_recorded(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """轮换后旧 jti 应进入黑名单。"""
        old_jti = jwt.decode(
            account["refresh_token"], settings.jwt_secret_key, algorithms=["HS256"]
        )["jti"]

        assert await token_service.is_jti_revoked(old_jti) is False
        await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": account["refresh_token"]}
        )
        assert await token_service.is_jti_revoked(old_jti) is True

    async def test_concurrent_refresh_only_one_wins(
        self, client: httpx.AsyncClient, account: dict, fake_redis: _FakeRedis
    ) -> None:
        """并发刷新同一 Token 只有一个成功——SET NX 保证原子性。"""
        import asyncio

        async def _try() -> int:
            r = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": account["refresh_token"]},
            )
            return r.status_code

        results = await asyncio.gather(*[_try() for _ in range(5)])
        assert results.count(200) == 1, f"应只有一次成功，实际 {results}"
        assert results.count(401) == 4


# ============================================================
# DoD 3：账号状态
# ============================================================


class TestAccountStatus:
    async def test_banned_account_cannot_refresh(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：账号封禁状态下刷新返回 11002。"""
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            await session.execute(
                text('UPDATE "user" SET status = :s WHERE id = :uid'),
                {"s": UserStatus.BANNED.value, "uid": account["user_id"]},
            )
            await session.commit()

        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": account["refresh_token"]},
        )
        assert response.status_code == 403
        assert response.json()["code"] == ErrorCode.ACCOUNT_BANNED == 11002

    async def test_deleted_account_cannot_refresh(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            await session.execute(
                text('UPDATE "user" SET status = :s WHERE id = :uid'),
                {"s": UserStatus.DELETED.value, "uid": account["user_id"]},
            )
            await session.commit()

        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": account["refresh_token"]},
        )
        assert response.status_code == 403
        assert response.json()["code"] == ErrorCode.ACCOUNT_DELETED

    async def test_token_version_mismatch_rejected(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """登出/改密后 token_version 自增，旧 Refresh Token 失效。"""
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            await session.execute(
                text('UPDATE "user" SET token_version = token_version + 1 WHERE id = :uid'),
                {"uid": account["user_id"]},
            )
            await session.commit()

        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": account["refresh_token"]},
        )
        assert response.status_code == 401


# ============================================================
# 边界：Token 本身的问题
# ============================================================


class TestInvalidTokens:
    async def test_expired_refresh_token_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        from datetime import UTC, datetime, timedelta

        expired = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "user_type": "user",
                "token_version": 0,
                "token_type": "refresh",
                "jti": uuid.uuid4().hex,
                "exp": int((datetime.now(UTC) - timedelta(minutes=1)).timestamp()),
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": expired}
        )
        assert response.status_code == 401
        assert response.json()["code"] == 11010

    async def test_access_token_cannot_refresh(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """Access Token 不能用于刷新。"""
        from app.core.security import create_access_token

        access_token = create_access_token(str(account["user_id"]), "user", 0)

        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": access_token}
        )
        assert response.status_code == 401

    async def test_forged_token_rejected(self, client: httpx.AsyncClient) -> None:
        forged = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "user_type": "user",
                "token_version": 0,
                "token_type": "refresh",
                "jti": "x",
                "exp": 9999999999,
            },
            "another-secret-key-at-least-32-characters",
            algorithm="HS256",
        )
        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": forged}
        )
        assert response.status_code == 401

    async def test_missing_token_rejected(self, client: httpx.AsyncClient) -> None:
        response = await client.post("/api/v1/auth/refresh", json={})
        assert response.status_code == 401

    async def test_alg_none_rejected(self, client: httpx.AsyncClient) -> None:
        forged = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "user_type": "user",
                "token_version": 0,
                "token_type": "refresh",
                "jti": "x",
                "exp": 9999999999,
            },
            key="",
            algorithm="none",
        )
        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": forged}
        )
        assert response.status_code == 401


# ============================================================
# 响应结构
# ============================================================


class TestResponseShape:
    async def test_response_has_exactly_three_fields(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """API §3.6 定义：只有 access_token / refresh_token / expires_in。"""
        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": account["refresh_token"]}
        )
        assert set(response.json()["data"]) == {
            "access_token",
            "refresh_token",
            "expires_in",
        }

    async def test_new_refresh_cookie_set(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": account["refresh_token"]}
        )
        cookie = response.headers.get("set-cookie", "")
        assert settings.refresh_cookie_name in cookie
        assert "HttpOnly" in cookie


# ============================================================
# Redis 不可用
# ============================================================


class TestRedisUnavailable:
    async def test_refresh_rejected_when_redis_down(
        self, client: httpx.AsyncClient, account: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Redis 不可用时拒绝刷新——无法保证轮换原子性，放行会导致重放。"""

        class _Broken:
            async def set(self, *a: Any, **k: Any) -> None:
                raise ConnectionError("redis down")

            async def get(self, *a: Any, **k: Any) -> None:
                raise ConnectionError("redis down")

        monkeypatch.setattr(token_service.redis_infra, "get_client", lambda: _Broken())

        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": account["refresh_token"]},
        )
        assert response.status_code == 503
