"""M01-T09 登出接口的测试。

覆盖 DoD：
    1. 登出后原 Access/Refresh Token 均返回 401
    2. user.token_version 递增 1（DB 断言）
    3. 返回 HTTP 204
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.exceptions import ErrorCode
from app.infra import redis as redis_infra
from app.main import create_app
from app.modules.account import service, token_service
from app.modules.account.constants import VerifyScene

pytestmark = pytest.mark.integration


# ============================================================
# 夹具
# ============================================================


class _FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):  # type: ignore[no-untyped-def]
        if nx and key in self._data:
            return None
        self._data[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            if self._data.pop(k, None) is not None:
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
        return True

    async def ttl(self, key: str) -> int:
        return 300


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
    """创建测试账号，返回完整登录凭据。"""
    from app.db.session import SessionLocal
    from app.modules.account import verification

    phone = f"139{uuid.uuid4().int % 100000000:08d}"
    await fake_redis.set(
        verification._code_key(VerifyScene.REGISTER, phone), "123456", ex=300
    )

    async with SessionLocal() as session:
        result = await service.register(
            session, target=phone, verify_code_str="123456", password="Passw0rd"
        )

    yield {
        "user_id": result.user_id,
        "access_token": result.access_token,
        "refresh_token": result.refresh_token,
        "target": phone,
        "password": "Passw0rd",
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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# DoD 3：返回 204
# ============================================================


class TestLogoutResponse:
    async def test_returns_204(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        response = await client.post(
            "/api/v1/auth/logout", headers=_auth(account["access_token"])
        )
        assert response.status_code == 204
        assert response.content == b"", "204 不应有响应体"

    async def test_requires_authentication(self, client: httpx.AsyncClient) -> None:
        response = await client.post("/api/v1/auth/logout")
        assert response.status_code == 401
        assert response.json()["code"] == ErrorCode.UNAUTHORIZED

    async def test_clears_refresh_cookie(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        from app.core.config import settings

        response = await client.post(
            "/api/v1/auth/logout", headers=_auth(account["access_token"])
        )
        cookie = response.headers.get("set-cookie", "")
        assert settings.refresh_cookie_name in cookie
        # delete_cookie 会产生 max-age=0 或 expires 过去时间
        assert "max-age=0" in cookie.lower() or "expires" in cookie.lower()


# ============================================================
# DoD 2：token_version 自增
# ============================================================


class TestTokenVersionIncrement:
    async def test_version_increments_by_one(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：user.token_version 递增 1（DB 断言）。"""
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            before = await session.execute(
                text('SELECT token_version FROM "user" WHERE id = :uid'),
                {"uid": account["user_id"]},
            )
            before_version = before.scalar_one()

        await client.post(
            "/api/v1/auth/logout", headers=_auth(account["access_token"])
        )

        async with SessionLocal() as session:
            after = await session.execute(
                text('SELECT token_version FROM "user" WHERE id = :uid'),
                {"uid": account["user_id"]},
            )
            after_version = after.scalar_one()

        assert after_version == before_version + 1

    async def test_concurrent_logout_increments_correctly(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """边界：并发登出时自增需原子，不能丢失更新。

        用 `UPDATE ... SET token_version = token_version + 1` 而非
        「读出来+1再写回」。
        """
        import asyncio

        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            before = await session.execute(
                text('SELECT token_version FROM "user" WHERE id = :uid'),
                {"uid": account["user_id"]},
            )
            before_version = before.scalar_one()

        async def _logout() -> int:
            r = await client.post(
                "/api/v1/auth/logout", headers=_auth(account["access_token"])
            )
            return r.status_code

        # 第一个成功后 token_version 变了，后续请求的 access_token 失效返回 401
        results = await asyncio.gather(*[_logout() for _ in range(5)])
        assert 204 in results

        async with SessionLocal() as session:
            after = await session.execute(
                text('SELECT token_version FROM "user" WHERE id = :uid'),
                {"uid": account["user_id"]},
            )
            after_version = after.scalar_one()

        # 成功的请求数与自增次数应一致
        assert after_version == before_version + results.count(204)


# ============================================================
# DoD 1：旧 Token 失效
# ============================================================


class TestTokensInvalidated:
    async def test_access_token_rejected_after_logout(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：登出后原 Access Token 返回 401。"""
        old_access = account["access_token"]
        await client.post("/api/v1/auth/logout", headers=_auth(old_access))

        # 再次用旧 Access Token 调登出（受保护接口）
        response = await client.post("/api/v1/auth/logout", headers=_auth(old_access))
        assert response.status_code == 401

    async def test_refresh_token_rejected_after_logout(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：登出后原 Refresh Token 返回 401。"""
        old_refresh = account["refresh_token"]
        await client.post(
            "/api/v1/auth/logout", headers=_auth(account["access_token"])
        )

        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": old_refresh}
        )
        assert response.status_code == 401

    async def test_new_login_works_after_logout(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """登出后用密码重新登录，新 Token 可用。"""
        await client.post(
            "/api/v1/auth/logout", headers=_auth(account["access_token"])
        )

        login = await client.post(
            "/api/v1/auth/login",
            json={"target": account["target"], "password": account["password"]},
        )
        assert login.status_code == 200
        new_access = login.json()["data"]["access_token"]

        # 新 Token 可用
        response = await client.post("/api/v1/auth/logout", headers=_auth(new_access))
        assert response.status_code == 204

    async def test_all_devices_logged_out(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """全端登出：另一台设备签发的 Token 也失效。"""
        # 模拟设备 B：用密码登录拿到另一套 Token
        device_b = await client.post(
            "/api/v1/auth/login",
            json={"target": account["target"], "password": account["password"]},
        )
        b_tokens = device_b.json()["data"]
        assert device_b.status_code == 200

        # 设备 A 登出
        await client.post(
            "/api/v1/auth/logout", headers=_auth(account["access_token"])
        )

        # 设备 B 的 Token 也失效
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": b_tokens["refresh_token"]},
        )
        assert response.status_code == 401, "全端登出应使所有设备的 Token 失效"


# ============================================================
# 边界
# ============================================================


class TestEdgeCases:
    async def test_logout_twice_second_fails(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """重复登出：第二次因 Token 已失效返回 401。"""
        first = await client.post(
            "/api/v1/auth/logout", headers=_auth(account["access_token"])
        )
        assert first.status_code == 204

        second = await client.post(
            "/api/v1/auth/logout", headers=_auth(account["access_token"])
        )
        assert second.status_code == 401

    async def test_b_token_cannot_logout_c_end(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """B 端 Token 不能调 C 端登出（双端隔离）。"""
        from app.core.security import create_access_token

        b_token = create_access_token(str(uuid.uuid4()), "admin", 0)
        response = await client.post("/api/v1/auth/logout", headers=_auth(b_token))
        assert response.status_code == 403

    async def test_malformed_token_rejected(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/auth/logout", headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert response.status_code == 401
