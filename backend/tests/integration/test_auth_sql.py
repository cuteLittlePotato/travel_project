"""M0-T05 认证 SQL 的真实数据库集成测试。

验证 ``resolve_user_token_version`` / ``resolve_admin_token_version`` 的
SQL 在真实表结构上可执行。表由 M01-T01 / M15-T01 创建；表不存在时自动跳过。

因此该测试在 M0 阶段通常跳过，M01-T01 完成后自动生效，
可作为「表结构与认证假设一致」的回归保障。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.api.middleware.admin_auth import resolve_admin_token_version
from app.api.middleware.auth import resolve_user_token_version
from app.db.session import SessionLocal

pytestmark = pytest.mark.integration


async def _table_exists(session: object, table: str) -> bool:
    result = await session.execute(  # type: ignore[attr-defined]
        text("SELECT to_regclass(:name) IS NOT NULL"), {"name": table}
    )
    return bool(result.scalar_one())


@pytest.fixture
async def session():
    async with SessionLocal() as s:
        try:
            from app.db.session import check_database

            if not await check_database():
                pytest.skip("数据库不可达")
        except Exception:
            pytest.skip("数据库不可达")
        yield s


class TestUserTokenVersionSql:
    async def test_returns_none_for_unknown_user(self, session) -> None:
        if not await _table_exists(session, "user"):
            pytest.skip('public."user" 表尚未创建（M01-T01 后生效）')

        assert await resolve_user_token_version(session, uuid.uuid4()) is None

    async def test_excludes_deleted_users(self, session) -> None:
        """已注销账号必须返回 None，使其 Token 失效。"""
        if not await _table_exists(session, "user"):
            pytest.skip('public."user" 表尚未创建（M01-T01 后生效）')

        uid = uuid.uuid4()
        await session.execute(
            text(
                'INSERT INTO "user" (id, username, nickname, status, token_version) '
                "VALUES (:id, :username, :nickname, 'deleted', 2)"
            ),
            {"id": uid, "username": f"probe_{uid.hex[:8]}", "nickname": "probe"},
        )
        try:
            assert await resolve_user_token_version(session, uid) is None
        finally:
            await session.execute(text('DELETE FROM "user" WHERE id = :id'), {"id": uid})
            await session.rollback()

    async def test_returns_version_for_active_user(self, session) -> None:
        if not await _table_exists(session, "user"):
            pytest.skip('public."user" 表尚未创建（M01-T01 后生效）')

        uid = uuid.uuid4()
        await session.execute(
            text(
                'INSERT INTO "user" (id, username, nickname, status, token_version) '
                "VALUES (:id, :username, :nickname, 'active', 7)"
            ),
            {"id": uid, "username": f"probe_{uid.hex[:8]}", "nickname": "probe"},
        )
        try:
            assert await resolve_user_token_version(session, uid) == 7
        finally:
            await session.execute(text('DELETE FROM "user" WHERE id = :id'), {"id": uid})
            await session.rollback()


class TestAdminTokenVersionSql:
    async def test_returns_none_for_unknown_admin(self, session) -> None:
        if not await _table_exists(session, "admin_user"):
            pytest.skip("admin_user 表尚未创建（M15-T01 后生效）")

        assert await resolve_admin_token_version(session, uuid.uuid4()) is None

    async def test_disabled_admin_returns_none(self, session) -> None:
        """被禁用的管理员，其 Token 必须立即失效。"""
        if not await _table_exists(session, "admin_user"):
            pytest.skip("admin_user 表尚未创建（M15-T01 后生效）")

        aid = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO admin_user (id, username, password_hash, status, token_version) "
                "VALUES (:id, :username, 'x', 'disabled', 1)"
            ),
            {"id": aid, "username": f"probe_{aid.hex[:8]}"},
        )
        try:
            assert await resolve_admin_token_version(session, aid) is None
        finally:
            await session.execute(text("DELETE FROM admin_user WHERE id = :id"), {"id": aid})
            await session.rollback()
