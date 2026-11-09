"""M01-T10 用户资料查询与更新的测试。

覆盖 DoD：
    1. 手机号脱敏形如 138****8888、邮箱形如 us***@example.com
    2. credential、token_version 不出现在响应中
    3. 更新后再次查询返回新值
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
from app.modules.account.constants import Gender, VerifyScene

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
async def phone_account(db_ready: None, fake_redis: _FakeRedis) -> Any:
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

    yield {"user_id": result.user_id, "access_token": result.access_token, "target": phone}

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
# DoD 1：脱敏（纯函数）
# ============================================================


class TestMasking:
    def test_phone_masked_middle_four(self) -> None:
        """DoD：手机号脱敏形如 138****8888。"""
        assert service.mask_provider_uid("phone", "13800138888") == "138****8888"

    def test_email_masked(self) -> None:
        """DoD：邮箱脱敏形如 us***@example.com。"""
        assert service.mask_provider_uid("email", "user@example.com") == "us***@example.com"

    def test_short_email(self) -> None:
        assert service.mask_provider_uid("email", "a@b.com") == "a***@b.com"

    def test_third_party_uid_masked(self) -> None:
        masked = service.mask_provider_uid("wechat", "openid_abcdefghijklmn")
        assert masked.startswith("open")
        assert masked.endswith("klmn")
        assert "***" in masked

    def test_short_uid_fully_masked(self) -> None:
        assert service.mask_provider_uid("wechat", "abc") == "***"

    def test_invalid_email_masked(self) -> None:
        assert service.mask_provider_uid("email", "not-an-email") == "***"


# ============================================================
# DoD 2：查询/更新用户资料
# ============================================================


class TestGetMe:
    async def test_returns_profile(
        self, client: httpx.AsyncClient, phone_account: dict
    ) -> None:
        response = await client.get(
            "/api/v1/users/me", headers=_auth(phone_account["access_token"])
        )

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert set(data) >= {
            "id",
            "username",
            "nickname",
            "avatar_url",
            "gender",
            "region_code",
            "region",
            "status",
            "created_at",
            "bindings",
        }
        assert data["id"] == str(phone_account["user_id"])
        assert data["status"] == "active"

    async def test_region_resolved_to_name(
        self, client: httpx.AsyncClient, phone_account: dict
    ) -> None:
        """常驻地区返回层级名称——前端不该显示 330100 这种编码。"""
        headers = _auth(phone_account["access_token"])
        await client.patch(
            "/api/v1/users/me", headers=headers, json={"region_code": "330100"}
        )

        response = await client.get("/api/v1/users/me", headers=headers)
        data = response.json()["data"]

        region = data["region"]
        if region is None:
            pytest.skip("地区字典未初始化")

        assert region["code"] == "330100"
        assert region["province"] == "浙江省"
        assert region["city"] == "杭州市"
        assert region["display"] == "浙江省 杭州市"

    async def test_region_null_when_unset(
        self, client: httpx.AsyncClient, phone_account: dict
    ) -> None:
        headers = _auth(phone_account["access_token"])
        response = await client.get("/api/v1/users/me", headers=headers)
        data = response.json()["data"]

        if data["region_code"] is None:
            assert data["region"] is None

    async def test_region_null_when_code_unknown(
        self, client: httpx.AsyncClient, phone_account: dict
    ) -> None:
        """编码在字典中不存在时返回 null，而不是报错——资料仍可展示。"""
        headers = _auth(phone_account["access_token"])
        await client.patch(
            "/api/v1/users/me", headers=headers, json={"region_code": "999999"}
        )

        response = await client.get("/api/v1/users/me", headers=headers)

        assert response.status_code == 200
        assert response.json()["data"]["region"] is None

    async def test_bindings_are_masked(
        self, client: httpx.AsyncClient, phone_account: dict
    ) -> None:
        """DoD：provider_uid 需脱敏。"""
        response = await client.get(
            "/api/v1/users/me", headers=_auth(phone_account["access_token"])
        )
        bindings = response.json()["data"]["bindings"]

        assert len(bindings) == 1
        binding = bindings[0]
        assert binding["provider"] == "phone"
        assert binding["is_primary"] is True
        # 脱敏：不出现完整手机号
        assert phone_account["target"] not in binding["provider_uid"]
        assert "****" in binding["provider_uid"]

    async def test_no_sensitive_fields(
        self, client: httpx.AsyncClient, phone_account: dict
    ) -> None:
        """DoD：credential、token_version 不出现在响应中。"""
        response = await client.get(
            "/api/v1/users/me", headers=_auth(phone_account["access_token"])
        )
        body = response.text.lower()
        for field in ("credential", "token_version", "password", "$2b$"):
            assert field not in body, f"响应泄露了 {field}"

    async def test_requires_authentication(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v1/users/me")
        assert response.status_code == 401
        assert response.json()["code"] == ErrorCode.UNAUTHORIZED


# ============================================================
# DoD 3：更新资料
# ============================================================


class TestUpdateMe:
    async def test_update_nickname(
        self, client: httpx.AsyncClient, phone_account: dict
    ) -> None:
        """DoD：更新后再次查询返回新值。"""
        response = await client.patch(
            "/api/v1/users/me",
            headers=_auth(phone_account["access_token"]),
            json={"nickname": "新昵称"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["nickname"] == "新昵称"

        # 再次查询确认持久化
        again = await client.get(
            "/api/v1/users/me", headers=_auth(phone_account["access_token"])
        )
        assert again.json()["data"]["nickname"] == "新昵称"

    async def test_update_multiple_fields(
        self, client: httpx.AsyncClient, phone_account: dict
    ) -> None:
        response = await client.patch(
            "/api/v1/users/me",
            headers=_auth(phone_account["access_token"]),
            json={
                "nickname": "旅行者",
                "gender": Gender.FEMALE.value,
                "region_code": "110000",
                "avatar_url": "https://cdn.example.com/a.jpg",
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["nickname"] == "旅行者"
        assert data["gender"] == "female"
        assert data["region_code"] == "110000"
        assert data["avatar_url"] == "https://cdn.example.com/a.jpg"

    async def test_partial_update_does_not_touch_others(
        self, client: httpx.AsyncClient, phone_account: dict
    ) -> None:
        """部分更新：只改传入的字段。"""
        # 先设置完整资料
        await client.patch(
            "/api/v1/users/me",
            headers=_auth(phone_account["access_token"]),
            json={"nickname": "原名", "region_code": "110000"},
        )
        # 只改昵称
        response = await client.patch(
            "/api/v1/users/me",
            headers=_auth(phone_account["access_token"]),
            json={"nickname": "新名"},
        )
        data = response.json()["data"]
        assert data["nickname"] == "新名"
        assert data["region_code"] == "110000", "未传的字段应保持不变"

    async def test_clear_avatar_with_null(
        self, client: httpx.AsyncClient, phone_account: dict
    ) -> None:
        """传 null 表示清空该字段。"""
        await client.patch(
            "/api/v1/users/me",
            headers=_auth(phone_account["access_token"]),
            json={"avatar_url": "https://cdn.example.com/a.jpg"},
        )
        response = await client.patch(
            "/api/v1/users/me",
            headers=_auth(phone_account["access_token"]),
            json={"avatar_url": None},
        )
        assert response.json()["data"]["avatar_url"] is None


# ============================================================
# 边界：参数校验
# ============================================================


class TestValidation:
    async def test_invalid_avatar_url(
        self, client: httpx.AsyncClient, phone_account: dict
    ) -> None:
        """avatar_url 必须以 http(s):// 开头。"""
        response = await client.patch(
            "/api/v1/users/me",
            headers=_auth(phone_account["access_token"]),
            json={"avatar_url": "javascript:alert(1)"},
        )
        assert response.status_code == 400
        assert response.json()["code"] == ErrorCode.VALIDATION_FAILED

    async def test_avatar_url_too_long(
        self, client: httpx.AsyncClient, phone_account: dict
    ) -> None:
        """avatar_url 长度 ≤500。"""
        response = await client.patch(
            "/api/v1/users/me",
            headers=_auth(phone_account["access_token"]),
            json={"avatar_url": "https://x.com/" + "a" * 500},
        )
        assert response.status_code == 400

    async def test_nickname_too_long(
        self, client: httpx.AsyncClient, phone_account: dict
    ) -> None:
        response = await client.patch(
            "/api/v1/users/me",
            headers=_auth(phone_account["access_token"]),
            json={"nickname": "x" * 51},
        )
        assert response.status_code == 400

    async def test_invalid_gender(
        self, client: httpx.AsyncClient, phone_account: dict
    ) -> None:
        response = await client.patch(
            "/api/v1/users/me",
            headers=_auth(phone_account["access_token"]),
            json={"gender": "unknown"},
        )
        assert response.status_code == 400

    async def test_b_token_cannot_access(
        self, client: httpx.AsyncClient, phone_account: dict
    ) -> None:
        """双端隔离：B 端 Token 不能访问 C 端资料。"""
        from app.core.security import create_access_token

        b_token = create_access_token(str(uuid.uuid4()), "admin", 0)
        response = await client.get("/api/v1/users/me", headers=_auth(b_token))
        assert response.status_code == 403
