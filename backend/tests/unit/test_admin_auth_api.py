"""M15-T08 管理员登录/登出/改密的测试。

覆盖 DoD：
    1. 登录返回 user_type='admin' 的 Token（接口测试）
    2. 登出后 admin_user.token_version 自增（DB 断言）
    3. 改密时原密码错误返回 25007（400）（接口测试）
    4. 改密后原 Token 失效（接口测试）
边界：管理员账号禁用后无法登录。
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


# ============================================================
# 夹具
# ============================================================


@pytest.fixture
async def db_ready() -> None:
    from app.db.session import SessionLocal, check_database

    try:
        if not await check_database():
            pytest.skip("数据库不可达")
    except Exception:
        pytest.skip("数据库不可达")

    async with SessionLocal() as session:
        for table in ("admin_user", "admin_user_role", "role"):
            result = await session.execute(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": f"public.{table}"},
            )
            if not result.scalar_one():
                pytest.skip(f"表 {table} 未创建")


@pytest.fixture
async def admin_account(db_ready: None) -> Any:
    """创建一个可登录的管理员（超管角色 + 已知密码）。"""
    from app.core.security import hash_password
    from app.db.session import SessionLocal
    from app.utils.ids import uuid7

    admin_id = uuid7()
    username = f"auth_{uuid.uuid4().hex[:8]}"
    password = "Passw0rd123"

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
                "username": username,
                "hash": hash_password(password),
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

    yield {"id": admin_id, "username": username, "password": password}

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


def _client() -> httpx.AsyncClient:
    from app.main import create_app

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    )


async def _login(client: httpx.AsyncClient, account: dict) -> httpx.Response:
    return await client.post(
        "/api/v1/admin/auth/login",
        json={"username": account["username"], "password": account["password"]},
    )


async def _token_version(admin_id: uuid.UUID) -> int:
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT token_version FROM admin_user WHERE id = :id"),
            {"id": admin_id},
        )
        return result.scalar_one()


# ============================================================
# 登录（DoD 1）
# ============================================================


class TestAdminLogin:
    async def test_login_returns_tokens(self, admin_account: dict) -> None:
        async with _client() as client:
            response = await _login(client, admin_account)

        assert response.status_code == 200
        data = response.json()["data"]

        assert data["access_token"]
        assert data["refresh_token"]
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    async def test_token_user_type_is_admin(self, admin_account: dict) -> None:
        """DoD：登录返回 user_type='admin' 的 Token。"""
        from app.core.security import decode_token

        async with _client() as client:
            response = await _login(client, admin_account)

        token = response.json()["data"]["access_token"]
        payload = decode_token(token, expected_type="access")

        assert payload.user_type == "admin"
        assert payload.subject_id == admin_account["id"]

    async def test_response_marks_user_type_admin(self, admin_account: dict) -> None:
        async with _client() as client:
            response = await _login(client, admin_account)

        assert response.json()["data"]["user_type"] == "admin"

    async def test_login_includes_admin_info(self, admin_account: dict) -> None:
        async with _client() as client:
            response = await _login(client, admin_account)

        admin = response.json()["data"]["admin"]
        assert admin["username"] == admin_account["username"]
        assert any(role["code"] == "super_admin" for role in admin["roles"])

    async def test_refresh_cookie_set(self, admin_account: dict) -> None:
        """Refresh Token 写 httpOnly Cookie（评审 §Q1）。"""
        async with _client() as client:
            response = await _login(client, admin_account)

        cookie_header = response.headers.get("set-cookie", "")
        assert "travel_admin_refresh_token" in cookie_header
        assert "HttpOnly" in cookie_header

    async def test_wrong_password_returns_401(self, admin_account: dict) -> None:
        async with _client() as client:
            response = await client.post(
                "/api/v1/admin/auth/login",
                json={"username": admin_account["username"], "password": "WrongPass1"},
            )

        assert response.status_code == 401
        assert response.json()["code"] == 11006

    async def test_nonexistent_username_returns_same_error(self) -> None:
        """用户名不存在与密码错误返回相同错误——防账号枚举。"""
        async with _client() as client:
            response = await client.post(
                "/api/v1/admin/auth/login",
                json={"username": "no_such_admin_x", "password": "SomePass1"},
            )

        assert response.status_code == 401
        assert response.json()["code"] == 11006
        assert response.json()["message"] == "用户名或密码错误"

    async def test_disabled_account_cannot_login(self, admin_account: dict) -> None:
        """边界：管理员账号禁用后无法登录。"""
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            await session.execute(
                text("UPDATE admin_user SET status = 'disabled' WHERE id = :id"),
                {"id": admin_account["id"]},
            )
            await session.commit()

        async with _client() as client:
            response = await _login(client, admin_account)

        assert response.status_code == 403
        assert response.json()["code"] == 11002

    async def test_login_updates_last_login_at(self, admin_account: dict) -> None:
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            before = await session.execute(
                text("SELECT last_login_at FROM admin_user WHERE id = :id"),
                {"id": admin_account["id"]},
            )
            assert before.scalar_one() is None

        async with _client() as client:
            await _login(client, admin_account)

        async with SessionLocal() as session:
            after = await session.execute(
                text("SELECT last_login_at FROM admin_user WHERE id = :id"),
                {"id": admin_account["id"]},
            )
            assert after.scalar_one() is not None

    async def test_admin_token_cannot_access_c_end(self, admin_account: dict) -> None:
        """B 端 Token 不能访问 C 端接口——两套体系完全分离。"""
        async with _client() as client:
            login = await _login(client, admin_account)
            token = login.json()["data"]["access_token"]

            response = await client.get(
                "/api/v1/users/me",
                headers={"Authorization": f"Bearer {token}"},
            )

        # C 端中间件拒绝 admin Token → 403（不是 401：
        # Token 本身有效，只是「类型不对」，语义上是禁止而非未认证）
        assert response.status_code == 403


# ============================================================
# 登出（DoD 2）
# ============================================================


class TestAdminLogout:
    async def test_logout_increments_token_version(self, admin_account: dict) -> None:
        """DoD：登出后 admin_user.token_version 自增（DB 断言）。"""
        async with _client() as client:
            login = await _login(client, admin_account)
            token = login.json()["data"]["access_token"]

            before = await _token_version(admin_account["id"])

            response = await client.post(
                "/api/v1/admin/auth/logout",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 204
        assert await _token_version(admin_account["id"]) == before + 1

    async def test_old_token_invalid_after_logout(self, admin_account: dict) -> None:
        """全端登出：登出前签发的 Token 立即失效。"""
        async with _client() as client:
            login = await _login(client, admin_account)
            token = login.json()["data"]["access_token"]

            await client.post(
                "/api/v1/admin/auth/logout",
                headers={"Authorization": f"Bearer {token}"},
            )

            # 用旧 Token 访问受保护接口
            response = await client.get(
                "/api/v1/admin/system/roles",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 401

    async def test_logout_clears_cookie(self, admin_account: dict) -> None:
        async with _client() as client:
            login = await _login(client, admin_account)
            token = login.json()["data"]["access_token"]

            response = await client.post(
                "/api/v1/admin/auth/logout",
                headers={"Authorization": f"Bearer {token}"},
            )

        cookie_header = response.headers.get("set-cookie", "")
        # 删除 Cookie 会带 Max-Age=0 或 expires 过去时间
        assert "travel_admin_refresh_token" in cookie_header

    async def test_logout_requires_login(self) -> None:
        async with _client() as client:
            response = await client.post("/api/v1/admin/auth/logout")

        assert response.status_code == 401

    async def test_logout_requires_no_permission(self, admin_account: dict) -> None:
        """登出不要求权限项——否则没权限的人还登不出去。"""
        from app.api.middleware.admin_auth import CurrentAdmin, require_admin
        from app.api.middleware.permission import get_permission_resolver
        from app.main import create_app

        app = create_app()
        app.dependency_overrides[require_admin] = lambda: CurrentAdmin(
            admin_id=admin_account["id"], token_version=0
        )

        # 权限集合为空——模拟没有任何权限的管理员
        async def _no_permissions(_session, _admin_id) -> set[str]:
            return set()

        app.dependency_overrides[get_permission_resolver] = lambda: _no_permissions

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/v1/admin/auth/logout")

        assert response.status_code == 204


# ============================================================
# 修改自己的密码（DoD 3 + 4）
# ============================================================


class TestChangeOwnPassword:
    async def test_change_returns_204(self, admin_account: dict) -> None:
        async with _client() as client:
            login = await _login(client, admin_account)
            token = login.json()["data"]["access_token"]

            response = await client.put(
                "/api/v1/admin/me/password",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "old_password": admin_account["password"],
                    "new_password": "NewPassw0rd9",
                },
            )

        assert response.status_code == 204

    async def test_wrong_old_password_returns_25007(
        self, admin_account: dict
    ) -> None:
        """DoD：改密时原密码错误返回 25007（400）。"""
        async with _client() as client:
            login = await _login(client, admin_account)
            token = login.json()["data"]["access_token"]

            response = await client.put(
                "/api/v1/admin/me/password",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "old_password": "WrongOldPass1",
                    "new_password": "NewPassw0rd9",
                },
            )

        assert response.status_code == 400
        assert response.json()["code"] == 25007

    async def test_same_password_returns_25008(self, admin_account: dict) -> None:
        async with _client() as client:
            login = await _login(client, admin_account)
            token = login.json()["data"]["access_token"]

            response = await client.put(
                "/api/v1/admin/me/password",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "old_password": admin_account["password"],
                    "new_password": admin_account["password"],
                },
            )

        assert response.status_code == 400
        assert response.json()["code"] == 25008

    async def test_old_token_invalid_after_change(self, admin_account: dict) -> None:
        """DoD：改密后原 Token 失效。"""
        async with _client() as client:
            login = await _login(client, admin_account)
            token = login.json()["data"]["access_token"]

            await client.put(
                "/api/v1/admin/me/password",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "old_password": admin_account["password"],
                    "new_password": "NewPassw0rd9",
                },
            )

            response = await client.get(
                "/api/v1/admin/system/roles",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 401

    async def test_can_login_with_new_password(self, admin_account: dict) -> None:
        async with _client() as client:
            login = await _login(client, admin_account)
            token = login.json()["data"]["access_token"]

            await client.put(
                "/api/v1/admin/me/password",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "old_password": admin_account["password"],
                    "new_password": "NewPassw0rd9",
                },
            )

            # 旧密码登不上
            old_login = await client.post(
                "/api/v1/admin/auth/login",
                json={
                    "username": admin_account["username"],
                    "password": admin_account["password"],
                },
            )
            assert old_login.status_code == 401

            # 新密码可以
            new_login = await client.post(
                "/api/v1/admin/auth/login",
                json={
                    "username": admin_account["username"],
                    "password": "NewPassw0rd9",
                },
            )
            assert new_login.status_code == 200

    async def test_weak_new_password_rejected(self, admin_account: dict) -> None:
        async with _client() as client:
            login = await _login(client, admin_account)
            token = login.json()["data"]["access_token"]

            response = await client.put(
                "/api/v1/admin/me/password",
                headers={"Authorization": f"Bearer {token}"},
                json={"old_password": admin_account["password"], "new_password": "12345678"},
            )

        assert response.status_code == 400
        assert response.json()["code"] == 10001

    async def test_requires_login(self) -> None:
        async with _client() as client:
            response = await client.put(
                "/api/v1/admin/me/password",
                json={"old_password": "a1234567", "new_password": "b1234567"},
            )

        assert response.status_code == 401


# ============================================================
# 刷新 Token（B 端独立实现）
# ============================================================


class TestAdminRefresh:
    async def test_refresh_returns_new_tokens(self, admin_account: dict) -> None:
        async with _client() as client:
            login = await _login(client, admin_account)
            refresh = login.json()["data"]["refresh_token"]

            response = await client.post(
                "/api/v1/admin/auth/refresh",
                json={"refresh_token": refresh},
            )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["access_token"]
        assert data["refresh_token"]
        assert data["user_type"] == "admin"

    async def test_refresh_token_is_rotated(self, admin_account: dict) -> None:
        """轮换机制：旧 Refresh Token 用过一次即失效。"""
        async with _client() as client:
            login = await _login(client, admin_account)
            old_refresh = login.json()["data"]["refresh_token"]

            first = await client.post(
                "/api/v1/admin/auth/refresh",
                json={"refresh_token": old_refresh},
            )
            assert first.status_code == 200

            second = await client.post(
                "/api/v1/admin/auth/refresh",
                json={"refresh_token": old_refresh},
            )

        assert second.status_code == 401
        assert second.json()["code"] == 11010

    async def test_refresh_fails_after_logout(self, admin_account: dict) -> None:
        """登出后 token_version 自增，Refresh Token 也失效。"""
        async with _client() as client:
            login = await _login(client, admin_account)
            data = login.json()["data"]

            await client.post(
                "/api/v1/admin/auth/logout",
                headers={"Authorization": f"Bearer {data['access_token']}"},
            )

            response = await client.post(
                "/api/v1/admin/auth/refresh",
                json={"refresh_token": data["refresh_token"]},
            )

        assert response.status_code == 401

    async def test_refresh_without_token_rejected(self, admin_account: dict) -> None:
        async with _client() as client:
            response = await client.post("/api/v1/admin/auth/refresh", json={})

        assert response.status_code == 401

    async def test_c_end_refresh_token_rejected(self, admin_account: dict) -> None:
        """C 端 Refresh Token 不能用于 B 端刷新。"""
        from app.core.security import create_refresh_token

        user_token = create_refresh_token(str(admin_account["id"]), "user", 0)

        async with _client() as client:
            response = await client.post(
                "/api/v1/admin/auth/refresh",
                json={"refresh_token": user_token},
            )

        assert response.status_code == 401
        assert response.json()["code"] == 11010
