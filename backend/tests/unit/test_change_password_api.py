"""M01-T11 修改密码接口的测试。

覆盖 DoD：
    1. 原密码错误返回 11006（400）
    2. 新旧密码相同返回 11011（400）
    3. 修改成功后 token_version 自增，原 Token 失效
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

OLD_PASSWORD = "OldPass123"
NEW_PASSWORD = "NewPass456"


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
    """有密码的账号（显式注册）。"""
    from app.db.session import SessionLocal
    from app.modules.account import verification

    phone = f"139{uuid.uuid4().int % 100000000:08d}"
    await fake_redis.set(
        verification._code_key(VerifyScene.REGISTER, phone), "123456", ex=300
    )

    async with SessionLocal() as session:
        result = await service.register(
            session, target=phone, verify_code_str="123456", password=OLD_PASSWORD
        )

    yield {
        "user_id": result.user_id,
        "access_token": result.access_token,
        "refresh_token": result.refresh_token,
        "target": phone,
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


@pytest.fixture
async def no_password_account(db_ready: None, fake_redis: _FakeRedis) -> Any:
    """无密码账号（验证码自动注册）。"""
    from app.db.session import SessionLocal
    from app.modules.account import verification

    phone = f"139{uuid.uuid4().int % 100000000:08d}"
    await fake_redis.set(
        verification._code_key(VerifyScene.LOGIN, phone), "123456", ex=300
    )

    async with SessionLocal() as session:
        result = await service.login_or_register_by_code(
            session, target=phone, verify_code_str="123456"
        )

    yield {
        "user_id": result.user_id,
        "access_token": result.access_token,
        "target": phone,
        "is_new": result.is_new_user,
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
# DoD 1：原密码错误
# ============================================================


class TestOldPasswordValidation:
    async def test_wrong_old_password_returns_11006(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：原密码错误返回 11006（400）。"""
        response = await client.put(
            "/api/v1/users/me/password",
            headers=_auth(account["access_token"]),
            json={"old_password": "WrongOld1", "new_password": NEW_PASSWORD},
        )
        assert response.status_code == 400
        assert response.json()["code"] == ErrorCode.INVALID_CREDENTIAL == 11006

    async def test_missing_old_password_for_existing_account(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """已有密码的账号不传 old_password 也应拒绝。"""
        response = await client.put(
            "/api/v1/users/me/password",
            headers=_auth(account["access_token"]),
            json={"new_password": NEW_PASSWORD},
        )
        assert response.status_code == 400
        assert response.json()["code"] == 11006


# ============================================================
# DoD 2：新旧相同
# ============================================================


class TestSamePassword:
    async def test_same_password_returns_11011(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：新旧密码相同返回 11011（400）。"""
        response = await client.put(
            "/api/v1/users/me/password",
            headers=_auth(account["access_token"]),
            json={"old_password": OLD_PASSWORD, "new_password": OLD_PASSWORD},
        )
        assert response.status_code == 400
        assert response.json()["code"] == ErrorCode.SAME_PASSWORD == 11011


# ============================================================
# DoD 3：修改成功
# ============================================================


class TestChangeSuccess:
    async def test_returns_204(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        response = await client.put(
            "/api/v1/users/me/password",
            headers=_auth(account["access_token"]),
            json={"old_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert response.status_code == 204

    async def test_token_version_increments(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：修改成功后 token_version 自增。"""
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            before = await session.execute(
                text('SELECT token_version FROM "user" WHERE id = :uid'),
                {"uid": account["user_id"]},
            )
            before_version = before.scalar_one()

        await client.put(
            "/api/v1/users/me/password",
            headers=_auth(account["access_token"]),
            json={"old_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
        )

        async with SessionLocal() as session:
            after = await session.execute(
                text('SELECT token_version FROM "user" WHERE id = :uid'),
                {"uid": account["user_id"]},
            )
            after_version = after.scalar_one()

        assert after_version == before_version + 1

    async def test_old_access_token_invalidated(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：修改后原 Access Token 失效。"""
        old_token = account["access_token"]
        await client.put(
            "/api/v1/users/me/password",
            headers=_auth(old_token),
            json={"old_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
        )

        response = await client.get("/api/v1/users/me", headers=_auth(old_token))
        assert response.status_code == 401

    async def test_old_refresh_token_invalidated(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：修改后原 Refresh Token 失效。"""
        old_refresh = account["refresh_token"]
        await client.put(
            "/api/v1/users/me/password",
            headers=_auth(account["access_token"]),
            json={"old_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
        )

        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": old_refresh}
        )
        assert response.status_code == 401

    async def test_new_password_works(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """修改后用新密码登录成功，旧密码失败。"""
        await client.put(
            "/api/v1/users/me/password",
            headers=_auth(account["access_token"]),
            json={"old_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
        )

        # 旧密码失败
        old_login = await client.post(
            "/api/v1/auth/login",
            json={"target": account["target"], "password": OLD_PASSWORD},
        )
        assert old_login.json()["code"] == 11006

        # 新密码成功
        new_login = await client.post(
            "/api/v1/auth/login",
            json={"target": account["target"], "password": NEW_PASSWORD},
        )
        assert new_login.status_code == 200


# ============================================================
# 边界：无密码账号首次设置
# ============================================================


class TestFirstTimeSetPassword:
    async def test_no_password_account_can_set_without_old(
        self, client: httpx.AsyncClient, no_password_account: dict
    ) -> None:
        """边界：自动注册的无密码账号首次设密码，old_password 可为空。"""
        response = await client.put(
            "/api/v1/users/me/password",
            headers=_auth(no_password_account["access_token"]),
            json={"new_password": NEW_PASSWORD},
        )
        assert response.status_code == 204, response.text

    async def test_after_setting_password_login_works(
        self, client: httpx.AsyncClient, no_password_account: dict
    ) -> None:
        """设置密码后可正常密码登录。"""
        await client.put(
            "/api/v1/users/me/password",
            headers=_auth(no_password_account["access_token"]),
            json={"new_password": NEW_PASSWORD},
        )

        login = await client.post(
            "/api/v1/auth/login",
            json={"target": no_password_account["target"], "password": NEW_PASSWORD},
        )
        assert login.status_code == 200

    async def test_second_change_requires_old_password(
        self, client: httpx.AsyncClient, no_password_account: dict
    ) -> None:
        """首次设置后，再次修改必须提供原密码。"""
        await client.put(
            "/api/v1/users/me/password",
            headers=_auth(no_password_account["access_token"]),
            json={"new_password": NEW_PASSWORD},
        )

        # 用新密码登录拿新 Token
        login = await client.post(
            "/api/v1/auth/login",
            json={"target": no_password_account["target"], "password": NEW_PASSWORD},
        )
        new_token = login.json()["data"]["access_token"]

        # 不传 old_password 应失败
        response = await client.put(
            "/api/v1/users/me/password",
            headers=_auth(new_token),
            json={"new_password": "Another789"},
        )
        assert response.status_code == 400
        assert response.json()["code"] == 11006

    async def test_third_party_account_can_set_password(
        self, client: httpx.AsyncClient
    ) -> None:
        """第三方登录的账号也可首次设置密码。"""
        from app.infra.oauth import OAuthUserInfo, get_provider

        provider = get_provider("wechat")
        provider.set_mock_response(  # type: ignore[attr-defined]
            OAuthUserInfo(provider_uid=f"openid_{uuid.uuid4().hex[:16]}")
        )

        login = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "wechat", "code": "c", "state": "s"},
        )
        user_id = login.json()["data"]["user_id"]
        token = login.json()["data"]["access_token"]

        try:
            response = await client.put(
                "/api/v1/users/me/password",
                headers=_auth(token),
                json={"new_password": NEW_PASSWORD},
            )
            assert response.status_code == 204
        finally:
            provider.clear_mock()  # type: ignore[attr-defined]
            from app.db.session import SessionLocal

            async with SessionLocal() as session:
                for table in ("user_setting", "user_profile", "oauth_binding"):
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE user_id = :uid"),
                        {"uid": user_id},
                    )
                await session.execute(
                    text('DELETE FROM "user" WHERE id = :uid'), {"uid": user_id}
                )
                await session.commit()


# ============================================================
# 参数校验
# ============================================================


class TestValidation:
    @pytest.mark.parametrize(
        "new_password", ["short1", "12345678", "abcdefgh", "a" * 33]
    )
    async def test_weak_password_rejected(
        self, client: httpx.AsyncClient, account: dict, new_password: str
    ) -> None:
        response = await client.put(
            "/api/v1/users/me/password",
            headers=_auth(account["access_token"]),
            json={"old_password": OLD_PASSWORD, "new_password": new_password},
        )
        assert response.status_code == 400
        assert response.json()["code"] == ErrorCode.VALIDATION_FAILED

    async def test_requires_authentication(self, client: httpx.AsyncClient) -> None:
        response = await client.put(
            "/api/v1/users/me/password",
            json={"old_password": "x", "new_password": NEW_PASSWORD},
        )
        assert response.status_code == 401
