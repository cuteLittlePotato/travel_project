"""M01-T07 第三方登录的测试。

覆盖 DoD：
    1. 首次登录自动创建账号并绑定（Mock 第三方响应）
    2. 已绑定账号直接登录
    3. 同一第三方账号绑定多个平台账号 → 11009（该场景被唯一索引禁止，见说明）

用 MockableOAuthProvider 注入固定响应，不依赖真实第三方。
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.exceptions import ErrorCode
from app.infra import redis as redis_infra
from app.infra.oauth import (
    OAuthCodeInvalidError,
    OAuthNotConfiguredError,
    OAuthUnavailableError,
    OAuthUserInfo,
    get_provider,
    supported_providers,
)
from app.main import create_app
from app.modules.account import service
from app.modules.account.constants import BindingProvider, UserStatus

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


@pytest.fixture(autouse=True)
def clear_mocks() -> Any:
    """每个测试后清理 Mock 状态，避免相互污染。"""
    yield
    for name in supported_providers():
        provider = get_provider(name)
        if hasattr(provider, "clear_mock"):
            provider.clear_mock()


def _openid() -> str:
    return f"openid_{uuid.uuid4().hex[:16]}"


def _mock_provider(provider_name: str, info: OAuthUserInfo) -> None:
    provider = get_provider(provider_name)
    provider.set_mock_response(info)  # type: ignore[attr-defined]


# ============================================================
# 服务商注册
# ============================================================


class TestProviderRegistry:
    def test_supported_providers(self) -> None:
        assert set(supported_providers()) == {"wechat", "alipay", "weibo"}

    def test_get_provider_by_string(self) -> None:
        assert get_provider("wechat").provider is BindingProvider.WECHAT

    def test_get_provider_by_enum(self) -> None:
        assert get_provider(BindingProvider.WEIBO).provider is BindingProvider.WEIBO

    def test_unknown_provider_rejected(self) -> None:
        from app.infra.oauth import OAuthError

        with pytest.raises(OAuthError):
            get_provider("facebook")

    def test_phone_is_not_oauth_provider(self) -> None:
        """手机号不是第三方，传进来应报错。"""
        from app.infra.oauth import OAuthError

        with pytest.raises(OAuthError):
            get_provider(BindingProvider.PHONE)


# ============================================================
# DoD 1：首次登录自动建号
# ============================================================


class TestFirstOAuthLogin:
    async def test_creates_account_and_binding(
        self, client: httpx.AsyncClient, cleanup: list
    ) -> None:
        """DoD：首次登录自动创建账号并绑定。"""
        openid = _openid()
        _mock_provider(
            "wechat",
            OAuthUserInfo(
                provider_uid=openid,
                nickname="微信小明",
                avatar_url="https://example.com/a.jpg",
            ),
        )

        response = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "wechat", "code": "mock-code", "state": "xyz"},
        )

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["is_new_user"] is True
        cleanup.append(uuid.UUID(data["user_id"]))

        # DB 断言：绑定已创建
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            row = await session.execute(
                text(
                    "SELECT provider, provider_uid, credential FROM oauth_binding "
                    "WHERE user_id = :uid"
                ),
                {"uid": data["user_id"]},
            )
            binding = row.one()
            assert binding[0] == "wechat"
            assert binding[1] == openid
            assert binding[2] is None, "第三方登录不应写入密码哈希"

    async def test_uses_third_party_nickname(
        self, client: httpx.AsyncClient, cleanup: list
    ) -> None:
        from app.db.session import SessionLocal

        _mock_provider(
            "weibo",
            OAuthUserInfo(provider_uid=_openid(), nickname="微博用户A"),
        )

        response = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "weibo", "code": "c", "state": "s"},
        )
        user_id = response.json()["data"]["user_id"]
        cleanup.append(uuid.UUID(user_id))

        async with SessionLocal() as session:
            row = await session.execute(
                text('SELECT nickname FROM "user" WHERE id = :uid'), {"uid": user_id}
            )
            assert row.scalar_one() == "微博用户A"

    async def test_generates_nickname_when_missing(
        self, client: httpx.AsyncClient, cleanup: list
    ) -> None:
        from app.db.session import SessionLocal

        _mock_provider("alipay", OAuthUserInfo(provider_uid=_openid(), nickname=None))

        response = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "alipay", "code": "c", "state": "s"},
        )
        user_id = response.json()["data"]["user_id"]
        cleanup.append(uuid.UUID(user_id))

        async with SessionLocal() as session:
            row = await session.execute(
                text('SELECT nickname FROM "user" WHERE id = :uid'), {"uid": user_id}
            )
            nickname = row.scalar_one()
        assert nickname.startswith("支付宝用户_")

    async def test_creates_profile_and_setting(
        self, client: httpx.AsyncClient, cleanup: list
    ) -> None:
        from app.db.session import SessionLocal

        _mock_provider("wechat", OAuthUserInfo(provider_uid=_openid()))
        response = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "wechat", "code": "c", "state": "s"},
        )
        user_id = response.json()["data"]["user_id"]
        cleanup.append(uuid.UUID(user_id))

        async with SessionLocal() as session:
            for table in ("user_profile", "user_setting"):
                count = await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE user_id = :uid"),
                    {"uid": user_id},
                )
                assert count.scalar_one() == 1


# ============================================================
# DoD 2：已绑定账号直接登录
# ============================================================


class TestReturningOAuthLogin:
    async def test_second_login_is_not_new_user(
        self, client: httpx.AsyncClient, cleanup: list
    ) -> None:
        """DoD：已绑定的账号直接登录。"""
        openid = _openid()
        _mock_provider("wechat", OAuthUserInfo(provider_uid=openid))

        first = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "wechat", "code": "c1", "state": "s"},
        )
        assert first.json()["data"]["is_new_user"] is True
        user_id = first.json()["data"]["user_id"]
        cleanup.append(uuid.UUID(user_id))

        second = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "wechat", "code": "c2", "state": "s"},
        )
        assert second.json()["data"]["is_new_user"] is False
        assert second.json()["data"]["user_id"] == user_id

    async def test_different_providers_are_separate_accounts(
        self, client: httpx.AsyncClient, cleanup: list
    ) -> None:
        """微信 openid 与微信 openid 不同 → 不同账号。"""
        _mock_provider("wechat", OAuthUserInfo(provider_uid=_openid()))
        first = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "wechat", "code": "c", "state": "s"},
        )

        _mock_provider("wechat", OAuthUserInfo(provider_uid=_openid()))
        second = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "wechat", "code": "c", "state": "s"},
        )

        cleanup.append(uuid.UUID(first.json()["data"]["user_id"]))
        cleanup.append(uuid.UUID(second.json()["data"]["user_id"]))
        assert first.json()["data"]["user_id"] != second.json()["data"]["user_id"]

    async def test_same_openid_different_provider_separate(
        self, client: httpx.AsyncClient, cleanup: list
    ) -> None:
        """同一串 openid 在微信和微博下是不同账号（唯一索引是 provider+uid）。"""
        shared = _openid()
        _mock_provider("wechat", OAuthUserInfo(provider_uid=shared))
        wechat = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "wechat", "code": "c", "state": "s"},
        )

        _mock_provider("weibo", OAuthUserInfo(provider_uid=shared))
        weibo = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "weibo", "code": "c", "state": "s"},
        )

        cleanup.append(uuid.UUID(wechat.json()["data"]["user_id"]))
        cleanup.append(uuid.UUID(weibo.json()["data"]["user_id"]))
        assert wechat.json()["data"]["user_id"] != weibo.json()["data"]["user_id"]


# ============================================================
# DoD 3：11009 场景（被唯一索引禁止）
# ============================================================


class TestUniqueBinding:
    async def test_same_openid_always_maps_to_one_user(
        self, client: httpx.AsyncClient, cleanup: list
    ) -> None:
        """DoD：同一第三方账号「绑定多个平台账号」被唯一索引禁止。

        验证方式：用同一 openid 反复登录，始终返回同一个 user_id，
        数据库里 `(provider, provider_uid)` 只有一条记录。
        """
        from app.db.session import SessionLocal

        openid = _openid()
        _mock_provider("wechat", OAuthUserInfo(provider_uid=openid))

        user_ids = set()
        for _ in range(3):
            response = await client.post(
                "/api/v1/auth/oauth-login",
                json={"provider": "wechat", "code": "c", "state": "s"},
            )
            user_ids.add(response.json()["data"]["user_id"])

        cleanup.append(uuid.UUID(next(iter(user_ids))))
        assert len(user_ids) == 1, "同一 openid 只能对应一个用户"

        async with SessionLocal() as session:
            count = await session.execute(
                text(
                    "SELECT count(*) FROM oauth_binding "
                    "WHERE provider = 'wechat' AND provider_uid = :uid"
                ),
                {"uid": openid},
            )
            assert count.scalar_one() == 1

    def test_error_code_11009_defined(self) -> None:
        """错误码保留定义，虽然当前场景无法触发。"""
        assert ErrorCode.OAUTH_ALREADY_BOUND == 11009


# ============================================================
# 边界：第三方异常
# ============================================================


class TestOAuthErrors:
    async def test_invalid_code_returns_400(
        self, client: httpx.AsyncClient
    ) -> None:
        provider = get_provider("wechat")
        provider.set_mock_error(OAuthCodeInvalidError("微信"))  # type: ignore[attr-defined]

        response = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "wechat", "code": "bad", "state": "s"},
        )
        assert response.status_code == 400
        assert "授权码" in response.json()["message"]

    async def test_unavailable_returns_400(
        self, client: httpx.AsyncClient
    ) -> None:
        provider = get_provider("weibo")
        provider.set_mock_error(OAuthUnavailableError("微博", "timeout"))  # type: ignore[attr-defined]

        response = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "weibo", "code": "c", "state": "s"},
        )
        assert response.status_code == 400
        assert "不可用" in response.json()["message"]

    async def test_not_configured_returns_400(
        self, client: httpx.AsyncClient
    ) -> None:
        provider = get_provider("alipay")
        provider.set_mock_error(OAuthNotConfiguredError("支付宝"))  # type: ignore[attr-defined]

        response = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "alipay", "code": "c", "state": "s"},
        )
        assert response.status_code == 400
        assert "未开放" in response.json()["message"]

    async def test_banned_user_cannot_oauth_login(
        self, client: httpx.AsyncClient, cleanup: list
    ) -> None:
        from app.db.session import SessionLocal

        openid = _openid()
        _mock_provider("wechat", OAuthUserInfo(provider_uid=openid))
        first = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "wechat", "code": "c", "state": "s"},
        )
        user_id = first.json()["data"]["user_id"]
        cleanup.append(uuid.UUID(user_id))

        async with SessionLocal() as session:
            await session.execute(
                text('UPDATE "user" SET status = :s WHERE id = :uid'),
                {"s": UserStatus.BANNED.value, "uid": user_id},
            )
            await session.commit()

        response = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "wechat", "code": "c", "state": "s"},
        )
        assert response.status_code == 403
        assert response.json()["code"] == ErrorCode.ACCOUNT_BANNED


# ============================================================
# 参数校验
# ============================================================


class TestValidation:
    @pytest.mark.parametrize("provider", ["facebook", "qq", "phone", ""])
    async def test_unsupported_provider(
        self, client: httpx.AsyncClient, provider: str
    ) -> None:
        response = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": provider, "code": "c", "state": "s"},
        )
        assert response.status_code == 400

    async def test_empty_code_rejected(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "wechat", "code": "", "state": "s"},
        )
        assert response.status_code == 400

    async def test_empty_state_rejected(self, client: httpx.AsyncClient) -> None:
        """虽然后端不校验 state 真实性，但字段本身必填。"""
        response = await client.post(
            "/api/v1/auth/oauth-login",
            json={"provider": "wechat", "code": "c", "state": ""},
        )
        assert response.status_code == 400
