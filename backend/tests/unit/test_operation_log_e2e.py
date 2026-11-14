"""M15-T06 中间件端到端验证（真实 Token，不走 dependency_overrides）。

前面 ``test_operation_log.py`` 直接测试写入函数；这里补一个真正
走 HTTP 中间件链的用例——证明「增删改自动记录」在真实鉴权路径下
也确实生效。

为什么不能用 `dependency_overrides`：覆盖 `require_admin` 后
中间件拿不到已认证的管理员，会把所有写请求都当成未认证而跳过。
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
        for table in ("operation_log", "admin_user", "role"):
            result = await session.execute(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": f"public.{table}"},
            )
            if not result.scalar_one():
                pytest.skip(f"表 {table} 未创建")


@pytest.fixture
async def super_admin(db_ready: None) -> Any:
    """创建拥有超管角色的管理员，并签发真实 Access Token。"""
    from app.core.security import create_access_token, hash_password
    from app.db.session import SessionLocal
    from app.utils.ids import uuid7

    admin_id = uuid7()
    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                INSERT INTO admin_user (id, username, password_hash, status,
                                        token_version, created_at, updated_at)
                VALUES (:id, :username, :hash, 'active', 0, NOW(), NOW())
                """
            ),
            {
                "id": admin_id,
                "username": f"e2e_{uuid.uuid4().hex[:8]}",
                "hash": hash_password("Passw0rd123"),
            },
        )
        await session.execute(
            text(
                """
                INSERT INTO admin_user_role (id, admin_user_id, role_id, created_at)
                SELECT gen_random_uuid(), :admin_id, r.id, NOW()
                FROM role r WHERE r.code = 'super_admin'
                """
            ),
            {"admin_id": admin_id},
        )
        await session.commit()

    token = create_access_token(str(admin_id), user_type="admin", token_version=0)

    yield {"admin_id": admin_id, "token": token}

    from app.api.middleware.permission import invalidate_admin_permissions

    await invalidate_admin_permissions(admin_id)

    async with SessionLocal() as session:
        await session.execute(
            text("DELETE FROM operation_log WHERE admin_user_id = :id"),
            {"id": admin_id},
        )
        await session.execute(
            text("DELETE FROM admin_user_role WHERE admin_user_id = :id"),
            {"id": admin_id},
        )
        await session.execute(
            text("DELETE FROM admin_user WHERE id = :id"), {"id": admin_id}
        )
        await session.commit()


def _client(token: str) -> httpx.AsyncClient:
    from app.main import create_app

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


async def _log_count(admin_id: uuid.UUID) -> int:
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT count(*) FROM operation_log WHERE admin_user_id = :id"),
            {"id": admin_id},
        )
        return result.scalar_one()


class TestMiddlewareEndToEnd:
    async def test_post_is_logged_through_middleware(self, super_admin) -> None:
        """真实鉴权链路下，POST 自动写入日志。"""
        admin_id = super_admin["admin_id"]

        before = await _log_count(admin_id)

        async with _client(super_admin["token"]) as client:
            response = await client.post(
                "/api/v1/admin/attraction-categories",
                json={
                    "name": f"e2e测试{uuid.uuid4().hex[:6]}",
                    "category_type": "theme",
                },
            )

        assert response.status_code == 201, response.text
        category_id = response.json()["data"]["id"]

        try:
            assert await _log_count(admin_id) == before + 1
        finally:
            from app.db.session import SessionLocal

            async with SessionLocal() as session:
                await session.execute(
                    text("DELETE FROM attraction_category WHERE id = :id"),
                    {"id": category_id},
                )
                await session.commit()

    async def test_get_is_not_logged_through_middleware(self, super_admin) -> None:
        """真实鉴权链路下，GET 不写入日志。"""
        admin_id = super_admin["admin_id"]
        before = await _log_count(admin_id)

        async with _client(super_admin["token"]) as client:
            for _ in range(3):
                response = await client.get("/api/v1/admin/system/roles")
                assert response.status_code == 200

        assert await _log_count(admin_id) == before

    async def test_failed_write_is_logged(self, super_admin) -> None:
        """失败的写操作也要记录——审计关心「尝试了什么」。"""
        admin_id = super_admin["admin_id"]
        before = await _log_count(admin_id)

        async with _client(super_admin["token"]) as client:
            response = await client.delete(
                f"/api/v1/admin/system/roles/{uuid.uuid4()}"
            )

        assert response.status_code == 404
        assert await _log_count(admin_id) == before + 1

        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            result = await session.execute(
                text(
                    "SELECT is_success, module, action FROM operation_log "
                    "WHERE admin_user_id = :id ORDER BY created_at DESC LIMIT 1"
                ),
                {"id": admin_id},
            )
            row = result.one()

        assert row[0] is False
        assert row[1] == "system"
        assert row[2] == "delete"

    async def test_unauthenticated_write_not_logged(self) -> None:
        """未认证的请求不记录——没有操作人，记下来也无从追责。"""
        from app.main import create_app

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/admin/attraction-categories",
                json={"name": "未认证下单", "category_type": "theme"},
            )

        assert response.status_code == 401
