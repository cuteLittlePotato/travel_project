"""注销后重新注册的测试。

业务规则（2026-11-09 确认）：
    账号注销后，**同一邮箱/手机号可以重新注册**，得到全新账号。

为什么需要专门处理：
    ``oauth_binding`` 有 ``uk_oauth_provider_uid (provider, provider_uid)``
    唯一约束。注销时若不释放标识，该邮箱会被永久占用——用户想重新注册
    会被「已注册」挡住，而他自己不知道原因。

设计取舍：
    新账号与旧账号是**两个独立账号**，旧账号的匿名化足迹不会关联过去。
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


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
            pytest.skip("表未创建")


@pytest.fixture
async def client(db_ready: None) -> httpx.AsyncClient:
    from app.main import create_app

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    )


@pytest.fixture
async def emails() -> Any:
    """记录本次测试创建的邮箱，结束后彻底清理。"""
    created: list[str] = []

    async def _new() -> str:
        email = f"rejoin_{uuid.uuid4().hex[:10]}@example.com"
        created.append(email)
        return email

    yield _new

    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        for email in created:
            # 可能有多个账号用同一邮箱（注销的 + 重新注册的）
            result = await session.execute(
                text(
                    "SELECT user_id FROM oauth_binding "
                    "WHERE provider_uid = :email OR provider_uid LIKE :prefix"
                ),
                {"email": email, "prefix": f"deleted_%{email[:4]}%"},
            )
            user_ids = [row[0] for row in result.all()]
            for uid in user_ids:
                for table in ("user_setting", "user_profile", "oauth_binding"):
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE user_id = :uid"),
                        {"uid": uid},
                    )
                await session.execute(
                    text('DELETE FROM "user" WHERE id = :uid'), {"uid": uid}
                )
        await session.commit()


async def _register(client: httpx.AsyncClient, email: str) -> dict:
    """走完整注册流程。"""
    from app.infra import redis
    from app.modules.account import verification

    await redis.get_client().set(
        verification._code_key(verification.VerifyScene.REGISTER, email),
        "123456",
        ex=300,
    )
    response = await client.post(
        "/api/v1/auth/register",
        json={"target": email, "verify_code": "123456"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _set_password(user_id: str, password: str) -> None:
    from app.core.security import hash_password
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        await session.execute(
            text("UPDATE oauth_binding SET credential = :h WHERE user_id = :uid"),
            {"h": hash_password(password), "uid": user_id},
        )
        await session.commit()


async def _deactivate(client: httpx.AsyncClient, user_id: str, password: str) -> int:
    from app.core.security import create_access_token

    token = create_access_token(user_id, user_type="user", token_version=0)
    response = await client.post(
        "/api/v1/users/me/deactivate",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": password, "confirmation": "注销"},
    )
    return response.status_code


class TestRejoinAfterDeactivation:
    async def test_email_released_on_deactivation(
        self, client: httpx.AsyncClient, emails: Any
    ) -> None:
        """注销后原邮箱不再被占用。"""
        from app.db.session import SessionLocal

        email = await emails()
        account = await _register(client, email)
        await _set_password(account["user_id"], "Passw0rd1")

        assert await _deactivate(client, account["user_id"], "Passw0rd1") == 204

        async with SessionLocal() as session:
            result = await session.execute(
                text(
                    "SELECT provider_uid FROM oauth_binding WHERE user_id = :uid"
                ),
                {"uid": account["user_id"]},
            )
            new_identifier = result.scalar_one()

        # 原邮箱已被改写为匿名值
        assert new_identifier != email
        assert new_identifier.startswith("deleted_")

    async def test_can_register_again_with_same_email(
        self, client: httpx.AsyncClient, emails: Any
    ) -> None:
        """**DoD：注销后可用同一邮箱重新注册。**"""
        email = await emails()
        first = await _register(client, email)
        await _set_password(first["user_id"], "Passw0rd1")
        await _deactivate(client, first["user_id"], "Passw0rd1")

        # 重新注册
        second = await _register(client, email)

        assert second["user_id"] != first["user_id"], "应是全新账号"

    async def test_new_account_has_no_password(
        self, client: httpx.AsyncClient, emails: Any
    ) -> None:
        """新账号同样不继承旧密码（注册不设密码）。"""
        email = await emails()
        first = await _register(client, email)
        await _set_password(first["user_id"], "OldPassw0rd")
        await _deactivate(client, first["user_id"], "OldPassw0rd")

        await _register(client, email)

        # 用旧密码登录应失败（未设置密码）
        login = await client.post(
            "/api/v1/auth/login",
            json={"target": email, "password": "OldPassw0rd"},
        )
        assert login.status_code == 401
        assert login.json()["code"] == 11013

    async def test_new_account_can_code_login(
        self, client: httpx.AsyncClient, emails: Any
    ) -> None:
        email = await emails()
        first = await _register(client, email)
        await _set_password(first["user_id"], "Passw0rd1")
        await _deactivate(client, first["user_id"], "Passw0rd1")

        await _register(client, email)

        from app.infra import redis
        from app.modules.account import verification

        await redis.get_client().set(
            verification._code_key(verification.VerifyScene.LOGIN, email),
            "123456",
            ex=300,
        )
        login = await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": email, "verify_code": "123456"},
        )

        assert login.status_code == 200
        assert login.json()["data"]["access_token"]

    async def test_old_account_data_not_linked(
        self, client: httpx.AsyncClient, emails: Any
    ) -> None:
        """旧账号的匿名化记录保留，但不会关联到新账号。"""
        from app.db.session import SessionLocal

        email = await emails()
        first = await _register(client, email)
        first_user_id = first["user_id"]
        await _set_password(first_user_id, "Passw0rd1")
        await _deactivate(client, first_user_id, "Passw0rd1")

        second = await _register(client, email)

        async with SessionLocal() as session:
            # 旧账号仍在，状态 deleted
            old = await session.execute(
                text('SELECT status, nickname FROM "user" WHERE id = :uid'),
                {"uid": first_user_id},
            )
            old_status, old_nickname = old.one()
            assert old_status == "deleted"
            assert old_nickname == "已注销用户"

            # 新账号 active，与旧账号是两个不同的 user
            new = await session.execute(
                text('SELECT status FROM "user" WHERE id = :uid'),
                {"uid": second["user_id"]},
            )
            assert new.scalar_one() == "active"
            assert second["user_id"] != first_user_id

    async def test_duplicate_registration_still_rejected_while_active(
        self, client: httpx.AsyncClient, emails: Any
    ) -> None:
        """未注销时重复注册仍然被拒——只释放已注销的标识。"""
        email = await emails()
        await _register(client, email)

        from app.infra import redis
        from app.modules.account import verification

        await redis.get_client().set(
            verification._code_key(verification.VerifyScene.REGISTER, email),
            "123456",
            ex=300,
        )
        response = await client.post(
            "/api/v1/auth/register",
            json={"target": email, "verify_code": "123456"},
        )

        assert response.status_code == 409
        assert response.json()["code"] == 11003

    async def test_multiple_rejoins(
        self, client: httpx.AsyncClient, emails: Any
    ) -> None:
        """反复注销再注册不会因为唯一约束失败。"""
        email = await emails()

        for _ in range(3):
            account = await _register(client, email)
            await _set_password(account["user_id"], "Passw0rd1")
            assert await _deactivate(client, account["user_id"], "Passw0rd1") == 204


# ============================================================
# 验证码登录遇到已注销账号
# ============================================================


class TestCodeLoginAfterDeactivation:
    """按钮写着「登录 / 注册」，用户点它就该得到其中一个结果。

    已注销账号既登不进去、又被唯一约束挡着注册不了——是死路。
    验证码登录应释放旧标识并自动创建新账号。
    """

    async def test_code_login_creates_new_account(
        self, client: httpx.AsyncClient, emails: Any
    ) -> None:
        from app.db.session import SessionLocal

        email = await emails()
        first = await _register(client, email)
        await _set_password(first["user_id"], "Passw0rd1")
        await _deactivate(client, first["user_id"], "Passw0rd1")

        # 手工把标识改回原邮箱，模拟「修复前注销的历史数据」
        async with SessionLocal() as session:
            await session.execute(
                text(
                    "UPDATE oauth_binding SET provider_uid = :email "
                    "WHERE user_id = :uid"
                ),
                {"email": email, "uid": first["user_id"]},
            )
            await session.commit()

        from app.infra import redis
        from app.modules.account import verification

        await redis.get_client().set(
            verification._code_key(verification.VerifyScene.LOGIN, email),
            "123456",
            ex=300,
        )
        response = await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": email, "verify_code": "123456"},
        )

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["is_new_user"] is True, "应创建全新账号"
        assert data["user_id"] != first["user_id"]

    async def test_old_account_stays_deleted(
        self, client: httpx.AsyncClient, emails: Any
    ) -> None:
        """旧账号仍是 deleted 状态，不会被「复活」。"""
        from app.db.session import SessionLocal

        email = await emails()
        first = await _register(client, email)
        await _set_password(first["user_id"], "Passw0rd1")
        await _deactivate(client, first["user_id"], "Passw0rd1")

        async with SessionLocal() as session:
            await session.execute(
                text(
                    "UPDATE oauth_binding SET provider_uid = :email "
                    "WHERE user_id = :uid"
                ),
                {"email": email, "uid": first["user_id"]},
            )
            await session.commit()

        from app.infra import redis
        from app.modules.account import verification

        await redis.get_client().set(
            verification._code_key(verification.VerifyScene.LOGIN, email),
            "123456",
            ex=300,
        )
        await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": email, "verify_code": "123456"},
        )

        async with SessionLocal() as session:
            result = await session.execute(
                text('SELECT status, nickname FROM "user" WHERE id = :uid'),
                {"uid": first["user_id"]},
            )
            status, nickname = result.one()

        assert status == "deleted"
        assert nickname == "已注销用户"

    async def test_normal_code_login_unaffected(
        self, client: httpx.AsyncClient, emails: Any
    ) -> None:
        """正常情况下仍走「已存在则登录」，不会每次都重建账号。"""
        email = await emails()
        first = await _register(client, email)

        from app.infra import redis
        from app.modules.account import verification

        await redis.get_client().set(
            verification._code_key(verification.VerifyScene.LOGIN, email),
            "123456",
            ex=300,
        )
        response = await client.post(
            "/api/v1/auth/login-by-code",
            json={"target": email, "verify_code": "123456"},
        )

        assert response.status_code == 200
        assert response.json()["data"]["is_new_user"] is False
        assert response.json()["data"]["user_id"] == first["user_id"]
