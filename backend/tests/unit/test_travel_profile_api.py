"""M01-T12 旅游偏好接口的测试。

覆盖 DoD：
    1. 数组字段最多 10 项、每项 ≤20 字符
    2. budget_level 枚举校验
    3. 更新后查询返回一致
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
from app.modules.account.constants import (
    PROFILE_ARRAY_ITEM_MAX_LENGTH,
    PROFILE_ARRAY_MAX_ITEMS,
    SEASON_ARRAY_MAX_ITEMS,
    VerifyScene,
)

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
            session, target=phone, verify_code_str="123456"
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


# ============================================================
# 查询
# ============================================================


class TestGetProfile:
    async def test_new_user_returns_empty(self, client: httpx.AsyncClient, account: dict) -> None:
        """新用户偏好为空。"""
        response = await client.get(
            "/api/v1/users/me/profile", headers=_auth(account["access_token"])
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["travel_types"] == []
        assert data["travel_styles"] == []
        assert data["budget_level"] is None
        assert data["companion_type"] is None
        assert data["preferred_seasons"] == []
        assert data["departure_city_code"] is None

    async def test_has_all_six_fields(self, client: httpx.AsyncClient, account: dict) -> None:
        response = await client.get(
            "/api/v1/users/me/profile", headers=_auth(account["access_token"])
        )
        assert set(response.json()["data"]) == {
            "travel_types",
            "travel_styles",
            "budget_level",
            "companion_type",
            "preferred_seasons",
            # 编码 + 后端解析出的城市信息（前端不该自己维护映射表）
            "departure_city_code",
            "departure_city_info",
        }

    async def test_requires_auth(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/api/v1/users/me/profile")).status_code == 401


# ============================================================
# 更新
# ============================================================


class TestUpdateProfile:
    async def test_full_update(self, client: httpx.AsyncClient, account: dict) -> None:
        """DoD：更新后查询返回一致。"""
        payload = {
            "travel_types": ["历史人文", "自然风光"],
            "travel_styles": ["深度游", "家庭出游"],
            "budget_level": "moderate",
            "companion_type": "family",
            "preferred_seasons": ["春季", "秋季"],
            "departure_city_code": "110100",
        }
        response = await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json=payload,
        )
        assert response.status_code == 204

        again = await client.get(
            "/api/v1/users/me/profile", headers=_auth(account["access_token"])
        )
        data = again.json()["data"]
        for key, value in payload.items():
            assert data[key] == value, f"{key} 不一致"

    async def test_empty_array_is_different_from_null(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """边界：空数组与 null 语义不同。

        空数组 = 用户清空了该偏好（存 []）
        null/未传 = 整体替换语义下置为 None
        """
        # 先设置
        await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"travel_types": ["历史人文"]},
        )
        # 传空数组
        await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"travel_types": []},
        )

        data = (
            await client.get(
                "/api/v1/users/me/profile", headers=_auth(account["access_token"])
            )
        ).json()["data"]
        assert data["travel_types"] == []

    async def test_omitted_field_is_reset(self, client: httpx.AsyncClient, account: dict) -> None:
        """**整体替换语义**：未传的字段被重置为 null（API §3.12）。"""
        # 先设置两个字段
        await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"travel_types": ["历史人文"], "departure_city_code": "110100"},
        )

        # 只传 travel_types
        await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"travel_types": ["自然风光"]},
        )

        data = (
            await client.get(
                "/api/v1/users/me/profile", headers=_auth(account["access_token"])
            )
        ).json()["data"]
        assert data["travel_types"] == ["自然风光"]
        assert data["departure_city_code"] is None, "整体替换语义下未传字段应被清空"


# ============================================================
# DoD 1：数组校验
# ============================================================


class TestArrayValidation:
    async def test_max_10_items_allowed(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        items = [f"类型{i}" for i in range(PROFILE_ARRAY_MAX_ITEMS)]
        response = await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"travel_types": items},
        )
        assert response.status_code == 204

    async def test_11_items_rejected(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：数组最多 10 项。"""
        items = [f"类型{i}" for i in range(PROFILE_ARRAY_MAX_ITEMS + 1)]
        response = await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"travel_types": items},
        )
        assert response.status_code == 400
        assert response.json()["code"] == ErrorCode.VALIDATION_FAILED

    async def test_item_too_long_rejected(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：每项 ≤20 字符。"""
        response = await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"travel_types": ["x" * (PROFILE_ARRAY_ITEM_MAX_LENGTH + 1)]},
        )
        assert response.status_code == 400

    async def test_item_exactly_20_allowed(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        response = await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"travel_types": ["x" * PROFILE_ARRAY_ITEM_MAX_LENGTH]},
        )
        assert response.status_code == 204

    async def test_seasons_max_4(self, client: httpx.AsyncClient, account: dict) -> None:
        """季节比其他数组严格：最多 4 项（API §3.12）。"""
        ok = await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"preferred_seasons": ["春", "夏", "秋", "冬"]},
        )
        assert ok.status_code == 204

        too_many = await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"preferred_seasons": [f"季节{i}" for i in range(SEASON_ARRAY_MAX_ITEMS + 1)]},
        )
        assert too_many.status_code == 400


# ============================================================
# DoD 2：枚举校验
# ============================================================


class TestEnumValidation:
    @pytest.mark.parametrize("level", ["economy", "moderate", "comfortable", "luxury"])
    async def test_valid_budget_level(
        self, client: httpx.AsyncClient, account: dict, level: str
    ) -> None:
        response = await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"budget_level": level},
        )
        assert response.status_code == 204

    async def test_invalid_budget_level(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：budget_level 枚举校验。"""
        response = await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"budget_level": "expensive"},
        )
        assert response.status_code == 400

    @pytest.mark.parametrize("kind", ["solo", "couple", "family", "friends"])
    async def test_valid_companion_type(
        self, client: httpx.AsyncClient, account: dict, kind: str
    ) -> None:
        response = await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"companion_type": kind},
        )
        assert response.status_code == 204

    async def test_invalid_companion_type(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        response = await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"companion_type": "alone"},
        )
        assert response.status_code == 400


# ============================================================
# 其他
# ============================================================


class TestOther:
    async def test_departure_city_code_format(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """出发城市存 6 位行政区划编码，不是自由文本。"""
        headers = _auth(account["access_token"])

        # 非 6 位数字 → 400
        response = await client.put(
            "/api/v1/users/me/profile",
            headers=headers,
            json={"departure_city_code": "北京"},
        )
        assert response.status_code == 400

    async def test_departure_city_code_accepted(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        headers = _auth(account["access_token"])

        response = await client.put(
            "/api/v1/users/me/profile",
            headers=headers,
            json={"departure_city_code": "110100"},
        )
        assert response.status_code == 204

        detail = await client.get("/api/v1/users/me/profile", headers=headers)
        assert detail.json()["data"]["departure_city_code"] == "110100"

    async def test_update_does_not_invalidate_tokens(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """更新偏好不应影响登录状态（与改密不同）。"""
        await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"travel_types": ["历史人文"]},
        )
        response = await client.get(
            "/api/v1/users/me/profile", headers=_auth(account["access_token"])
        )
        assert response.status_code == 200

    async def test_requires_auth(self, client: httpx.AsyncClient) -> None:
        response = await client.put("/api/v1/users/me/profile", json={})
        assert response.status_code == 401

    async def test_empty_body_resets_all(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """整体替换语义：传空对象 = 清空所有偏好。"""
        await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"travel_types": ["历史人文"], "departure_city_code": "110100"},
        )

        await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={},
        )

        data = (
            await client.get(
                "/api/v1/users/me/profile", headers=_auth(account["access_token"])
            )
        ).json()["data"]
        assert data["travel_types"] == []
        assert data["departure_city_code"] is None


class TestMissingProfileRecord:
    """覆盖「user_profile 记录不存在」的分支。

    正常情况下注册流程会创建该记录，但数据异常（如手工清理）时
    update 应能自动补建，而不是崩溃。
    """

    async def test_update_creates_missing_record(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        from app.db.session import SessionLocal

        # 手工删掉 profile 记录
        async with SessionLocal() as session:
            await session.execute(
                text("DELETE FROM user_profile WHERE user_id = :uid"),
                {"uid": account["user_id"]},
            )
            await session.commit()

        # 更新应自动重建
        response = await client.put(
            "/api/v1/users/me/profile",
            headers=_auth(account["access_token"]),
            json={"travel_types": ["历史人文"]},
        )
        assert response.status_code == 204

        data = (
            await client.get(
                "/api/v1/users/me/profile", headers=_auth(account["access_token"])
            )
        ).json()["data"]
        assert data["travel_types"] == ["历史人文"]

    async def test_get_returns_empty_when_missing(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """记录不存在时查询返回空默认值，而非 404。"""
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            await session.execute(
                text("DELETE FROM user_profile WHERE user_id = :uid"),
                {"uid": account["user_id"]},
            )
            await session.commit()

        response = await client.get(
            "/api/v1/users/me/profile", headers=_auth(account["access_token"])
        )
        assert response.status_code == 200
        assert response.json()["data"]["travel_types"] == []
