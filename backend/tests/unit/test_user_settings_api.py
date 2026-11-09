"""M01-T13 隐私设置接口的测试。

覆盖 DoD：
    1. 三个可见性字段枚举校验 public/friends/private
    2. Patch 仅更新传入字段
    3. 更新后查询返回一致

重点：布尔字段必须能区分「未传」与「传 false」。
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

    yield {"user_id": result.user_id, "access_token": result.access_token}

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


async def _get_settings(client: httpx.AsyncClient, token: str) -> dict:
    response = await client.get("/api/v1/users/me/settings", headers=_auth(token))
    return response.json()["data"]


# ============================================================
# 查询
# ============================================================


class TestGetSettings:
    async def test_defaults(self, client: httpx.AsyncClient, account: dict) -> None:
        """新用户默认：全部 public，允许推荐与通知。"""
        data = await _get_settings(client, account["access_token"])
        assert data == {
            "profile_visibility": "public",
            "footprint_visibility": "public",
            "plan_visibility": "public",
            "allow_recommendation": True,
            "allow_notification": True,
        }

    async def test_has_exactly_five_fields(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        data = await _get_settings(client, account["access_token"])
        assert set(data) == {
            "profile_visibility",
            "footprint_visibility",
            "plan_visibility",
            "allow_recommendation",
            "allow_notification",
        }

    async def test_requires_auth(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/api/v1/users/me/settings")).status_code == 401


# ============================================================
# DoD 2：Patch 仅更新传入字段
# ============================================================


class TestPartialUpdate:
    async def test_only_updates_provided_field(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：Patch 仅更新传入字段。"""
        response = await client.patch(
            "/api/v1/users/me/settings",
            headers=_auth(account["access_token"]),
            json={"profile_visibility": "private"},
        )
        assert response.status_code == 204

        data = await _get_settings(client, account["access_token"])
        assert data["profile_visibility"] == "private"
        # 其他字段保持默认
        assert data["footprint_visibility"] == "public"
        assert data["plan_visibility"] == "public"
        assert data["allow_recommendation"] is True

    async def test_no_fields_does_nothing(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """传空对象不改变任何字段。"""
        response = await client.patch(
            "/api/v1/users/me/settings",
            headers=_auth(account["access_token"]),
            json={},
        )
        assert response.status_code == 204

        data = await _get_settings(client, account["access_token"])
        assert data["profile_visibility"] == "public"
        assert data["allow_recommendation"] is True


# ============================================================
# 边界：布尔字段的 false
# ============================================================


class TestBooleanFalse:
    async def test_false_is_applied(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """**关键边界**：传 false 必须生效，不能被当成「未传」。"""
        response = await client.patch(
            "/api/v1/users/me/settings",
            headers=_auth(account["access_token"]),
            json={"allow_recommendation": False},
        )
        assert response.status_code == 204

        data = await _get_settings(client, account["access_token"])
        assert data["allow_recommendation"] is False, "false 应生效"
        assert data["allow_notification"] is True, "未传的字段不受影响"

    async def test_both_false(self, client: httpx.AsyncClient, account: dict) -> None:
        await client.patch(
            "/api/v1/users/me/settings",
            headers=_auth(account["access_token"]),
            json={"allow_recommendation": False, "allow_notification": False},
        )
        data = await _get_settings(client, account["access_token"])
        assert data["allow_recommendation"] is False
        assert data["allow_notification"] is False

    async def test_true_restores(self, client: httpx.AsyncClient, account: dict) -> None:
        """置 false 后可以再置回 true。"""
        token = account["access_token"]
        await client.patch(
            "/api/v1/users/me/settings",
            headers=_auth(token),
            json={"allow_recommendation": False},
        )
        await client.patch(
            "/api/v1/users/me/settings",
            headers=_auth(token),
            json={"allow_recommendation": True},
        )
        data = await _get_settings(client, token)
        assert data["allow_recommendation"] is True


# ============================================================
# DoD 1：枚举校验
# ============================================================


class TestVisibilityValidation:
    @pytest.mark.parametrize("value", ["public", "friends", "private"])
    async def test_all_valid_values(
        self, client: httpx.AsyncClient, account: dict, value: str
    ) -> None:
        for field in (
            "profile_visibility",
            "footprint_visibility",
            "plan_visibility",
        ):
            response = await client.patch(
                "/api/v1/users/me/settings",
                headers=_auth(account["access_token"]),
                json={field: value},
            )
            assert response.status_code == 204, f"{field}={value} 应通过"

    @pytest.mark.parametrize("value", ["public_only", "friend", "PRIVATE", ""])
    async def test_invalid_values_rejected(
        self, client: httpx.AsyncClient, account: dict, value: str
    ) -> None:
        """DoD：枚举校验。"""
        response = await client.patch(
            "/api/v1/users/me/settings",
            headers=_auth(account["access_token"]),
            json={"profile_visibility": value},
        )
        assert response.status_code == 400
        assert response.json()["code"] == ErrorCode.VALIDATION_FAILED

    async def test_three_fields_independent(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """三个可见性字段互相独立。"""
        await client.patch(
            "/api/v1/users/me/settings",
            headers=_auth(account["access_token"]),
            json={
                "profile_visibility": "private",
                "footprint_visibility": "friends",
                "plan_visibility": "public",
            },
        )
        data = await _get_settings(client, account["access_token"])
        assert data["profile_visibility"] == "private"
        assert data["footprint_visibility"] == "friends"
        assert data["plan_visibility"] == "public"


# ============================================================
# DoD 3：更新后查询一致
# ============================================================


class TestRoundTrip:
    async def test_full_update_persists(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        token = account["access_token"]
        payload = {
            "profile_visibility": "friends",
            "footprint_visibility": "private",
            "plan_visibility": "private",
            "allow_recommendation": False,
            "allow_notification": False,
        }
        await client.patch(
            "/api/v1/users/me/settings", headers=_auth(token), json=payload
        )

        data = await _get_settings(client, token)
        assert data == payload


# ============================================================
# 边界：记录缺失与认证
# ============================================================


class TestMissingRecord:
    async def test_update_creates_missing_record(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            await session.execute(
                text("DELETE FROM user_setting WHERE user_id = :uid"),
                {"uid": account["user_id"]},
            )
            await session.commit()

        response = await client.patch(
            "/api/v1/users/me/settings",
            headers=_auth(account["access_token"]),
            json={"profile_visibility": "private"},
        )
        assert response.status_code == 204

        data = await _get_settings(client, account["access_token"])
        assert data["profile_visibility"] == "private"

    async def test_get_returns_defaults_when_missing(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            await session.execute(
                text("DELETE FROM user_setting WHERE user_id = :uid"),
                {"uid": account["user_id"]},
            )
            await session.commit()

        data = await _get_settings(client, account["access_token"])
        assert data["profile_visibility"] == "public"


class TestAuth:
    async def test_patch_requires_auth(self, client: httpx.AsyncClient) -> None:
        response = await client.patch("/api/v1/users/me/settings", json={})
        assert response.status_code == 401
