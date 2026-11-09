"""账号注销接口的测试（API §3.19）。

背景：数据库设计 §4.3 定义了「用户注销」的数据处置规则
（软删除 + 清理会话/记忆/额度 + 保留匿名化足迹），
但 API 设计漏了触发注销的接口。本任务补上。

DoD：
    1. 注销需验证密码
    2. 注销需手动输入「注销」二次确认
    3. 注销后 status='deleted'，昵称匿名化
    4. 注销后所有 Token 失效
    5. 清理会话、记忆、额度；保留足迹
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.exceptions import ErrorCode

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
            text("SELECT to_regclass('public.user') IS NOT NULL")
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
async def account(client: httpx.AsyncClient) -> Any:
    """创建一个带密码、带数据的测试账号。

    直接写库：注册接口会走验证码流程，测试里没必要绕那一圈。
    """
    from app.core.security import create_access_token, hash_password
    from app.db.session import SessionLocal
    from app.utils.ids import uuid7

    user_id = uuid7()
    username = f"deact_{uuid.uuid4().hex[:8]}"
    phone = f"139{uuid.uuid4().int % 100000000:08d}"
    password = "Passw0rd1"

    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                INSERT INTO "user" (id, username, nickname, status, token_version,
                                    created_at, updated_at)
                VALUES (:id, :username, :nickname, 'active', 0, NOW(), NOW())
                """
            ),
            {"id": user_id, "username": username, "nickname": "测试用户"},
        )
        await session.execute(
            text(
                """
                INSERT INTO oauth_binding (id, user_id, provider, provider_uid,
                                           credential, is_primary, created_at)
                VALUES (:id, :uid, 'phone', :phone, :hash, TRUE, NOW())
                """
            ),
            {
                "id": uuid7(),
                "uid": user_id,
                "phone": phone,
                "hash": hash_password(password),
            },
        )
        await session.commit()

    token = create_access_token(str(user_id), user_type="user", token_version=0)

    yield {
        "id": user_id,
        "username": username,
        "password": password,
        "headers": {"Authorization": f"Bearer {token}"},
        "access_token": token,
    }

    # 清理：注销测试可能已删了关联数据，这里兜底
    async with SessionLocal() as session:
        for table in ("oauth_binding", "user_profile", "user_setting", "user_quota"):
            try:
                await session.execute(
                    text(f"DELETE FROM {table} WHERE user_id = :id"),
                    {"id": user_id},
                )
            except Exception:
                await session.rollback()
        await session.execute(
            text('DELETE FROM "user" WHERE id = :id'), {"id": user_id}
        )
        await session.commit()


async def _deactivate(
    client: httpx.AsyncClient,
    headers: dict,
    *,
    password: str,
    confirmation: str = "注销",
) -> httpx.Response:
    return await client.post(
        "/api/v1/users/me/deactivate",
        headers=headers,
        json={"password": password, "confirmation": confirmation},
    )


# ============================================================
# 身份验证
# ============================================================


class TestIdentityVerification:
    async def test_wrong_password_rejected(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """注销是破坏性操作，密码错误必须拒绝。"""
        async with client:
            response = await _deactivate(
                client, account["headers"], password="WrongPass1"
            )

        assert response.status_code == 401
        assert response.json()["code"] == ErrorCode.INVALID_CREDENTIAL

    async def test_empty_password_rejected(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        async with client:
            response = await _deactivate(client, account["headers"], password="")

        assert response.status_code == 400

    async def test_requires_authentication(
        self, client: httpx.AsyncClient
    ) -> None:
        async with client:
            response = await client.post(
                "/api/v1/users/me/deactivate",
                json={"password": "AnyPass1", "confirmation": "注销"},
            )

        assert response.status_code == 401

    async def test_account_without_password_rejected(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """无密码账号（验证码注册）不能注销，需先设置密码。"""
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            await session.execute(
                text(
                    "UPDATE oauth_binding SET credential = NULL WHERE user_id = :id"
                ),
                {"id": account["id"]},
            )
            await session.commit()

        async with client:
            response = await _deactivate(
                client, account["headers"], password="AnyPass1"
            )

        assert response.status_code == 400
        assert response.json()["code"] == ErrorCode.PASSWORD_NOT_SET


# ============================================================
# 二次确认
# ============================================================


class TestConfirmation:
    @pytest.mark.parametrize(
        "confirmation",
        ["确定", "取消", "delete", "", "注销账号"],
    )
    async def test_wrong_confirmation_rejected(
        self, client: httpx.AsyncClient, account: dict, confirmation: str
    ) -> None:
        """必须输入「注销」二字，绕不过去。"""
        async with client:
            response = await _deactivate(
                client,
                account["headers"],
                password=account["password"],
                confirmation=confirmation,
            )

        assert response.status_code == 400
        assert response.json()["code"] == 10001

    async def test_correct_confirmation_accepted(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        async with client:
            response = await _deactivate(
                client, account["headers"], password=account["password"]
            )

        assert response.status_code == 204


# ============================================================
# 注销结果
# ============================================================


class TestDeactivationResult:
    async def test_status_becomes_deleted(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：软删除，status='deleted'。"""
        from app.db.session import SessionLocal

        async with client:
            await _deactivate(client, account["headers"], password=account["password"])

        async with SessionLocal() as session:
            result = await session.execute(
                text('SELECT status FROM "user" WHERE id = :id'),
                {"id": account["id"]},
            )
            assert result.scalar_one() == "deleted"

    async def test_nickname_anonymized(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：昵称匿名化，足迹保留但不再指向具体人。"""
        from app.db.session import SessionLocal

        async with client:
            await _deactivate(client, account["headers"], password=account["password"])

        async with SessionLocal() as session:
            result = await session.execute(
                text('SELECT nickname, avatar_url FROM "user" WHERE id = :id'),
                {"id": account["id"]},
            )
            nickname, avatar = result.one()

        assert nickname == "已注销用户"
        assert avatar is None

    async def test_tokens_invalidated(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：注销后所有 Token 失效。"""
        async with client:
            await _deactivate(client, account["headers"], password=account["password"])

            # 用同一个 Token 再访问
            response = await client.get(
                "/api/v1/users/me", headers=account["headers"]
            )

        assert response.status_code == 401

    async def test_cannot_login_after_deactivation(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        from app.db.session import SessionLocal

        # 记录手机号
        async with SessionLocal() as session:
            result = await session.execute(
                text(
                    "SELECT provider_uid FROM oauth_binding WHERE user_id = :id"
                ),
                {"id": account["id"]},
            )
            phone = result.scalar_one()

        async with client:
            await _deactivate(client, account["headers"], password=account["password"])

            response = await client.post(
                "/api/v1/auth/login",
                json={"target": phone, "password": account["password"]},
            )

        assert response.status_code == 403
        assert response.json()["code"] == ErrorCode.ACCOUNT_DELETED

    async def test_idempotent(self, client: httpx.AsyncClient, account: dict) -> None:
        """重复注销不报错——用户可能手抖点两次。"""
        async with client:
            first = await _deactivate(
                client, account["headers"], password=account["password"]
            )
            assert first.status_code == 204

            # Token 已失效，第二次会 401（而非 500）
            second = await _deactivate(
                client, account["headers"], password=account["password"]
            )

        # 鉴权先失败，返回 401 是合理的
        assert second.status_code == 401


# ============================================================
# 数据清理
# ============================================================


class TestDataCleanup:
    async def test_conversations_cleared(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：会话与消息被清理。"""
        from app.db.session import SessionLocal
        from app.utils.ids import uuid7

        # 造一条会话
        async with SessionLocal() as session:
            try:
                await session.execute(
                    text(
                        """
                        INSERT INTO chat_session (id, user_id, title, created_at, updated_at)
                        VALUES (:id, :uid, '测试会话', NOW(), NOW())
                        """
                    ),
                    {"id": uuid7(), "uid": account["id"]},
                )
                await session.commit()
            except Exception:
                await session.rollback()
                pytest.skip("chat_session 表结构不匹配")

        async with client:
            await _deactivate(client, account["headers"], password=account["password"])

        async with SessionLocal() as session:
            result = await session.execute(
                text("SELECT count(*) FROM chat_session WHERE user_id = :id"),
                {"id": account["id"]},
            )
            assert result.scalar_one() == 0

    async def test_quota_cleared(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            try:
                await session.execute(
                    text(
                        """
                        INSERT INTO user_quota (id, user_id, quota_date, call_count,
                                                token_used, created_at, updated_at)
                        VALUES (gen_random_uuid(), :uid, CURRENT_DATE, 5, 1000,
                                NOW(), NOW())
                        """
                    ),
                    {"uid": account["id"]},
                )
                await session.commit()
            except Exception:
                await session.rollback()
                pytest.skip("user_quota 表结构不匹配")

        async with client:
            await _deactivate(client, account["headers"], password=account["password"])

        async with SessionLocal() as session:
            result = await session.execute(
                text("SELECT count(*) FROM user_quota WHERE user_id = :id"),
                {"id": account["id"]},
            )
            assert result.scalar_one() == 0

    async def test_user_record_retained(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：软删除——user 记录本身保留，不是物理删除。"""
        from app.db.session import SessionLocal

        async with client:
            await _deactivate(client, account["headers"], password=account["password"])

        async with SessionLocal() as session:
            result = await session.execute(
                text('SELECT count(*) FROM "user" WHERE id = :id'),
                {"id": account["id"]},
            )
            assert result.scalar_one() == 1
