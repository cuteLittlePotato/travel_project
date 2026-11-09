"""M01-T06 验证码登录（自动注册）的测试。

覆盖 DoD：
    1. 未注册 target 自动创建账号并登录，响应 is_new_user=true
    2. 昵称格式符合规则（手机号 / 邮箱）
    3. 昵称冲突时最多重试 3 次
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.exceptions import ErrorCode
from app.infra import redis as redis_infra
from app.main import create_app
from app.modules.account import service
from app.modules.account.constants import UserStatus, VerifyScene
from app.utils.nickname import (
    MAX_RETRY,
    build_nickname_base,
    generate_auto_nickname,
    is_valid_auto_nickname,
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
async def cleanup() -> Any:
    created: list[uuid.UUID] = []
    yield created

    if not created:
        return
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        for uid in created:
            for table in ("user_setting", "user_profile", "oauth_binding"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE user_id = :uid"), {"uid": uid}
                )
            await session.execute(text('DELETE FROM "user" WHERE id = :uid'), {"uid": uid})
        await session.commit()


def _phone() -> str:
    return f"139{uuid.uuid4().int % 100000000:08d}"


def _email() -> str:
    return f"u{uuid.uuid4().hex[:10]}@example.com"


async def _seed(target: str, scene: VerifyScene = VerifyScene.LOGIN, code: str = "123456") -> None:
    from app.modules.account import verification

    client = redis_infra.get_client()
    await client.set(verification._code_key(scene, target), code, ex=300)


# ============================================================
# DoD 2：昵称生成（纯函数，无需数据库）
# ============================================================


class TestNicknameGeneration:
    def test_phone_nickname_format(self) -> None:
        """DoD：手机号昵称符合 ^\\d{3}\\*\\*\\*[0-9a-f]{4}$。"""
        nickname = generate_auto_nickname("13800138000")
        assert re.fullmatch(r"\d{3}\*\*\*[0-9a-f]{4}", nickname), nickname
        assert nickname.startswith("138***")

    def test_email_nickname_format(self) -> None:
        """DoD：邮箱昵称符合 ^\\w+_[0-9a-f]{4}$。"""
        nickname = generate_auto_nickname("alice@example.com")
        assert re.fullmatch(r"\w+_[0-9a-f]{4}", nickname), nickname
        assert nickname.startswith("alice_")

    def test_nickname_is_random(self) -> None:
        """每次生成的后缀不同。"""
        names = {generate_auto_nickname("13800138000") for _ in range(50)}
        assert len(names) > 45

    def test_retry_with_sequence(self) -> None:
        """DoD：冲突重试耗尽后追加序号。"""
        for attempt in range(MAX_RETRY):
            nickname = generate_auto_nickname("13800138000", attempt=attempt)
            assert re.fullmatch(r"\d{3}\*\*\*[0-9a-f]{4}", nickname)

        # 第 4 次起带序号
        nickname = generate_auto_nickname("13800138000", attempt=MAX_RETRY)
        assert re.fullmatch(r"\d{3}\*\*\*[0-9a-f]{4}_1", nickname), nickname

    def test_nickname_length_within_limit(self) -> None:
        """不能超过 user.nickname 的 VARCHAR(50)。"""
        long_email = f"{'a' * 40}@example.com"
        assert len(generate_auto_nickname(long_email)) <= 50

    def test_email_with_special_chars(self) -> None:
        """邮箱本地部分含特殊字符时被清理。"""
        base = build_nickname_base("user.name+tag@example.com")
        assert base.isalnum() or "_" in base or "-" in base

    def test_is_valid_helper(self) -> None:
        assert is_valid_auto_nickname(generate_auto_nickname("13800138000"), "13800138000")
        assert is_valid_auto_nickname(generate_auto_nickname("a@b.com"), "a@b.com")
        assert not is_valid_auto_nickname("随便写的", "13800138000")


# ============================================================
# DoD 1：自动注册
# ============================================================


class TestAutoRegister:
    async def test_new_target_creates_account(
        self, client: httpx.AsyncClient, cleanup: list, fake_redis: _FakeRedis
    ) -> None:
        """DoD：未注册 target 自动创建账号并登录，is_new_user=true。"""
        target = _phone()
        await _seed(target)

        response = await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": target, "verify_code": "123456"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["is_new_user"] is True
        assert set(data) >= {"user_id", "access_token", "refresh_token", "expires_in"}
        cleanup.append(uuid.UUID(data["user_id"]))

    async def test_existing_account_logs_in(
        self, client: httpx.AsyncClient, cleanup: list, fake_redis: _FakeRedis
    ) -> None:
        """已注册的账号直接登录，is_new_user=false。"""
        target = _phone()
        await _seed(target)

        first = await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": target, "verify_code": "123456"},
        )
        assert first.json()["data"]["is_new_user"] is True
        cleanup.append(uuid.UUID(first.json()["data"]["user_id"]))

        await _seed(target)
        second = await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": target, "verify_code": "123456"},
        )
        assert second.json()["data"]["is_new_user"] is False
        assert second.json()["data"]["user_id"] == first.json()["data"]["user_id"]

    async def test_auto_registered_account_has_no_password(
        self, client: httpx.AsyncClient, cleanup: list, fake_redis: _FakeRedis
    ) -> None:
        """边界：自动注册的账号 credential 为空，密码登录应失败。

        返回 11013（未设置密码）而非 11006（密码错误）——
        用户从没设过密码，说「密码错误」会让人反复重试。
        """
        target = _phone()
        await _seed(target)

        response = await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": target, "verify_code": "123456"},
        )
        user_id = response.json()["data"]["user_id"]
        cleanup.append(uuid.UUID(user_id))

        # 用任意密码尝试密码登录
        login = await client.post(
            "/api/v1/auth/login",
            json={"target": target, "password": "AnyPass1"},
        )
        assert login.json()["code"] == ErrorCode.PASSWORD_NOT_SET == 11013

    async def test_creates_profile_and_setting(
        self, client: httpx.AsyncClient, cleanup: list, fake_redis: _FakeRedis
    ) -> None:
        from app.db.session import SessionLocal

        target = _phone()
        await _seed(target)
        response = await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": target, "verify_code": "123456"},
        )
        user_id = response.json()["data"]["user_id"]
        cleanup.append(uuid.UUID(user_id))

        async with SessionLocal() as session:
            for table in ("user_profile", "user_setting", "oauth_binding"):
                count = await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE user_id = :uid"),
                    {"uid": user_id},
                )
                assert count.scalar_one() == 1, f"{table} 应有 1 条记录"

    async def test_nickname_follows_rule(
        self, client: httpx.AsyncClient, cleanup: list, fake_redis: _FakeRedis
    ) -> None:
        from app.db.session import SessionLocal

        target = _phone()
        await _seed(target)
        response = await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": target, "verify_code": "123456"},
        )
        user_id = response.json()["data"]["user_id"]
        cleanup.append(uuid.UUID(user_id))

        async with SessionLocal() as session:
            row = await session.execute(
                text('SELECT nickname FROM "user" WHERE id = :uid'), {"uid": user_id}
            )
            nickname = row.scalar_one()

        assert re.fullmatch(r"\d{3}\*\*\*[0-9a-f]{4}", nickname), nickname


# ============================================================
# 验证码校验
# ============================================================


class TestVerifyCode:
    async def test_wrong_code_rejected(
        self, client: httpx.AsyncClient, fake_redis: _FakeRedis
    ) -> None:
        target = _phone()
        await _seed(target)

        response = await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": target, "verify_code": "999999"},
        )
        assert response.json()["code"] == ErrorCode.INVALID_VERIFY_CODE == 11004

    async def test_missing_code_rejected(
        self, client: httpx.AsyncClient, fake_redis: _FakeRedis
    ) -> None:
        response = await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": _phone(), "verify_code": "123456"},
        )
        assert response.json()["code"] == 11004

    async def test_register_scene_code_rejected(
        self, client: httpx.AsyncClient, fake_redis: _FakeRedis
    ) -> None:
        """注册场景的验证码不能用于登录。"""
        target = _phone()
        await _seed(target, scene=VerifyScene.REGISTER)

        response = await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": target, "verify_code": "123456"},
        )
        assert response.json()["code"] == 11004


# ============================================================
# 账号状态
# ============================================================


class TestAccountStatus:
    async def test_banned_account_rejected(
        self, client: httpx.AsyncClient, cleanup: list, fake_redis: _FakeRedis
    ) -> None:
        from app.db.session import SessionLocal

        target = _phone()
        await _seed(target)
        first = await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": target, "verify_code": "123456"},
        )
        user_id = first.json()["data"]["user_id"]
        cleanup.append(uuid.UUID(user_id))

        async with SessionLocal() as session:
            await session.execute(
                text('UPDATE "user" SET status = :s WHERE id = :uid'),
                {"s": UserStatus.BANNED.value, "uid": user_id},
            )
            await session.commit()

        await _seed(target)
        response = await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": target, "verify_code": "123456"},
        )
        assert response.status_code == 403
        assert response.json()["code"] == ErrorCode.ACCOUNT_BANNED


# ============================================================
# 参数校验
# ============================================================


class TestValidation:
    @pytest.mark.parametrize("target", ["", "abc", "12345", "a@b"])
    async def test_invalid_target(self, client: httpx.AsyncClient, target: str) -> None:
        response = await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": target, "verify_code": "123456"},
        )
        assert response.status_code == 400

    async def test_code_must_be_6_digits(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": _phone(), "verify_code": "123"},
        )
        assert response.status_code == 400
