"""M01-T04 注册接口的测试。

覆盖 DoD：
    1. 注册成功返回 HTTP 201 + user_id + 双 Token
    2. 重复 target 返回 11003（HTTP 409）
    3. 注册后 user_profile、user_setting 各存在一条记录
    4. password 长度 8-32 且含字母数字；响应不含 password_hash

用真实数据库（注册要落库）+ Fake Redis（验证码）。
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from app.core.config import settings
from app.core.exceptions import ErrorCode
from app.infra import redis as redis_infra
from app.main import create_app
from app.modules.account.constants import VerifyScene

pytestmark = pytest.mark.integration


# ============================================================
# 夹具
# ============================================================


class _FakeRedis:
    """验证码服务只需 set/get/delete/incr/decr/expire/ttl。"""

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
    """注册要落库，必须确认数据库可用且表已建。

    表未建时跳过而非失败——其他集成测试（如 test_migrations）会清库，
    全量运行时顺序不固定。
    """
    from sqlalchemy import text

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
            pytest.skip('表未创建（先执行 alembic upgrade head）')


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    client = _FakeRedis()
    from app.modules.account import verification

    monkeypatch.setattr(redis_infra, "get_client", lambda: client)
    monkeypatch.setattr(verification.redis_infra, "get_client", lambda: client)
    return client


@pytest.fixture
async def client(db_ready: None) -> httpx.AsyncClient:
    """异步客户端，与 pytest 共用事件循环。

    不用 ``TestClient``：它内部会新建事件循环，导致 asyncpg 连接池
    跨事件循环复用报 ``attached to a different loop``。
    """
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def cleanup() -> Any:
    """测试后清理创建的数据。"""
    created: list[uuid.UUID] = []
    yield created

    if not created:
        return
    from sqlalchemy import text

    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        for uid in created:
            await session.execute(
                text("DELETE FROM user_setting WHERE user_id = :uid"), {"uid": uid}
            )
            await session.execute(
                text("DELETE FROM user_profile WHERE user_id = :uid"), {"uid": uid}
            )
            await session.execute(
                text("DELETE FROM oauth_binding WHERE user_id = :uid"), {"uid": uid}
            )
            await session.execute(text('DELETE FROM "user" WHERE id = :uid'), {"uid": uid})
        await session.commit()


async def _seed_code(target: str, scene: VerifyScene, code: str = "123456") -> None:
    """把验证码直接写进 Fake Redis，跳过发送流程。"""
    from app.modules.account import verification

    client = redis_infra.get_client()
    await client.set(verification._code_key(scene, target), code, ex=300)


def _unique_phone() -> str:
    return f"139{uuid.uuid4().int % 100000000:08d}"


def _unique_email() -> str:
    return f"u{uuid.uuid4().hex[:10]}@example.com"


# ============================================================
# DoD 1：注册成功
# ============================================================


class TestRegisterSuccess:
    async def test_returns_201_with_tokens(
        self, client: httpx.AsyncClient, cleanup: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.account import verification

        # 用独立的 redis 实例存放验证码，避免 fixture 作用域问题
        target = _unique_phone()
        fake = _FakeRedis()
        monkeypatch.setattr(redis_infra, "get_client", lambda: fake)
        monkeypatch.setattr(verification.redis_infra, "get_client", lambda: fake)
        await fake.set(verification._code_key(VerifyScene.REGISTER, target), "123456", ex=300)

        response = await client.post(
            "/api/v1/auth/register",
            json={
                "target": target,
                "verify_code": "123456",
                "password": "Passw0rd",
                "nickname": "测试用户",
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["code"] == 0
        data = body["data"]
        assert set(data) >= {"user_id", "access_token", "refresh_token", "expires_in"}
        assert data["expires_in"] == settings.access_token_expire_minutes * 60
        cleanup.append(uuid.UUID(data["user_id"]))

    async def test_creates_profile_and_setting(
        self, client: httpx.AsyncClient, cleanup: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DoD：注册后 user_profile、user_setting 各存在一条记录。"""
        from sqlalchemy import text

        from app.db.session import SessionLocal
        from app.modules.account import verification

        target = _unique_phone()
        fake = _FakeRedis()
        monkeypatch.setattr(redis_infra, "get_client", lambda: fake)
        monkeypatch.setattr(verification.redis_infra, "get_client", lambda: fake)
        await fake.set(verification._code_key(VerifyScene.REGISTER, target), "123456", ex=300)

        response = await client.post(
            "/api/v1/auth/register",
            json={"target": target, "verify_code": "123456", "password": "Passw0rd"},
        )
        assert response.status_code == 201
        user_id = response.json()["data"]["user_id"]
        cleanup.append(uuid.UUID(user_id))

        async with SessionLocal() as session:
            profile = await session.execute(
                text("SELECT count(*) FROM user_profile WHERE user_id = :uid"),
                {"uid": user_id},
            )
            setting = await session.execute(
                text("SELECT count(*) FROM user_setting WHERE user_id = :uid"),
                {"uid": user_id},
            )
            binding = await session.execute(
                text("SELECT count(*) FROM oauth_binding WHERE user_id = :uid"),
                {"uid": user_id},
            )
        assert profile.scalar_one() == 1
        assert setting.scalar_one() == 1
        assert binding.scalar_one() == 1

    async def test_refresh_cookie_set(
        self, client: httpx.AsyncClient, cleanup: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """评审 §Q1：Refresh Token 必须写入 httpOnly Cookie。"""
        from app.modules.account import verification

        target = _unique_phone()
        fake = _FakeRedis()
        monkeypatch.setattr(redis_infra, "get_client", lambda: fake)
        monkeypatch.setattr(verification.redis_infra, "get_client", lambda: fake)
        await fake.set(verification._code_key(VerifyScene.REGISTER, target), "123456", ex=300)

        response = await client.post(
            "/api/v1/auth/register",
            json={"target": target, "verify_code": "123456", "password": "Passw0rd"},
        )
        assert response.status_code == 201
        cleanup.append(uuid.UUID(response.json()["data"]["user_id"]))

        cookie = response.headers.get("set-cookie", "")
        assert settings.refresh_cookie_name in cookie
        assert "HttpOnly" in cookie
        assert f"Path={settings.refresh_cookie_path}" in cookie


# ============================================================
# DoD 2：重复注册
# ============================================================


class TestDuplicateRegistration:
    async def test_duplicate_target_returns_409(
        self, client: httpx.AsyncClient, cleanup: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DoD：重复 target 返回 11003（HTTP 409）。"""
        from app.modules.account import verification

        target = _unique_phone()
        fake = _FakeRedis()
        monkeypatch.setattr(redis_infra, "get_client", lambda: fake)
        monkeypatch.setattr(verification.redis_infra, "get_client", lambda: fake)

        await fake.set(verification._code_key(VerifyScene.REGISTER, target), "123456", ex=300)
        first = await client.post(
            "/api/v1/auth/register",
            json={"target": target, "verify_code": "123456", "password": "Passw0rd"},
        )
        assert first.status_code == 201
        cleanup.append(uuid.UUID(first.json()["data"]["user_id"]))

        await fake.set(verification._code_key(VerifyScene.REGISTER, target), "123456", ex=300)
        second = await client.post(
            "/api/v1/auth/register",
            json={"target": target, "verify_code": "123456", "password": "Passw0rd"},
        )
        assert second.status_code == 409
        assert second.json()["code"] == ErrorCode.DUPLICATE_TARGET == 11003


# ============================================================
# 边界：验证码
# ============================================================


class TestVerifyCodeErrors:
    async def test_wrong_code_returns_11004(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """边界异常：验证码错误 11004。"""
        from app.modules.account import verification

        target = _unique_phone()
        fake = _FakeRedis()
        monkeypatch.setattr(redis_infra, "get_client", lambda: fake)
        monkeypatch.setattr(verification.redis_infra, "get_client", lambda: fake)
        await fake.set(verification._code_key(VerifyScene.REGISTER, target), "123456", ex=300)

        response = await client.post(
            "/api/v1/auth/register",
            json={"target": target, "verify_code": "999999", "password": "Passw0rd"},
        )
        assert response.status_code == 400
        assert response.json()["code"] == ErrorCode.INVALID_VERIFY_CODE == 11004

    async def test_missing_code_returns_11004(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """验证码未发送过（不存在）→ 11004。"""
        from app.modules.account import verification

        fake = _FakeRedis()
        monkeypatch.setattr(redis_infra, "get_client", lambda: fake)
        monkeypatch.setattr(verification.redis_infra, "get_client", lambda: fake)

        response = await client.post(
            "/api/v1/auth/register",
            json={
                "target": _unique_phone(),
                "verify_code": "123456",
                "password": "Passw0rd",
            },
        )
        assert response.status_code == 400
        assert response.json()["code"] == 11004

    async def test_code_of_wrong_scene_rejected(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.account import verification

        target = _unique_phone()
        fake = _FakeRedis()
        monkeypatch.setattr(redis_infra, "get_client", lambda: fake)
        monkeypatch.setattr(verification.redis_infra, "get_client", lambda: fake)
        # 只写了 login 场景的验证码
        await fake.set(verification._code_key(VerifyScene.LOGIN, target), "123456", ex=300)

        response = await client.post(
            "/api/v1/auth/register",
            json={"target": target, "verify_code": "123456", "password": "Passw0rd"},
        )
        assert response.status_code == 400
        assert response.json()["code"] == 11004


# ============================================================
# DoD 4：参数校验与敏感字段
# ============================================================


class TestValidation:
    @pytest.mark.parametrize(
        "password",
        ["short1", "12345678", "abcdefgh", "a" * 33, "Passw0rd!" * 10],
    )
    async def test_invalid_password_rejected(self, client: httpx.AsyncClient, password: str) -> None:
        """DoD：password 需 8-32 位且含字母数字。"""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "target": _unique_phone(),
                "verify_code": "123456",
                "password": password,
            },
        )
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == ErrorCode.VALIDATION_FAILED
        assert any("password" in e["field"] for e in body["data"]["errors"])

    @pytest.mark.parametrize(
        "target", ["", "12345", "abc", "a@b", "not-an-email", "123456789012"]
    )
    async def test_invalid_target_rejected(self, client: httpx.AsyncClient, target: str) -> None:
        """边界异常：target 格式非法 → 400。"""
        response = await client.post(
            "/api/v1/auth/register",
            json={"target": target, "verify_code": "123456", "password": "Passw0rd"},
        )
        assert response.status_code == 400

    async def test_code_must_be_6_digits(self, client: httpx.AsyncClient) -> None:
        for code in ["12345", "1234567", "abcdef", "12 456"]:
            response = await client.post(
                "/api/v1/auth/register",
                json={
                    "target": _unique_phone(),
                    "verify_code": code,
                    "password": "Passw0rd",
                },
            )
            assert response.status_code == 400, f"{code} 应被拒绝"

    async def test_nickname_length_limit(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "target": _unique_phone(),
                "verify_code": "123456",
                "password": "Passw0rd",
                "nickname": "x" * 51,
            },
        )
        assert response.status_code == 400

    async def test_response_has_no_password_hash(
        self, client: httpx.AsyncClient, cleanup: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DoD：响应不含 password_hash。"""
        from app.modules.account import verification

        target = _unique_phone()
        fake = _FakeRedis()
        monkeypatch.setattr(redis_infra, "get_client", lambda: fake)
        monkeypatch.setattr(verification.redis_infra, "get_client", lambda: fake)
        await fake.set(verification._code_key(VerifyScene.REGISTER, target), "123456", ex=300)

        response = await client.post(
            "/api/v1/auth/register",
            json={"target": target, "verify_code": "123456", "password": "Passw0rd"},
        )
        assert response.status_code == 201
        cleanup.append(uuid.UUID(response.json()["data"]["user_id"]))

        text = response.text.lower()
        for field in ("password_hash", "credential", "token_version", "bcrypt", "$2b$"):
            assert field not in text, f"响应泄露了 {field}"


# ============================================================
# 邮箱注册
# ============================================================


class TestEmailRegistration:
    async def test_email_target_works(
        self, client: httpx.AsyncClient, cleanup: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.account import verification

        target = _unique_email()
        fake = _FakeRedis()
        monkeypatch.setattr(redis_infra, "get_client", lambda: fake)
        monkeypatch.setattr(verification.redis_infra, "get_client", lambda: fake)
        await fake.set(verification._code_key(VerifyScene.REGISTER, target), "654321", ex=300)

        response = await client.post(
            "/api/v1/auth/register",
            json={"target": target, "verify_code": "654321", "password": "Passw0rd"},
        )
        assert response.status_code == 201
        cleanup.append(uuid.UUID(response.json()["data"]["user_id"]))


# ============================================================
# 默认昵称
# ============================================================


class TestDefaultNickname:
    def test_phone_nickname_masked(self) -> None:
        from app.modules.account.service import generate_default_nickname

        assert generate_default_nickname("13800138000") == "138***8000"

    def test_email_nickname_has_suffix(self) -> None:
        from app.modules.account.service import generate_default_nickname

        nickname = generate_default_nickname("alice@example.com")
        assert nickname.startswith("alice_")
        assert len(nickname) <= 50

    def test_username_hides_target(self) -> None:
        """username 不能暴露手机号。"""
        from app.modules.account.service import generate_unique_username

        username = generate_unique_username("13800138000")
        assert "13800138000" not in username
        assert username.startswith("u_")
        assert len(username) <= 50
