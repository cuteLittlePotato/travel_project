"""M15-T04 角色与权限接口的测试。

覆盖 DoD：
    1. 删除已分配的角色返回 25005（409）（接口测试）
    2. 内置角色不可删除，返回 25006（400）（接口测试）
    3. 权限项按 module + action 分组返回（结构断言）
边界：角色 code 唯一性校验。
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
        for table in ("role", "permission", "role_permission", "admin_user_role"):
            result = await session.execute(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": f"public.{table}"},
            )
            if not result.scalar_one():
                pytest.skip(f"表 {table} 未创建")

        result = await session.execute(text("SELECT count(*) FROM permission"))
        if result.scalar_one() == 0:
            pytest.skip("权限项未初始化")


@pytest.fixture
async def client(db_ready: None) -> httpx.AsyncClient:
    from app.api.middleware.admin_auth import CurrentAdmin, require_admin
    from app.api.middleware.permission import get_permission_resolver
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[require_admin] = lambda: CurrentAdmin(
        admin_id=uuid.uuid4(), token_version=0
    )

    # M15-T05 之后 B 端接口需要权限项。测试统一按「拥有全部权限」放行，
    # 权限校验本身的行为由 test_permission_middleware.py 单独覆盖。
    # 注意返回的是真实权限编码集合，中间件没有通配符分支。
    # get_permission_resolver 是**工厂**：它的返回值才是真正的 resolver。
    # 直接覆盖它为 async 函数会被 FastAPI 当成依赖去解析参数（400）。
    # 因此覆盖成「返回全权 resolver 的同步函数」。
    from app.modules.system.permissions import permission_codes

    async def _all_permissions(_session, _admin_id) -> set[str]:
        return set(permission_codes())

    app.dependency_overrides[get_permission_resolver] = lambda: _all_permissions
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def cleanup() -> Any:
    created_roles: list[str] = []
    created_admins: list[str] = []
    yield {"roles": created_roles, "admins": created_admins}

    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        for admin_id in created_admins:
            await session.execute(
                text("DELETE FROM admin_user_role WHERE admin_user_id = :id"),
                {"id": admin_id},
            )
            await session.execute(
                text("DELETE FROM admin_user WHERE id = :id"), {"id": admin_id}
            )
        for role_id in created_roles:
            await session.execute(
                text("DELETE FROM role_permission WHERE role_id = :id"),
                {"id": role_id},
            )
            await session.execute(text("DELETE FROM role WHERE id = :id"), {"id": role_id})
        await session.commit()


def _unique_code() -> str:
    return f"test_role_{uuid.uuid4().hex[:8]}"


async def _create_role(client: httpx.AsyncClient, cleanup: dict, **overrides: Any) -> dict:
    payload = {
        "code": _unique_code(),
        "name": "测试角色",
        "description": "测试用",
        **overrides,
    }
    response = await client.post("/api/v1/admin/system/roles", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    cleanup["roles"].append(data["id"])
    return data


async def _create_admin_with_role(
    client: httpx.AsyncClient, cleanup: dict, role_id: str
) -> dict:
    response = await client.post(
        "/api/v1/admin/system/admins",
        json={
            "username": f"t_{uuid.uuid4().hex[:8]}",
            "password": "Passw0rd123",
            "role_ids": [role_id],
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    cleanup["admins"].append(data["id"])
    return data


# ============================================================
# 角色列表
# ============================================================


class TestListRoles:
    async def test_lists_builtin_roles(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v1/admin/system/roles")
        assert response.status_code == 200

        codes = {item["code"] for item in response.json()["data"]["items"]}
        assert "super_admin" in codes
        assert "normal" in codes

    async def test_includes_counts(self, client: httpx.AsyncClient) -> None:
        """列表项含管理员数与权限项数（删除前的引用提示）。"""
        response = await client.get("/api/v1/admin/system/roles")
        items = response.json()["data"]["items"]

        for item in items:
            assert "admin_count" in item
            assert "permission_count" in item

    async def test_super_admin_has_all_permissions(
        self, client: httpx.AsyncClient
    ) -> None:
        """超级管理员的 permission_count 应等于权限项总数。"""
        roles = (await client.get("/api/v1/admin/system/roles")).json()["data"]["items"]
        perms = (await client.get("/api/v1/admin/system/permissions")).json()["data"]

        super_admin = next(i for i in roles if i["code"] == "super_admin")
        assert super_admin["permission_count"] == perms["total"]

    async def test_builtin_flag_present(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v1/admin/system/roles")
        items = response.json()["data"]["items"]

        assert all("is_builtin" in item for item in items)
        assert any(item["is_builtin"] for item in items)


# ============================================================
# 创建角色（边界：code 唯一）
# ============================================================


class TestCreateRole:
    async def test_create_returns_201(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        data = await _create_role(client, cleanup)

        assert data["code"].startswith("test_role_")
        assert data["is_builtin"] is False
        assert data["permission_count"] == 0

    async def test_duplicate_code_returns_25014(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """边界：角色 code 唯一性校验。"""
        first = await _create_role(client, cleanup)

        response = await client.post(
            "/api/v1/admin/system/roles",
            json={"code": first["code"], "name": "重名角色"},
        )

        assert response.status_code == 409
        assert response.json()["code"] == 25014

    async def test_duplicate_builtin_code_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        """不能用内置角色的编码创建新角色。"""
        response = await client.post(
            "/api/v1/admin/system/roles",
            json={"code": "super_admin", "name": "假冒超管"},
        )
        assert response.status_code == 409
        assert response.json()["code"] == 25014

    async def test_create_with_permissions(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        perms = (
            await client.get("/api/v1/admin/system/permissions")
        ).json()["data"]["items"]
        permission_ids = [perms[0]["id"], perms[1]["id"]]

        data = await _create_role(
            client, cleanup, permission_ids=permission_ids
        )

        assert data["permission_count"] == 2
        assert len(data["permissions"]) == 2

    async def test_nonexistent_permission_rejected(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        response = await client.post(
            "/api/v1/admin/system/roles",
            json={
                "code": _unique_code(),
                "name": "坏权限",
                "permission_ids": [str(uuid.uuid4())],
            },
        )
        assert response.status_code == 404
        assert response.json()["code"] == 25015

    async def test_invalid_code_format_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        """code 必须小写字母开头，只含小写字母数字下划线。"""
        response = await client.post(
            "/api/v1/admin/system/roles",
            json={"code": "Bad-Code!", "name": "格式错误"},
        )
        assert response.status_code == 400


# ============================================================
# 角色详情
# ============================================================


class TestGetRole:
    async def test_detail_includes_permissions(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        perms = (
            await client.get("/api/v1/admin/system/permissions")
        ).json()["data"]["items"]
        data = await _create_role(
            client, cleanup, permission_ids=[perms[0]["id"]]
        )

        response = await client.get(f"/api/v1/admin/system/roles/{data['id']}")
        payload = response.json()["data"]

        assert payload["id"] == data["id"]
        assert len(payload["permissions"]) == 1
        assert payload["permissions"][0]["code"] == perms[0]["code"]

    async def test_not_found_returns_404(self, client: httpx.AsyncClient) -> None:
        response = await client.get(f"/api/v1/admin/system/roles/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["code"] == 25010


# ============================================================
# 更新角色
# ============================================================


class TestUpdateRole:
    async def test_update_returns_204(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        data = await _create_role(client, cleanup)

        response = await client.patch(
            f"/api/v1/admin/system/roles/{data['id']}",
            json={"name": "改过的名字"},
        )
        assert response.status_code == 204

        detail = await client.get(f"/api/v1/admin/system/roles/{data['id']}")
        assert detail.json()["data"]["name"] == "改过的名字"

    async def test_code_not_changeable(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """``code`` 不在 RoleUpdate 的字段里，传了也会被忽略。"""
        data = await _create_role(client, cleanup)
        original_code = data["code"]

        await client.patch(
            f"/api/v1/admin/system/roles/{data['id']}",
            json={"name": "改名", "code": "hacked_code"},
        )

        detail = await client.get(f"/api/v1/admin/system/roles/{data['id']}")
        assert detail.json()["data"]["code"] == original_code

    async def test_is_builtin_not_changeable(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """``is_builtin`` 由系统判定，接口不能设置。"""
        data = await _create_role(client, cleanup)

        await client.patch(
            f"/api/v1/admin/system/roles/{data['id']}",
            json={"name": "改名", "is_builtin": True},
        )

        detail = await client.get(f"/api/v1/admin/system/roles/{data['id']}")
        assert detail.json()["data"]["is_builtin"] is False


# ============================================================
# 设置角色权限
# ============================================================


class TestSetRolePermissions:
    async def test_set_permissions_replaces(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """整体替换语义：后一次提交覆盖前一次。"""
        perms = (
            await client.get("/api/v1/admin/system/permissions")
        ).json()["data"]["items"]
        data = await _create_role(
            client, cleanup, permission_ids=[perms[0]["id"], perms[1]["id"]]
        )

        response = await client.put(
            f"/api/v1/admin/system/roles/{data['id']}/permissions",
            json={"permission_ids": [perms[2]["id"]]},
        )
        assert response.status_code == 204

        detail = await client.get(f"/api/v1/admin/system/roles/{data['id']}")
        permissions = detail.json()["data"]["permissions"]

        assert len(permissions) == 1
        assert permissions[0]["id"] == perms[2]["id"]

    async def test_clear_all_permissions(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        perms = (
            await client.get("/api/v1/admin/system/permissions")
        ).json()["data"]["items"]
        data = await _create_role(client, cleanup, permission_ids=[perms[0]["id"]])

        await client.put(
            f"/api/v1/admin/system/roles/{data['id']}/permissions",
            json={"permission_ids": []},
        )

        detail = await client.get(f"/api/v1/admin/system/roles/{data['id']}")
        assert detail.json()["data"]["permissions"] == []

    async def test_nonexistent_permission_rejected(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        data = await _create_role(client, cleanup)

        response = await client.put(
            f"/api/v1/admin/system/roles/{data['id']}/permissions",
            json={"permission_ids": [str(uuid.uuid4())]},
        )
        assert response.status_code == 404


# ============================================================
# 删除角色（DoD 1 + 2）
# ============================================================


class TestDeleteRole:
    async def test_delete_returns_204(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        data = await _create_role(client, cleanup)

        response = await client.delete(f"/api/v1/admin/system/roles/{data['id']}")
        assert response.status_code == 204

        detail = await client.get(f"/api/v1/admin/system/roles/{data['id']}")
        assert detail.status_code == 404
        cleanup["roles"].remove(data["id"])

    async def test_builtin_role_returns_25006(
        self, client: httpx.AsyncClient
    ) -> None:
        """DoD：内置角色不可删除，返回 25006（400）。"""
        roles = (await client.get("/api/v1/admin/system/roles")).json()["data"]["items"]
        super_admin = next(i for i in roles if i["code"] == "super_admin")

        response = await client.delete(
            f"/api/v1/admin/system/roles/{super_admin['id']}"
        )

        assert response.status_code == 400
        assert response.json()["code"] == 25006

    async def test_in_use_role_returns_25005(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """DoD：删除已分配的角色返回 25005（409）。"""
        role = await _create_role(client, cleanup)
        await _create_admin_with_role(client, cleanup, role["id"])

        response = await client.delete(f"/api/v1/admin/system/roles/{role['id']}")

        assert response.status_code == 409
        assert response.json()["code"] == 25005

    async def test_can_delete_after_unassigning(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """解除分配后即可删除。"""
        role = await _create_role(client, cleanup)
        admin = await _create_admin_with_role(client, cleanup, role["id"])

        # 把管理员的角色换成 normal
        normal = next(
            i
            for i in (
                await client.get("/api/v1/admin/system/roles")
            ).json()["data"]["items"]
            if i["code"] == "normal"
        )
        await client.patch(
            f"/api/v1/admin/system/admins/{admin['id']}",
            json={"role_ids": [normal["id"]]},
        )

        response = await client.delete(f"/api/v1/admin/system/roles/{role['id']}")
        assert response.status_code == 204
        cleanup["roles"].remove(role["id"])

    async def test_builtin_checked_before_in_use(
        self, client: httpx.AsyncClient
    ) -> None:
        """同时满足「内置」与「已分配」时，先报内置角色（25006）。

        内置角色是请求本身不合法，与「当前有没有人用」无关。
        normal 角色通常没有管理员，但即使有也应先报 25006。
        """
        roles = (await client.get("/api/v1/admin/system/roles")).json()["data"]["items"]
        normal = next(i for i in roles if i["code"] == "normal")

        response = await client.delete(
            f"/api/v1/admin/system/roles/{normal['id']}"
        )

        assert response.status_code == 400
        assert response.json()["code"] == 25006

    async def test_delete_nonexistent_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.delete(f"/api/v1/admin/system/roles/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["code"] == 25010


# ============================================================
# 权限项列表（DoD 3）
# ============================================================


class TestListPermissions:
    async def test_returns_items_and_groups(
        self, client: httpx.AsyncClient
    ) -> None:
        """DoD：权限项按 module + action 分组返回。"""
        response = await client.get("/api/v1/admin/system/permissions")
        assert response.status_code == 200

        data = response.json()["data"]
        assert "items" in data
        assert "groups" in data
        assert "total" in data
        assert data["total"] == len(data["items"])

    async def test_groups_cover_all_modules(self, client: httpx.AsyncClient) -> None:
        data = (
            await client.get("/api/v1/admin/system/permissions")
        ).json()["data"]

        group_modules = {g["module"] for g in data["groups"]}
        item_modules = {i["module"] for i in data["items"]}
        assert group_modules == item_modules

    async def test_group_total_matches_items(
        self, client: httpx.AsyncClient
    ) -> None:
        data = (
            await client.get("/api/v1/admin/system/permissions")
        ).json()["data"]

        grouped_total = sum(len(g["permissions"]) for g in data["groups"])
        assert grouped_total == len(data["items"])

    async def test_each_permission_has_required_fields(
        self, client: httpx.AsyncClient
    ) -> None:
        data = (
            await client.get("/api/v1/admin/system/permissions")
        ).json()["data"]

        for item in data["items"]:
            for key in ("id", "code", "module", "action", "name"):
                assert key in item, f"权限项缺少 {key}"

    async def test_module_matches_inside_group(
        self, client: httpx.AsyncClient
    ) -> None:
        """分组内的权限项 module 必须与组名一致。"""
        data = (
            await client.get("/api/v1/admin/system/permissions")
        ).json()["data"]

        for group in data["groups"]:
            for permission in group["permissions"]:
                assert permission["module"] == group["module"]

    async def test_covers_expected_modules(self, client: httpx.AsyncClient) -> None:
        data = (
            await client.get("/api/v1/admin/system/permissions")
        ).json()["data"]

        modules = {g["module"] for g in data["groups"]}
        expected = {
            "catalog",
            "knowledge_base",
            "knowledge_graph",
            "model",
            "quota",
            "user_ops",
            "system",
            "dashboard",
        }
        assert modules == expected
