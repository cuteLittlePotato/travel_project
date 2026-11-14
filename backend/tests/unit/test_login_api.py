"""M01-T05 密码登录接口的测试。

覆盖 DoD：
    1. 正确凭据返回 200 + 双 Token
    2. 账号不存在 11005、密码错误 11006
    3. 封禁 11002、注销 11007
    4. 连续 5 次错误锁定 15 分钟 → 11008

安全约定（2026-11-08 确认）：「账号不存在」与「密码错误」的 message
和 HTTP 状态码必须一致，只有业务码不同。
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
from app.modules.account import service
from app.modules.account.constants import LOGIN_FAIL_LIMIT, UserStatus

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
async def user_factory(db_ready: None, fake_redis: _FakeRedis) -> Any:
    """创建测试用户：注册 -> 返回 (target, password, user_id)。"""
    from app.modules.account import verification

    created: list[uuid.UUID] = []

    async def _create(
        *,
        password: str = "Passw0rd",
        status: str = UserStatus.ACTIVE.value,
        with_password: bool = True,
        target: str | None = None,
    ) -> dict[str, Any]:
        phone = target or f"139{uuid.uuid4().int % 100000000:08d}"
        await fake_redis.set(
            verification._code_key(
                verification.VerifyScene.REGISTER, phone
            ),
            "123456",
            ex=300,
        )
        # 直接调 service，避免依赖 HTTP 层
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            # 注册不设密码（需求 2.1.1），需要密码的用例在下面单独设置
            result = await service.register(
                session,
                target=phone,
                verify_code_str="123456",
            )
        created.append(result.user_id)

        if with_password:
            # 模拟用户注册后在个人中心设置了密码
            from app.core.security import hash_password

            async with SessionLocal() as session:
                await session.execute(
                    text(
                        "UPDATE oauth_binding SET credential = :h "
                        "WHERE user_id = :uid"
                    ),
                    {"h": hash_password(password), "uid": result.user_id},
                )
                await session.commit()

        if status != UserStatus.ACTIVE.value or not with_password:
            async with SessionLocal() as session:
                if status != UserStatus.ACTIVE.value:
                    await session.execute(
                        text('UPDATE "user" SET status = :s WHERE id = :uid'),
                        {"s": status, "uid": result.user_id},
                    )
                if not with_password:
                    await session.execute(
                        text(
                            "UPDATE oauth_binding SET credential = NULL "
                            "WHERE user_id = :uid"
                        ),
                        {"uid": result.user_id},
                    )
                await session.commit()

        return {
            "target": phone,
            "password": password,
            "user_id": result.user_id,
        }

    yield _create

    # 清理
    if created:
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            for uid in created:
                for table in ("user_setting", "user_profile", "oauth_binding"):
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE user_id = :uid"), {"uid": uid}
                    )
                await session.execute(
                    text('DELETE FROM "user" WHERE id = :uid'), {"uid": uid}
                )
            await session.commit()


# ============================================================
# DoD 1：登录成功
# ============================================================


class TestLoginSuccess:
    async def test_returns_200_with_tokens(
        self, client: httpx.AsyncClient, user_factory: Any
    ) -> None:
        account = await user_factory()

        response = await client.post(
            "/api/v1/auth/login",
            json={"target": account["target"], "password": account["password"]},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["code"] == 0
        data = body["data"]
        assert set(data) >= {"user_id", "access_token", "refresh_token", "expires_in"}
        assert data["user_id"] == str(account["user_id"])

    async def test_login_by_email(
        self, client: httpx.AsyncClient, user_factory: Any
    ) -> None:
        email = f"u{uuid.uuid4().hex[:10]}@example.com"
        account = await user_factory(target=email)

        response = await client.post(
            "/api/v1/auth/login",
            json={"target": email, "password": account["password"]},
        )
        assert response.status_code == 200

    async def test_login_by_username(
        self, client: httpx.AsyncClient, user_factory: Any
    ) -> None:
        """支持用户名登录。"""
        account = await user_factory()

        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            row = await session.execute(
                text('SELECT username FROM "user" WHERE id = :uid'),
                {"uid": account["user_id"]},
            )
            username = row.scalar_one()

        response = await client.post(
            "/api/v1/auth/login",
            json={"target": username, "password": account["password"]},
        )
        assert response.status_code == 200

    async def test_refresh_cookie_set(
        self, client: httpx.AsyncClient, user_factory: Any
    ) -> None:
        from app.core.config import settings

        account = await user_factory()
        response = await client.post(
            "/api/v1/auth/login",
            json={"target": account["target"], "password": account["password"]},
        )
        cookie = response.headers.get("set-cookie", "")
        assert settings.refresh_cookie_name in cookie
        assert "HttpOnly" in cookie

    async def test_success_clears_fail_count(
        self, client: httpx.AsyncClient, user_factory: Any
    ) -> None:
        account = await user_factory()
        # 先失败 2 次
        for _ in range(2):
            await client.post(
                "/api/v1/auth/login",
                json={"target": account["target"], "password": "WrongPass1"},
            )
        assert await service.get_login_fail_count(account["target"]) == 2

        # 登录成功
        response = await client.post(
            "/api/v1/auth/login",
            json={"target": account["target"], "password": account["password"]},
        )
        assert response.status_code == 200
        assert await service.get_login_fail_count(account["target"]) == 0


# ============================================================
# DoD 2：账号不存在 / 密码错误
# ============================================================


class TestCredentialErrors:
    async def test_nonexistent_account_returns_11005(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/auth/login",
            json={"target": f"139{uuid.uuid4().int % 100000000:08d}", "password": "AnyPass1"},
        )
        assert response.json()["code"] == ErrorCode.ACCOUNT_NOT_FOUND == 11005

    async def test_wrong_password_returns_11006(
        self, client: httpx.AsyncClient, user_factory: Any
    ) -> None:
        account = await user_factory()
        response = await client.post(
            "/api/v1/auth/login",
            json={"target": account["target"], "password": "WrongPass1"},
        )
        assert response.json()["code"] == ErrorCode.INVALID_CREDENTIAL == 11006

    async def test_account_without_password_returns_11013(
        self, client: httpx.AsyncClient, user_factory: Any
    ) -> None:
        """验证码注册的账号没有密码，用密码登录应给出可执行的指引。

        报「密码错误」在这里是误导——用户从来没有设置过密码，
        无论输什么都登不上，而且他不会知道原因。
        """
        account = await user_factory(with_password=False)

        response = await client.post(
            "/api/v1/auth/login",
            json={"target": account["target"], "password": "AnyPass1"},
        )

        assert response.status_code == 401
        assert response.json()["code"] == ErrorCode.PASSWORD_NOT_SET == 11013
        assert "验证码登录" in response.json()["message"]

    async def test_password_not_set_distinguishable_from_wrong_password(
        self, client: httpx.AsyncClient, user_factory: Any
    ) -> None:
        """两种失败原因必须用不同错误码——前端据此给不同指引。"""
        no_password = await user_factory(with_password=False)
        wrong_password = await user_factory()

        r1 = await client.post(
            "/api/v1/auth/login",
            json={"target": no_password["target"], "password": "AnyPass1"},
        )
        r2 = await client.post(
            "/api/v1/auth/login",
            json={"target": wrong_password["target"], "password": "WrongPass1"},
        )

        assert r1.json()["code"] == 11013
        assert r2.json()["code"] == 11006
        assert r1.json()["message"] != r2.json()["message"]

    async def test_messages_are_identical(
        self, client: httpx.AsyncClient, user_factory: Any
    ) -> None:
        """安全约定：两种情况 message 与 HTTP 状态码必须一致，防账号枚举。"""
        account = await user_factory()

        wrong_pwd = await client.post(
            "/api/v1/auth/login",
            json={"target": account["target"], "password": "WrongPass1"},
        )
        not_exist = await client.post(
            "/api/v1/auth/login",
            json={
                "target": f"139{uuid.uuid4().int % 100000000:08d}",
                "password": "AnyPass1",
            },
        )

        assert wrong_pwd.status_code == not_exist.status_code == 401
        assert wrong_pwd.json()["message"] == not_exist.json()["message"]
        # 只有业务码不同
        assert wrong_pwd.json()["code"] != not_exist.json()["code"]


# ============================================================
# DoD 3：封禁 / 注销
# ============================================================


class TestAccountStatus:
    async def test_banned_returns_11002(
        self, client: httpx.AsyncClient, user_factory: Any
    ) -> None:
        account = await user_factory(status=UserStatus.BANNED.value)
        response = await client.post(
            "/api/v1/auth/login",
            json={"target": account["target"], "password": account["password"]},
        )
        assert response.status_code == 403
        assert response.json()["code"] == ErrorCode.ACCOUNT_BANNED == 11002

    async def test_deleted_returns_11007(
        self, client: httpx.AsyncClient, user_factory: Any
    ) -> None:
        account = await user_factory(status=UserStatus.DELETED.value)
        response = await client.post(
            "/api/v1/auth/login",
            json={"target": account["target"], "password": account["password"]},
        )
        assert response.status_code == 403
        assert response.json()["code"] == ErrorCode.ACCOUNT_DELETED == 11007


# ============================================================
# DoD 4：登录锁定
# ============================================================


class TestLoginLock:
    async def test_five_failures_lock_account(
        self, client: httpx.AsyncClient, user_factory: Any
    ) -> None:
        """DoD：连续 5 次密码错误锁定 15 分钟，返回 11008。"""
        account = await user_factory()

        for i in range(LOGIN_FAIL_LIMIT):
            response = await client.post(
                "/api/v1/auth/login",
                json={"target": account["target"], "password": "WrongPass1"},
            )
            assert response.json()["code"] == 11006, f"第 {i + 1} 次应返回 11006"

        # 第 6 次：即使密码正确也被锁定
        response = await client.post(
            "/api/v1/auth/login",
            json={"target": account["target"], "password": account["password"]},
        )
        assert response.status_code == 429
        assert response.json()["code"] == ErrorCode.TOO_MANY_LOGIN_ATTEMPTS == 11008
        assert "retry_after" in (response.json()["data"] or {})

    async def test_lock_ttl_is_15_minutes(
        self, client: httpx.AsyncClient, user_factory: Any, fake_redis: _FakeRedis
    ) -> None:
        account = await user_factory()
        for _ in range(LOGIN_FAIL_LIMIT):
            await client.post(
                "/api/v1/auth/login",
                json={"target": account["target"], "password": "WrongPass1"},
            )

        ttl = await fake_redis.ttl(service._login_fail_key(account["target"]))
        assert 14 * 60 <= ttl <= 15 * 60

    async def test_no_password_account_cannot_login(
        self, client: httpx.AsyncClient, user_factory: Any
    ) -> None:
        """验证码自动注册的账号没有密码，密码登录应失败。

        用 11013 而非 11006：用户从没设过密码，说「密码错误」会误导。
        """
        account = await user_factory(with_password=False)
        response = await client.post(
            "/api/v1/auth/login",
            json={"target": account["target"], "password": "AnyPass1"},
        )
        assert response.json()["code"] == 11013

    async def test_different_accounts_independent(
        self, client: httpx.AsyncClient, user_factory: Any
    ) -> None:
        """锁定按 target 计，不相互影响。"""
        account_a = await user_factory()
        account_b = await user_factory()

        for _ in range(LOGIN_FAIL_LIMIT):
            await client.post(
                "/api/v1/auth/login",
                json={"target": account_a["target"], "password": "WrongPass1"},
            )

        # A 被锁
        locked = await client.post(
            "/api/v1/auth/login",
            json={"target": account_a["target"], "password": account_a["password"]},
        )
        assert locked.json()["code"] == 11008

        # B 不受影响
        ok = await client.post(
            "/api/v1/auth/login",
            json={"target": account_b["target"], "password": account_b["password"]},
        )
        assert ok.status_code == 200


# ============================================================
# 参数校验
# ============================================================


class TestValidation:
    async def test_empty_target_rejected(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/auth/login", json={"target": "", "password": "Passw0rd"}
        )
        assert response.status_code == 400

    async def test_empty_password_rejected(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/auth/login", json={"target": "13800138000", "password": ""}
        )
        assert response.status_code == 400

    async def test_missing_fields_rejected(self, client: httpx.AsyncClient) -> None:
        response = await client.post("/api/v1/auth/login", json={})
        assert response.status_code == 400


class TestPasswordNotLeaked:
    async def test_response_has_no_sensitive_fields(
        self, client: httpx.AsyncClient, user_factory: Any
    ) -> None:
        account = await user_factory()
        response = await client.post(
            "/api/v1/auth/login",
            json={"target": account["target"], "password": account["password"]},
        )
        text_body = response.text.lower()
        for field in ("password_hash", "credential", "token_version", "$2b$"):
            assert field not in text_body
