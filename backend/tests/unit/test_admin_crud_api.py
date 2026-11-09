"""M15-T03 管理员 CRUD 接口的测试。

覆盖 DoD：
    1. 用户名重复返回 25002（409）（接口测试）
    2. 删除仅存的超级管理员返回 25003（409）（接口测试）
    3. 不能删除自己返回 25004（400）（接口测试）
    4. 规范检查：响应不含 password_hash、token_version
边界：重置密码后需使目标管理员 Token 失效。
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
        for table in ("admin_user", "role", "admin_user_role"):
            result = await session.execute(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": f"public.{table}"},
            )
            if not result.scalar_one():
                pytest.skip(f"表 {table} 未创建（先执行 alembic upgrade head）")
        # 种子数据必须已灌入
        result = await session.execute(text("SELECT count(*) FROM role"))
        if result.scalar_one() == 0:
            pytest.skip("角色种子数据未初始化（执行 alembic upgrade head）")


#: 测试里「当前登录管理员」的 ID，由夹具设定
@pytest.fixture
def current_admin_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
async def client(db_ready: None, current_admin_id: uuid.UUID) -> httpx.AsyncClient:
    from app.api.middleware.admin_auth import CurrentAdmin, require_admin
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[require_admin] = lambda: CurrentAdmin(
        admin_id=current_admin_id, token_version=0
    )

    # M15-T05：B 端接口需要权限项。测试统一按「拥有全部权限」放行，
    # 权限校验本身的行为由 test_permission_middleware.py 单独覆盖。
    from app.api.middleware.permission import get_permission_resolver
    from app.modules.system.permissions import permission_codes

    async def _all_permissions(_session, _admin_id) -> set[str]:
        return set(permission_codes())

    app.dependency_overrides[get_permission_resolver] = lambda: _all_permissions

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def super_admin_role_id() -> str:
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT id FROM role WHERE code = 'super_admin'")
        )
        return str(result.scalar_one())


@pytest.fixture
async def normal_role_id() -> str:
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT id FROM role WHERE code = 'normal'")
        )
        return str(result.scalar_one())


@pytest.fixture
async def cleanup() -> Any:
    created: list[str] = []
    yield created

    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        for admin_id in created:
            await session.execute(
                text("DELETE FROM admin_user_role WHERE admin_user_id = :id"),
                {"id": admin_id},
            )
            await session.execute(
                text("DELETE FROM admin_user WHERE id = :id"), {"id": admin_id}
            )
        await session.commit()


def _unique_username() -> str:
    return f"test_{uuid.uuid4().hex[:8]}"


async def _create(
    client: httpx.AsyncClient,
    cleanup: list[str],
    role_id: str,
    **overrides: Any,
) -> dict:
    payload = {
        "username": _unique_username(),
        "password": "Passw0rd123",
        "real_name": "测试管理员",
        "email": f"{uuid.uuid4().hex[:6]}@example.com",
        "role_ids": [role_id],
        **overrides,
    }
    response = await client.post("/api/v1/admin/system/admins", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    cleanup.append(data["id"])
    return data


# ============================================================
# 创建（DoD 1）
# ============================================================


class TestCreateAdmin:
    async def test_create_returns_201(
        self, client: httpx.AsyncClient, cleanup: list[str], normal_role_id: str
    ) -> None:
        data = await _create(client, cleanup, normal_role_id)

        assert data["username"].startswith("test_")
        assert data["status"] == "active"
        assert len(data["roles"]) == 1
        assert data["roles"][0]["code"] == "normal"

    async def test_duplicate_username_returns_25002(
        self, client: httpx.AsyncClient, cleanup: list[str], normal_role_id: str
    ) -> None:
        """DoD：用户名重复返回 25002（409）。"""
        first = await _create(client, cleanup, normal_role_id)

        response = await client.post(
            "/api/v1/admin/system/admins",
            json={
                "username": first["username"],
                "password": "Passw0rd123",
                "role_ids": [normal_role_id],
            },
        )

        assert response.status_code == 409
        assert response.json()["code"] == 25002

    async def test_password_is_hashed(
        self, client: httpx.AsyncClient, cleanup: list[str], normal_role_id: str
    ) -> None:
        """密码必须以 bcrypt 哈希存储，不能是明文。"""
        plain = "Passw0rd123"
        data = await _create(client, cleanup, normal_role_id, password=plain)

        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            result = await session.execute(
                text("SELECT password_hash FROM admin_user WHERE id = :id"),
                {"id": data["id"]},
            )
            stored = result.scalar_one()

        assert stored != plain
        assert stored.startswith("$2")  # bcrypt 标识

    async def test_weak_password_rejected(
        self, client: httpx.AsyncClient, normal_role_id: str
    ) -> None:
        """密码必须含字母与数字。"""
        response = await client.post(
            "/api/v1/admin/system/admins",
            json={
                "username": _unique_username(),
                "password": "12345678",  # 纯数字
                "role_ids": [normal_role_id],
            },
        )
        assert response.status_code == 400
        assert response.json()["code"] == 10001

    async def test_short_password_rejected(
        self, client: httpx.AsyncClient, normal_role_id: str
    ) -> None:
        response = await client.post(
            "/api/v1/admin/system/admins",
            json={
                "username": _unique_username(),
                "password": "Ab1",  # 太短
                "role_ids": [normal_role_id],
            },
        )
        assert response.status_code == 400

    async def test_invalid_username_rejected(
        self, client: httpx.AsyncClient, normal_role_id: str
    ) -> None:
        """用户名只允许字母数字下划线。"""
        response = await client.post(
            "/api/v1/admin/system/admins",
            json={
                "username": "bad-name!",
                "password": "Passw0rd123",
                "role_ids": [normal_role_id],
            },
        )
        assert response.status_code == 400

    async def test_empty_roles_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        """至少一个角色（API §14.2）。"""
        response = await client.post(
            "/api/v1/admin/system/admins",
            json={
                "username": _unique_username(),
                "password": "Passw0rd123",
                "role_ids": [],
            },
        )
        assert response.status_code == 400

    async def test_nonexistent_role_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/admin/system/admins",
            json={
                "username": _unique_username(),
                "password": "Passw0rd123",
                "role_ids": [str(uuid.uuid4())],
            },
        )
        assert response.status_code == 404
        assert response.json()["code"] == 25010


# ============================================================
# 敏感字段（DoD 4）
# ============================================================


class TestNoSensitiveFields:
    async def test_create_response_has_no_sensitive_fields(
        self, client: httpx.AsyncClient, cleanup: list[str], normal_role_id: str
    ) -> None:
        """DoD：响应不含 password_hash、token_version。"""
        data = await _create(client, cleanup, normal_role_id)

        assert "password_hash" not in data
        assert "token_version" not in data
        assert "password" not in data

    async def test_list_has_no_sensitive_fields(
        self, client: httpx.AsyncClient, cleanup: list[str], normal_role_id: str
    ) -> None:
        await _create(client, cleanup, normal_role_id)

        response = await client.get(
            "/api/v1/admin/system/admins", params={"page_size": 100}
        )

        for item in response.json()["data"]["items"]:
            assert "password_hash" not in item
            assert "token_version" not in item

    async def test_detail_has_no_sensitive_fields(
        self, client: httpx.AsyncClient, cleanup: list[str], normal_role_id: str
    ) -> None:
        data = await _create(client, cleanup, normal_role_id)

        response = await client.get(f"/api/v1/admin/system/admins/{data['id']}")

        payload = response.json()["data"]
        assert "password_hash" not in payload
        assert "token_version" not in payload


# ============================================================
# 查询
# ============================================================


class TestQueryAdmins:
    async def test_list_pagination(
        self, client: httpx.AsyncClient, cleanup: list[str], normal_role_id: str
    ) -> None:
        await _create(client, cleanup, normal_role_id)

        response = await client.get(
            "/api/v1/admin/system/admins", params={"page": 1, "page_size": 10}
        )
        data = response.json()["data"]

        for key in ("items", "total", "page", "page_size", "total_pages"):
            assert key in data

    async def test_list_includes_roles(
        self, client: httpx.AsyncClient, cleanup: list[str], normal_role_id: str
    ) -> None:
        created = await _create(client, cleanup, normal_role_id)

        response = await client.get(
            "/api/v1/admin/system/admins", params={"page_size": 100}
        )
        items = response.json()["data"]["items"]

        target = next(i for i in items if i["id"] == created["id"])
        assert len(target["roles"]) == 1
        assert target["roles"][0]["code"] == "normal"

    async def test_detail_not_found(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get(f"/api/v1/admin/system/admins/{uuid.uuid4()}")

        assert response.status_code == 404
        assert response.json()["code"] == 25009


# ============================================================
# 更新与重置密码
# ============================================================


class TestUpdateAdmin:
    async def test_update_returns_204(
        self, client: httpx.AsyncClient, cleanup: list[str], normal_role_id: str
    ) -> None:
        data = await _create(client, cleanup, normal_role_id)

        response = await client.patch(
            f"/api/v1/admin/system/admins/{data['id']}",
            json={"real_name": "改过的名字"},
        )
        assert response.status_code == 204

        detail = await client.get(f"/api/v1/admin/system/admins/{data['id']}")
        assert detail.json()["data"]["real_name"] == "改过的名字"

    async def test_patch_only_changes_given_fields(
        self, client: httpx.AsyncClient, cleanup: list[str], normal_role_id: str
    ) -> None:
        """PATCH 语义：只传 real_name 时 email 不受影响。"""
        data = await _create(
            client, cleanup, normal_role_id, email="original@example.com"
        )

        await client.patch(
            f"/api/v1/admin/system/admins/{data['id']}",
            json={"real_name": "只改名字"},
        )

        detail = await client.get(f"/api/v1/admin/system/admins/{data['id']}")
        assert detail.json()["data"]["email"] == "original@example.com"

    async def test_change_roles(
        self, client: httpx.AsyncClient, cleanup: list[str], normal_role_id: str,
        super_admin_role_id: str,
    ) -> None:
        data = await _create(client, cleanup, normal_role_id)

        await client.patch(
            f"/api/v1/admin/system/admins/{data['id']}",
            json={"role_ids": [super_admin_role_id]},
        )

        detail = await client.get(f"/api/v1/admin/system/admins/{data['id']}")
        assert detail.json()["data"]["roles"][0]["code"] == "super_admin"

    async def test_cannot_disable_self(
        self, client: httpx.AsyncClient, cleanup: list[str], normal_role_id: str,
        current_admin_id: uuid.UUID,
    ) -> None:
        """不能禁用自己——禁用后立即失去登录能力。"""
        from app.db.session import SessionLocal

        # 创建一个 ID 与 current_admin_id 相同的管理员
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
                    "id": current_admin_id,
                    "username": _unique_username(),
                    "hash": "$2b$12$" + "x" * 53,
                },
            )
            await session.commit()

        try:
            response = await client.patch(
                f"/api/v1/admin/system/admins/{current_admin_id}",
                json={"status": "disabled"},
            )

            assert response.status_code == 400
            assert response.json()["code"] == 25011
        finally:
            async with SessionLocal() as session:
                await session.execute(
                    text("DELETE FROM admin_user WHERE id = :id"),
                    {"id": current_admin_id},
                )
                await session.commit()


class TestResetPassword:
    async def test_reset_returns_204(
        self, client: httpx.AsyncClient, cleanup: list[str], normal_role_id: str
    ) -> None:
        data = await _create(client, cleanup, normal_role_id)

        response = await client.put(
            f"/api/v1/admin/system/admins/{data['id']}/password",
            json={"new_password": "NewPassw0rd9"},
        )
        assert response.status_code == 204

    async def test_reset_invalidates_tokens(
        self, client: httpx.AsyncClient, cleanup: list[str], normal_role_id: str
    ) -> None:
        """任务卡边界：重置密码后需使目标管理员 Token 失效。"""
        data = await _create(client, cleanup, normal_role_id)

        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            before = await session.execute(
                text("SELECT token_version FROM admin_user WHERE id = :id"),
                {"id": data["id"]},
            )
            version_before = before.scalar_one()

        await client.put(
            f"/api/v1/admin/system/admins/{data['id']}/password",
            json={"new_password": "NewPassw0rd9"},
        )

        async with SessionLocal() as session:
            after = await session.execute(
                text("SELECT token_version FROM admin_user WHERE id = :id"),
                {"id": data["id"]},
            )
            version_after = after.scalar_one()

        assert version_after == version_before + 1

    async def test_reset_weak_password_rejected(
        self, client: httpx.AsyncClient, cleanup: list[str], normal_role_id: str
    ) -> None:
        data = await _create(client, cleanup, normal_role_id)

        response = await client.put(
            f"/api/v1/admin/system/admins/{data['id']}/password",
            json={"new_password": "12345678"},
        )
        assert response.status_code == 400

    async def test_reset_nonexistent_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.put(
            f"/api/v1/admin/system/admins/{uuid.uuid4()}/password",
            json={"new_password": "NewPassw0rd9"},
        )
        assert response.status_code == 404


# ============================================================
# 删除（DoD 2 + 3）
# ============================================================


class TestDeleteAdmin:
    async def test_delete_returns_204(
        self, client: httpx.AsyncClient, cleanup: list[str], normal_role_id: str
    ) -> None:
        data = await _create(client, cleanup, normal_role_id)

        response = await client.delete(f"/api/v1/admin/system/admins/{data['id']}")
        assert response.status_code == 204

        detail = await client.get(f"/api/v1/admin/system/admins/{data['id']}")
        assert detail.status_code == 404
        cleanup.remove(data["id"])

    async def test_cannot_delete_self_returns_25004(
        self, client: httpx.AsyncClient, current_admin_id: uuid.UUID
    ) -> None:
        """DoD：不能删除自己返回 25004（400）。"""
        from app.db.session import SessionLocal

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
                    "id": current_admin_id,
                    "username": _unique_username(),
                    "hash": "$2b$12$" + "x" * 53,
                },
            )
            await session.commit()

        try:
            response = await client.delete(
                f"/api/v1/admin/system/admins/{current_admin_id}"
            )

            assert response.status_code == 400
            assert response.json()["code"] == 25004
        finally:
            async with SessionLocal() as session:
                await session.execute(
                    text("DELETE FROM admin_user WHERE id = :id"),
                    {"id": current_admin_id},
                )
                await session.commit()

    async def test_delete_last_super_admin_returns_25003(
        self, client: httpx.AsyncClient, cleanup: list[str], super_admin_role_id: str
    ) -> None:
        """DoD：删除仅存的超级管理员返回 25003（409）。"""
        from app.db.session import SessionLocal

        # 先清空所有现有的超管，确保被测的是「仅存」
        async with SessionLocal() as session:
            existing = await session.execute(
                text(
                    """
                    SELECT count(DISTINCT aur.admin_user_id)
                    FROM admin_user_role aur
                    JOIN role r ON r.id = aur.role_id
                    WHERE r.code = 'super_admin'
                    """
                )
            )
            if existing.scalar_one() > 0:
                pytest.skip("库中已有超级管理员，无法构造「仅存」场景")

        only = await _create(client, cleanup, super_admin_role_id)

        response = await client.delete(f"/api/v1/admin/system/admins/{only['id']}")

        assert response.status_code == 409
        assert response.json()["code"] == 25003

    async def test_delete_one_of_two_super_admins_allowed(
        self, client: httpx.AsyncClient, cleanup: list[str], super_admin_role_id: str
    ) -> None:
        """有两个超管时，删掉其中一个应成功。"""
        first = await _create(client, cleanup, super_admin_role_id)
        second = await _create(client, cleanup, super_admin_role_id)

        response = await client.delete(f"/api/v1/admin/system/admins/{first['id']}")

        assert response.status_code == 204
        cleanup.remove(first["id"])
        # second 仍存在
        detail = await client.get(f"/api/v1/admin/system/admins/{second['id']}")
        assert detail.status_code == 200

    async def test_delete_nonexistent_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.delete(f"/api/v1/admin/system/admins/{uuid.uuid4()}")
        assert response.status_code == 404
