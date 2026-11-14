"""M11-T02 省市管理接口的测试。

覆盖 DoD：
    1. code 重复返回 21001（409）
    2. 删除有下级城市的省份返回 21002（409）
    3. 删除有景点的城市返回 21003（409）
    4. 省份列表含 city_count
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.exceptions import ErrorCode
from app.main import create_app
from app.modules.catalog.constants import (
    ERROR_REGION_CODE_DUPLICATE,
    ERROR_REGION_HAS_CHILDREN,
    ERROR_REGION_IN_USE,
)

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
        result = await session.execute(
            text("SELECT to_regclass('public.region') IS NOT NULL")
        )
        if not result.scalar_one():
            pytest.skip("表未创建（先执行 alembic upgrade head）")


@pytest.fixture
async def client(db_ready: None) -> httpx.AsyncClient:
    """B 端客户端，绕过认证（用 dependency_overrides）。"""
    from app.api.middleware.admin_auth import CurrentAdmin, require_admin

    app = create_app()
    app.dependency_overrides[require_admin] = lambda: CurrentAdmin(
        admin_id=uuid.uuid4(), token_version=0
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
async def cleanup() -> Any:
    """记录创建的资源，测试后清理。"""
    created = {"provinces": [], "cities": [], "attractions": []}
    yield created

    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        for aid in created["attractions"]:
            await session.execute(
                text("DELETE FROM attraction WHERE id = :id"), {"id": aid}
            )
        for cid in created["cities"]:
            await session.execute(text("DELETE FROM region WHERE id = :id"), {"id": cid})
        for pid in created["provinces"]:
            await session.execute(text("DELETE FROM region WHERE id = :id"), {"id": pid})
        await session.commit()


def _unique_code() -> str:
    """生成唯一的 6 位行政区划编码。"""
    return f"{uuid.uuid4().int % 900000 + 100000}"


async def _create_province(
    client: httpx.AsyncClient, cleanup: dict, **overrides: Any
) -> dict:
    payload = {
        "name": f"测试省{uuid.uuid4().hex[:4]}",
        "code": _unique_code(),
        **overrides,
    }
    response = await client.post("/api/v1/admin/regions/provinces", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    cleanup["provinces"].append(data["id"])
    return data


async def _create_city(
    client: httpx.AsyncClient, cleanup: dict, province_id: str, **overrides: Any
) -> dict:
    payload = {
        "name": f"测试市{uuid.uuid4().hex[:4]}",
        "code": _unique_code(),
        "parent_id": province_id,
        **overrides,
    }
    response = await client.post("/api/v1/admin/regions/cities", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    cleanup["cities"].append(data["id"])
    return data


# ============================================================
# 省份 CRUD
# ============================================================


class TestProvinceCrud:
    async def test_create_returns_201(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        data = await _create_province(client, cleanup)
        assert data["level"] == 1
        assert data["parent_id"] is None
        assert data["code"]

    async def test_list_contains_city_count(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """DoD：省份列表含 city_count。"""
        province = await _create_province(client, cleanup)
        await _create_city(client, cleanup, province["id"])
        await _create_city(client, cleanup, province["id"])

        response = await client.get("/api/v1/admin/regions/provinces")
        assert response.status_code == 200
        items = response.json()["data"]["items"]

        target = next(i for i in items if i["id"] == province["id"])
        assert target["city_count"] == 2

    async def test_city_count_zero_for_new_province(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        province = await _create_province(client, cleanup)
        response = await client.get("/api/v1/admin/regions/provinces")
        target = next(
            i for i in response.json()["data"]["items"] if i["id"] == province["id"]
        )
        assert target["city_count"] == 0

    async def test_update_returns_204(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        province = await _create_province(client, cleanup)
        response = await client.put(
            f"/api/v1/admin/regions/provinces/{province['id']}",
            json={
                "name": "新名称",
                "code": province["code"],
                "heat_score": 88.5,
            },
        )
        assert response.status_code == 204

    async def test_delete_returns_204(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        province = await _create_province(client, cleanup)
        response = await client.delete(
            f"/api/v1/admin/regions/provinces/{province['id']}"
        )
        assert response.status_code == 204
        cleanup["provinces"].remove(province["id"])


# ============================================================
# DoD 1：code 重复
# ============================================================


class TestCodeDuplicate:
    async def test_duplicate_province_code_returns_21001(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """DoD：code 重复返回 21001（409）。"""
        province = await _create_province(client, cleanup)

        response = await client.post(
            "/api/v1/admin/regions/provinces",
            json={"name": "另一个省", "code": province["code"]},
        )
        assert response.status_code == 409
        assert response.json()["code"] == ERROR_REGION_CODE_DUPLICATE == 21001

    async def test_duplicate_city_code_returns_21001(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        province = await _create_province(client, cleanup)
        city = await _create_city(client, cleanup, province["id"])

        response = await client.post(
            "/api/v1/admin/regions/cities",
            json={
                "name": "另一个市",
                "code": city["code"],
                "parent_id": province["id"],
            },
        )
        assert response.status_code == 409
        assert response.json()["code"] == 21001

    async def test_update_to_existing_code_returns_21001(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """更新时改成一个已被占用的编码，也应拒绝。"""
        first = await _create_province(client, cleanup)
        second = await _create_province(client, cleanup)

        response = await client.put(
            f"/api/v1/admin/regions/provinces/{second['id']}",
            json={"name": second["name"], "code": first["code"]},
        )
        assert response.status_code == 409
        assert response.json()["code"] == 21001


# ============================================================
# DoD 2：删除有城市的省份
# ============================================================


class TestDeleteProvinceWithCities:
    async def test_returns_21002(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """DoD：删除有下级城市的省份返回 21002（409）。"""
        province = await _create_province(client, cleanup)
        await _create_city(client, cleanup, province["id"])

        response = await client.delete(
            f"/api/v1/admin/regions/provinces/{province['id']}"
        )
        assert response.status_code == 409
        assert response.json()["code"] == ERROR_REGION_HAS_CHILDREN == 21002

    async def test_province_still_exists_after_rejection(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """被拒绝后省份应仍存在。"""
        province = await _create_province(client, cleanup)
        await _create_city(client, cleanup, province["id"])

        await client.delete(f"/api/v1/admin/regions/provinces/{province['id']}")

        response = await client.get("/api/v1/admin/regions/provinces")
        ids = {i["id"] for i in response.json()["data"]["items"]}
        assert province["id"] in ids


# ============================================================
# DoD 3：删除有景点的城市
# ============================================================


class TestDeleteCityInUse:
    async def test_returns_21003(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """DoD：删除有景点的城市返回 21003（409）。"""
        province = await _create_province(client, cleanup)
        city = await _create_city(client, cleanup, province["id"])

        # 创建一个景点挂在该城市
        response = await client.post(
            "/api/v1/admin/attractions",
            json={"name": f"景点{uuid.uuid4().hex[:6]}", "city_id": city["id"]},
        )
        assert response.status_code == 201, response.text
        cleanup["attractions"].append(response.json()["data"]["id"])

        # 删除城市应被拒绝
        delete_response = await client.delete(
            f"/api/v1/admin/regions/cities/{city['id']}"
        )
        assert delete_response.status_code == 409
        assert delete_response.json()["code"] == ERROR_REGION_IN_USE == 21003

    async def test_empty_city_can_be_deleted(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        province = await _create_province(client, cleanup)
        city = await _create_city(client, cleanup, province["id"])

        response = await client.delete(f"/api/v1/admin/regions/cities/{city['id']}")
        assert response.status_code == 204
        cleanup["cities"].remove(city["id"])


# ============================================================
# 城市 CRUD
# ============================================================


class TestCityCrud:
    async def test_create_city_requires_parent(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """创建城市 parent_id 必填。"""
        response = await client.post(
            "/api/v1/admin/regions/cities",
            json={"name": "无父城市", "code": _unique_code()},
        )
        assert response.status_code == 400

    async def test_create_city_with_invalid_parent(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        response = await client.post(
            "/api/v1/admin/regions/cities",
            json={
                "name": "测试市",
                "code": _unique_code(),
                "parent_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 404

    async def test_list_filtered_by_province(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        province_a = await _create_province(client, cleanup)
        province_b = await _create_province(client, cleanup)
        await _create_city(client, cleanup, province_a["id"])
        await _create_city(client, cleanup, province_b["id"])

        response = await client.get(
            f"/api/v1/admin/regions/cities?province_id={province_a['id']}"
        )
        data = response.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["parent_id"] == province_a["id"]

    async def test_city_list_includes_province_name(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        province = await _create_province(client, cleanup)
        await _create_city(client, cleanup, province["id"])

        response = await client.get(
            f"/api/v1/admin/regions/cities?province_id={province['id']}"
        )
        item = response.json()["data"]["items"][0]
        assert item["province_name"] == province["name"]


# ============================================================
# 参数校验
# ============================================================


class TestValidation:
    @pytest.mark.parametrize("code", ["12345", "1234567", "abcdef", "12345a"])
    async def test_invalid_code_rejected(
        self, client: httpx.AsyncClient, code: str
    ) -> None:
        """DoD 边界：code 需为 6 位国标编码。"""
        response = await client.post(
            "/api/v1/admin/regions/provinces",
            json={"name": "测试省", "code": code},
        )
        assert response.status_code == 400
        assert response.json()["code"] == ErrorCode.VALIDATION_FAILED

    async def test_valid_6_digit_code_accepted(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """合法的 6 位编码能通过校验。

        用随机编码而非 ``110000``——那是北京市的真实编码，
        而开发库已导入完整省市数据，硬编码真实编码会撞唯一约束。
        """
        code = _unique_code()
        data = await _create_province(client, cleanup, code=code)
        assert data["code"] == code

    async def test_name_too_long_rejected(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/admin/regions/provinces",
            json={"name": "x" * 51, "code": _unique_code()},
        )
        assert response.status_code == 400

    async def test_heat_score_range(self, client: httpx.AsyncClient) -> None:
        for score in (101, -1):
            response = await client.post(
                "/api/v1/admin/regions/provinces",
                json={"name": "测试省", "code": _unique_code(), "heat_score": score},
            )
            assert response.status_code == 400, f"heat_score={score} 应被拒绝"

    async def test_invalid_cover_url(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/admin/regions/provinces",
            json={
                "name": "测试省",
                "code": _unique_code(),
                "cover_image_url": "javascript:alert(1)",
            },
        )
        assert response.status_code == 400


# ============================================================
# 认证
# ============================================================


class TestAuth:
    async def test_requires_admin_token(self, db_ready: None) -> None:
        """无 B 端 Token 访问返回 401。"""
        app = create_app()  # 不覆盖依赖
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/v1/admin/regions/provinces")
        assert response.status_code == 401

    async def test_c_token_rejected(self, db_ready: None) -> None:
        """C 端 Token 访问 B 端接口返回 403。"""
        from app.core.security import create_access_token

        app = create_app()
        transport = httpx.ASGITransport(app=app)
        c_token = create_access_token(str(uuid.uuid4()), "user", 0)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get(
                "/api/v1/admin/regions/provinces",
                headers={"Authorization": f"Bearer {c_token}"},
            )
        assert response.status_code == 403
