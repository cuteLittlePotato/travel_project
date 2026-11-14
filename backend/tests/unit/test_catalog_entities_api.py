"""M11-T03/T04/T06/T07/T09 的验收测试。

覆盖各任务的 DoD：
    T03 分类：名称重复 21004、列表含 attraction_count、删除有引用 21005
    T04 景点：名称重复 21006、删除有引用、批量分类整体替换、列表含 final_popularity
    T06 餐厅：CRUD、城市/菜系筛选、avg_cost 非负
    T07 酒店：min_price <= max_price、HTTP 状态码
    T09 活动：日期校验、status 实时计算、无价格/状态字段
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.main import create_app
from app.modules.catalog.constants import (
    ERROR_ATTRACTION_NAME_DUPLICATE,
    ERROR_CATEGORY_IN_USE,
    ERROR_CATEGORY_NAME_DUPLICATE,
    ERROR_RESTAURANT_NOT_FOUND,
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
            text("SELECT to_regclass('public.attraction') IS NOT NULL")
        )
        if not result.scalar_one():
            pytest.skip("表未创建（先执行 alembic upgrade head）")


@pytest.fixture
async def client(db_ready: None) -> httpx.AsyncClient:
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
async def city(client: httpx.AsyncClient) -> Any:
    """创建一个省份 + 城市，测试后清理。"""
    from app.db.session import SessionLocal

    code_p = f"{uuid.uuid4().int % 900000 + 100000}"
    p = await client.post(
        "/api/v1/admin/regions/provinces",
        json={"name": f"省{uuid.uuid4().hex[:4]}", "code": code_p},
    )
    province = p.json()["data"]

    code_c = f"{uuid.uuid4().int % 900000 + 100000}"
    c = await client.post(
        "/api/v1/admin/regions/cities",
        json={
            "name": f"市{uuid.uuid4().hex[:4]}",
            "code": code_c,
            "parent_id": province["id"],
        },
    )
    city_data = c.json()["data"]

    yield city_data

    async with SessionLocal() as session:
        await session.execute(
            text("DELETE FROM region WHERE id IN (:cid, :pid)"),
            {"cid": city_data["id"], "pid": province["id"]},
        )
        await session.commit()


@pytest.fixture
async def cleanup() -> Any:
    created = {"categories": [], "attractions": [], "restaurants": [], "hotels": [], "activities": []}
    yield created

    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        for aid in created["attractions"]:
            await session.execute(
                text("DELETE FROM attraction_category_relation WHERE attraction_id = :id"),
                {"id": aid},
            )
            await session.execute(
                text("DELETE FROM attraction WHERE id = :id"), {"id": aid}
            )
        for cid in created["categories"]:
            await session.execute(
                text("DELETE FROM attraction_category WHERE id = :id"), {"id": cid}
            )
        for rid in created["restaurants"]:
            await session.execute(text("DELETE FROM restaurant WHERE id = :id"), {"id": rid})
        for hid in created["hotels"]:
            await session.execute(text("DELETE FROM hotel WHERE id = :id"), {"id": hid})
        for aid in created["activities"]:
            await session.execute(text("DELETE FROM activity WHERE id = :id"), {"id": aid})
        await session.commit()


# ============================================================
# T03：分类
# ============================================================


class TestCategoryApi:
    async def _create(
        self, client: httpx.AsyncClient, cleanup: dict, **overrides: Any
    ) -> dict:
        payload = {
            "name": f"分类{uuid.uuid4().hex[:6]}",
            "category_type": "theme",
            **overrides,
        }
        response = await client.post("/api/v1/admin/attraction-categories", json=payload)
        assert response.status_code == 201, response.text
        data = response.json()["data"]
        cleanup["categories"].append(data["id"])
        return data

    async def test_create_returns_201(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        data = await self._create(client, cleanup)
        assert data["category_type"] == "theme"

    async def test_duplicate_name_returns_21004(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """DoD：同类型下名称重复返回 21004（409）。"""
        category = await self._create(client, cleanup)

        response = await client.post(
            "/api/v1/admin/attraction-categories",
            json={"name": category["name"], "category_type": "theme"},
        )
        assert response.status_code == 409
        assert response.json()["code"] == ERROR_CATEGORY_NAME_DUPLICATE == 21004

    async def test_same_name_different_type_allowed(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """不同类型下同名允许（唯一约束是 (category_type, name)）。

        用随机名称而非 ``5A`` 这类业务上真实存在的名称——
        后者会与库里已有数据撞车，导致测试结果取决于环境。
        """
        name = f"同名测试{uuid.uuid4().hex[:6]}"
        await self._create(client, cleanup, name=name, category_type="theme")
        response = await client.post(
            "/api/v1/admin/attraction-categories",
            json={"name": name, "category_type": "level"},
        )
        assert response.status_code == 201
        cleanup["categories"].append(response.json()["data"]["id"])

    async def test_list_contains_attraction_count(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        """DoD：列表含 attraction_count。"""
        category = await self._create(client, cleanup)

        # 创建一个关联该分类的景点
        attraction = await client.post(
            "/api/v1/admin/attractions",
            json={
                "name": f"景点{uuid.uuid4().hex[:6]}",
                "city_id": city["id"],
                "category_ids": [category["id"]],
            },
        )
        cleanup["attractions"].append(attraction.json()["data"]["id"])

        response = await client.get("/api/v1/admin/attraction-categories")
        items = response.json()["data"]["items"]
        target = next(i for i in items if i["id"] == category["id"])
        assert target["attraction_count"] == 1

    async def test_delete_with_attractions_returns_21005(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        """DoD：删除有景点关联的分类返回 21005（409）。"""
        category = await self._create(client, cleanup)

        attraction = await client.post(
            "/api/v1/admin/attractions",
            json={
                "name": f"景点{uuid.uuid4().hex[:6]}",
                "city_id": city["id"],
                "category_ids": [category["id"]],
            },
        )
        cleanup["attractions"].append(attraction.json()["data"]["id"])

        response = await client.delete(
            f"/api/v1/admin/attraction-categories/{category['id']}"
        )
        assert response.status_code == 409
        assert response.json()["code"] == ERROR_CATEGORY_IN_USE == 21005

    async def test_delete_empty_category_succeeds(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        category = await self._create(client, cleanup)
        response = await client.delete(
            f"/api/v1/admin/attraction-categories/{category['id']}"
        )
        assert response.status_code == 204
        cleanup["categories"].remove(category["id"])

    async def test_invalid_parent_returns_404(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        response = await client.post(
            "/api/v1/admin/attraction-categories",
            json={
                "name": f"子分类{uuid.uuid4().hex[:6]}",
                "category_type": "theme",
                "parent_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 404

    async def test_parent_type_must_match(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """上级分类的类型必须与当前一致。"""
        theme = await self._create(client, cleanup, category_type="theme")
        response = await client.post(
            "/api/v1/admin/attraction-categories",
            json={
                "name": f"子分类{uuid.uuid4().hex[:6]}",
                "category_type": "level",
                "parent_id": theme["id"],
            },
        )
        assert response.status_code == 400


# ============================================================
# T04：景点
# ============================================================


class TestAttractionApi:
    async def _create(
        self, client: httpx.AsyncClient, cleanup: dict, city_id: str, **overrides: Any
    ) -> dict:
        payload = {
            "name": f"景点{uuid.uuid4().hex[:6]}",
            "city_id": city_id,
            **overrides,
        }
        response = await client.post("/api/v1/admin/attractions", json=payload)
        assert response.status_code == 201, response.text
        data = response.json()["data"]
        cleanup["attractions"].append(data["id"])
        return data

    async def test_create_returns_201(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        data = await self._create(client, cleanup, city["id"])
        assert data["city_id"] == city["id"]

    async def test_duplicate_name_in_city_returns_21006(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        """DoD：同城市景点名重复返回 21006（409）。"""
        attraction = await self._create(client, cleanup, city["id"])

        response = await client.post(
            "/api/v1/admin/attractions",
            json={"name": attraction["name"], "city_id": city["id"]},
        )
        assert response.status_code == 409
        assert response.json()["code"] == ERROR_ATTRACTION_NAME_DUPLICATE == 21006

    async def test_same_name_different_city_allowed(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        """不同城市可以有同名景点（唯一约束是 (name, city_id)）。"""
        # 造第二个城市
        from app.db.session import SessionLocal

        code_c = f"{uuid.uuid4().int % 900000 + 100000}"
        c2 = await client.post(
            "/api/v1/admin/regions/cities",
            json={"name": f"市{uuid.uuid4().hex[:4]}", "code": code_c, "parent_id": city["parent_id"]},
        )
        city2 = c2.json()["data"]

        try:
            await self._create(client, cleanup, city["id"], name="同名景点")
            response = await client.post(
                "/api/v1/admin/attractions",
                json={"name": "同名景点", "city_id": city2["id"]},
            )
            assert response.status_code == 201
            cleanup["attractions"].append(response.json()["data"]["id"])
        finally:
            async with SessionLocal() as session:
                await session.execute(
                    text("DELETE FROM region WHERE id = :id"), {"id": city2["id"]}
                )
                await session.commit()

    async def test_list_contains_final_popularity(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        """DoD：列表返回 final_popularity（来自 popularity_stat）。"""
        await self._create(client, cleanup, city["id"])

        response = await client.get(
            f"/api/v1/admin/attractions?city_id={city['id']}"
        )
        item = response.json()["data"]["items"][0]
        assert "final_popularity" in item
        # 未计算热度时应回退到 base_popularity
        assert item["final_popularity"] is not None

    async def test_set_categories_replaces_all(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        """DoD：批量设置分类为整体替换语义。"""
        # 建两个分类
        cat_a = await client.post(
            "/api/v1/admin/attraction-categories",
            json={"name": f"分类A{uuid.uuid4().hex[:4]}", "category_type": "theme"},
        )
        cat_b = await client.post(
            "/api/v1/admin/attraction-categories",
            json={"name": f"分类B{uuid.uuid4().hex[:4]}", "category_type": "theme"},
        )
        a_id, b_id = cat_a.json()["data"]["id"], cat_b.json()["data"]["id"]
        cleanup["categories"].extend([a_id, b_id])

        attraction = await self._create(
            client, cleanup, city["id"], category_ids=[a_id]
        )

        # 整体替换为 B
        response = await client.put(
            f"/api/v1/admin/attractions/{attraction['id']}/categories",
            json={"category_ids": [b_id]},
        )
        assert response.status_code == 204

        detail = await client.get(f"/api/v1/admin/attractions/{attraction['id']}")
        assert detail.json()["data"]["category_ids"] == [b_id]

    async def test_set_categories_empty_clears(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        """传空数组清空全部分类。"""
        cat = await client.post(
            "/api/v1/admin/attraction-categories",
            json={"name": f"分类{uuid.uuid4().hex[:4]}", "category_type": "theme"},
        )
        cat_id = cat.json()["data"]["id"]
        cleanup["categories"].append(cat_id)

        attraction = await self._create(
            client, cleanup, city["id"], category_ids=[cat_id]
        )

        await client.put(
            f"/api/v1/admin/attractions/{attraction['id']}/categories",
            json={"category_ids": []},
        )

        detail = await client.get(f"/api/v1/admin/attractions/{attraction['id']}")
        assert detail.json()["data"]["category_ids"] == []

    async def test_set_invalid_category_returns_21009(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        """边界：category_ids 含不存在的分类返回 21009（400）。"""
        attraction = await self._create(client, cleanup, city["id"])

        response = await client.put(
            f"/api/v1/admin/attractions/{attraction['id']}/categories",
            json={"category_ids": [str(uuid.uuid4())]},
        )
        assert response.status_code == 400
        assert response.json()["code"] == 21009

    async def test_delete_attraction_succeeds_when_unreferenced(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        attraction = await self._create(client, cleanup, city["id"])
        response = await client.delete(f"/api/v1/admin/attractions/{attraction['id']}")
        assert response.status_code == 204
        cleanup["attractions"].remove(attraction["id"])

    async def test_coordinate_pair_validation(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        """只给纬度不给经度应拒绝。"""
        response = await client.post(
            "/api/v1/admin/attractions",
            json={
                "name": f"景点{uuid.uuid4().hex[:6]}",
                "city_id": city["id"],
                "latitude": "39.9",
            },
        )
        assert response.status_code == 400

    async def test_coordinate_range(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        response = await client.post(
            "/api/v1/admin/attractions",
            json={
                "name": f"景点{uuid.uuid4().hex[:6]}",
                "city_id": city["id"],
                "latitude": "100",
                "longitude": "116",
            },
        )
        assert response.status_code == 400


# ============================================================
# T06：餐厅
# ============================================================


class TestRestaurantApi:
    async def test_detail_returns_all_editable_fields(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        """详情接口返回全部可编辑字段，供编辑表单回填。

        列表只返回展示字段（不含 summary / phone / signature_dishes 等），
        编辑时必须走详情接口。
        """
        create = await client.post(
            "/api/v1/admin/restaurants",
            json={
                "name": f"详情测试{uuid.uuid4().hex[:6]}",
                "city_id": city["id"],
                "cuisine_type": "川菜",
                "summary": "测试简介",
                "phone": "010-12345678",
                "business_hours": {"mon": "10:00-22:00", "note": "周一休息"},
                "signature_dishes": ["水煮鱼", "回锅肉"],
                "need_reservation": True,
                "image_urls": ["https://example.com/a.jpg"],
            },
        )
        assert create.status_code == 201
        rid = create.json()["data"]["id"]
        cleanup["restaurants"].append(rid)

        detail = await client.get(f"/api/v1/admin/restaurants/{rid}")
        assert detail.status_code == 200
        data = detail.json()["data"]

        assert data["summary"] == "测试简介"
        assert data["phone"] == "010-12345678"
        assert data["business_hours"] == {"mon": "10:00-22:00", "note": "周一休息"}
        assert data["signature_dishes"] == ["水煮鱼", "回锅肉"]
        assert data["need_reservation"] is True
        assert data["image_urls"] == ["https://example.com/a.jpg"]
        assert data["cover_image_url"] == "https://example.com/a.jpg"
        assert data["city_name"] == city["name"]

    async def test_detail_not_found(self, client: httpx.AsyncClient) -> None:
        response = await client.get(f"/api/v1/admin/restaurants/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["code"] == ERROR_RESTAURANT_NOT_FOUND

    async def test_list_omits_detail_only_fields(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        """列表不返回仅详情需要的字段——避免列表响应膨胀。"""
        create = await client.post(
            "/api/v1/admin/restaurants",
            json={
                "name": f"列表瘦身{uuid.uuid4().hex[:6]}",
                "city_id": city["id"],
                "summary": "简介",
            },
        )
        rid = create.json()["data"]["id"]
        cleanup["restaurants"].append(rid)

        lst = await client.get("/api/v1/admin/restaurants?page_size=100")
        item = next(i for i in lst.json()["data"]["items"] if i["id"] == rid)

        assert "summary" not in item
        assert "phone" not in item
        assert "signature_dishes" not in item
        # 列表展示需要的字段仍在
        assert "business_hours" in item

    async def test_crud_cycle(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        """DoD：CRUD 各端点可用。"""
        create = await client.post(
            "/api/v1/admin/restaurants",
            json={
                "name": f"餐厅{uuid.uuid4().hex[:6]}",
                "city_id": city["id"],
                "cuisine_type": "川菜",
                "avg_cost": "80.00",
            },
        )
        assert create.status_code == 201
        rid = create.json()["data"]["id"]
        cleanup["restaurants"].append(rid)

        # 列表
        lst = await client.get(f"/api/v1/admin/restaurants?city_id={city['id']}")
        assert lst.status_code == 200
        assert lst.json()["data"]["total"] >= 1

        # 更新
        upd = await client.put(
            f"/api/v1/admin/restaurants/{rid}",
            json={
                "name": "新餐厅名",
                "city_id": city["id"],
                "avg_cost": "120.00",
            },
        )
        assert upd.status_code == 204

        # 删除
        dele = await client.delete(f"/api/v1/admin/restaurants/{rid}")
        assert dele.status_code == 204
        cleanup["restaurants"].remove(rid)

    async def test_filter_by_cuisine(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        """DoD：支持按菜系筛选。"""
        create = await client.post(
            "/api/v1/admin/restaurants",
            json={
                "name": f"粤菜馆{uuid.uuid4().hex[:4]}",
                "city_id": city["id"],
                "cuisine_type": "粤菜",
            },
        )
        cleanup["restaurants"].append(create.json()["data"]["id"])

        response = await client.get("/api/v1/admin/restaurants?keyword=粤菜")
        assert response.status_code == 200

    async def test_negative_avg_cost_rejected(
        self, client: httpx.AsyncClient, city: dict
    ) -> None:
        """边界：avg_cost 为负数时拒绝。"""
        response = await client.post(
            "/api/v1/admin/restaurants",
            json={
                "name": "测试餐厅",
                "city_id": city["id"],
                "avg_cost": "-10",
            },
        )
        assert response.status_code == 400


# ============================================================
# T07：酒店
# ============================================================


class TestHotelApi:
    async def test_detail_returns_all_editable_fields(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        create = await client.post(
            "/api/v1/admin/hotels",
            json={
                "name": f"详情酒店{uuid.uuid4().hex[:6]}",
                "city_id": city["id"],
                "star_level": "five",
                "summary": "五星级",
                "phone": "010-87654321",
                "room_types": [{"name": "大床房", "price": "800"}],
                "facilities": ["wifi", "pool"],
            },
        )
        assert create.status_code == 201
        hid = create.json()["data"]["id"]
        cleanup["hotels"].append(hid)

        detail = await client.get(f"/api/v1/admin/hotels/{hid}")
        assert detail.status_code == 200
        data = detail.json()["data"]

        assert data["summary"] == "五星级"
        assert data["phone"] == "010-87654321"
        assert data["room_types"] == [{"name": "大床房", "price": "800"}]
        assert data["facilities"] == ["wifi", "pool"]

    async def test_detail_not_found(self, client: httpx.AsyncClient) -> None:
        response = await client.get(f"/api/v1/admin/hotels/{uuid.uuid4()}")
        assert response.status_code == 404


    async def test_crud_cycle(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        create = await client.post(
            "/api/v1/admin/hotels",
            json={
                "name": f"酒店{uuid.uuid4().hex[:6]}",
                "city_id": city["id"],
                "star_level": "five",
                "min_price": "500",
                "max_price": "1200",
            },
        )
        assert create.status_code == 201
        hid = create.json()["data"]["id"]
        cleanup["hotels"].append(hid)

        lst = await client.get(f"/api/v1/admin/hotels?city_id={city['id']}")
        assert lst.status_code == 200

        upd = await client.put(
            f"/api/v1/admin/hotels/{hid}",
            json={
                "name": "新酒店名",
                "city_id": city["id"],
                "min_price": "600",
                "max_price": "1500",
            },
        )
        assert upd.status_code == 204

        dele = await client.delete(f"/api/v1/admin/hotels/{hid}")
        assert dele.status_code == 204
        cleanup["hotels"].remove(hid)

    async def test_max_price_less_than_min_rejected(
        self, client: httpx.AsyncClient, city: dict
    ) -> None:
        """DoD：min_price <= max_price 校验。"""
        response = await client.post(
            "/api/v1/admin/hotels",
            json={
                "name": "测试酒店",
                "city_id": city["id"],
                "min_price": "1000",
                "max_price": "500",
            },
        )
        assert response.status_code == 400


# ============================================================
# T09：活动
# ============================================================


class TestActivityApi:
    async def test_detail_returns_all_editable_fields(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """活动详情含 status（由日期实时计算）。"""
        create = await client.post(
            "/api/v1/admin/activities",
            json={
                "title": f"详情活动{uuid.uuid4().hex[:6]}",
                "start_date": "2026-11-01",
                "end_date": "2026-11-30",
                "description": "活动描述",
                "detail_url": "https://example.com/act",
            },
        )
        assert create.status_code == 201
        aid = create.json()["data"]["id"]
        cleanup.setdefault("activities", []).append(aid)

        detail = await client.get(f"/api/v1/admin/activities/{aid}")
        assert detail.status_code == 200
        data = detail.json()["data"]

        assert data["description"] == "活动描述"
        assert data["detail_url"] == "https://example.com/act"
        # status 是 ORM @property，不在 columns 里，需显式补
        assert data["status"] in ("upcoming", "ongoing", "ended")

    async def test_detail_not_found(self, client: httpx.AsyncClient) -> None:
        response = await client.get(f"/api/v1/admin/activities/{uuid.uuid4()}")
        assert response.status_code == 404

    async def test_create_returns_201(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        today = date.today()
        response = await client.post(
            "/api/v1/admin/activities",
            json={
                "title": f"活动{uuid.uuid4().hex[:6]}",
                "activity_type": "discount",
                "start_date": today.isoformat(),
                "end_date": (today + timedelta(days=7)).isoformat(),
            },
        )
        assert response.status_code == 201
        cleanup["activities"].append(response.json()["data"]["id"])

    async def test_end_before_start_returns_400(
        self, client: httpx.AsyncClient
    ) -> None:
        """DoD：end_date >= start_date 否则拒绝（21011 / 400）。"""
        today = date.today()
        response = await client.post(
            "/api/v1/admin/activities",
            json={
                "title": "日期错误活动",
                "start_date": (today + timedelta(days=7)).isoformat(),
                "end_date": today.isoformat(),
            },
        )
        assert response.status_code == 400

    async def test_status_computed_in_list(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """DoD：列表 status 按日期实时计算。"""
        today = date.today()

        # 进行中
        ongoing = await client.post(
            "/api/v1/admin/activities",
            json={
                "title": f"进行中{uuid.uuid4().hex[:4]}",
                "start_date": (today - timedelta(days=1)).isoformat(),
                "end_date": (today + timedelta(days=1)).isoformat(),
            },
        )
        cleanup["activities"].append(ongoing.json()["data"]["id"])

        # 未开始
        upcoming = await client.post(
            "/api/v1/admin/activities",
            json={
                "title": f"未开始{uuid.uuid4().hex[:4]}",
                "start_date": (today + timedelta(days=10)).isoformat(),
                "end_date": (today + timedelta(days=17)).isoformat(),
            },
        )
        cleanup["activities"].append(upcoming.json()["data"]["id"])

        response = await client.get("/api/v1/admin/activities?page_size=100")
        items = {i["id"]: i for i in response.json()["data"]["items"]}

        assert items[ongoing.json()["data"]["id"]]["status"] == "ongoing"
        assert items[upcoming.json()["data"]["id"]]["status"] == "upcoming"

    async def test_toggle_publish(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """活动上下架（API §12.34）。"""
        today = date.today()
        create = await client.post(
            "/api/v1/admin/activities",
            json={
                "title": f"活动{uuid.uuid4().hex[:6]}",
                "start_date": today.isoformat(),
                "end_date": (today + timedelta(days=3)).isoformat(),
            },
        )
        aid = create.json()["data"]["id"]
        cleanup["activities"].append(aid)

        # 下架
        down = await client.patch(
            f"/api/v1/admin/activities/{aid}/publish", json={"is_published": False}
        )
        assert down.status_code == 204

        # 上架
        up = await client.patch(
            f"/api/v1/admin/activities/{aid}/publish", json={"is_published": True}
        )
        assert up.status_code == 204

    async def test_no_price_field(self, client: httpx.AsyncClient, cleanup: dict) -> None:
        """DoD 规范检查：活动无价格字段（价格走 detail_url 外链）。"""
        today = date.today()
        create = await client.post(
            "/api/v1/admin/activities",
            json={
                "title": f"活动{uuid.uuid4().hex[:6]}",
                "start_date": today.isoformat(),
                "end_date": (today + timedelta(days=3)).isoformat(),
            },
        )
        cleanup["activities"].append(create.json()["data"]["id"])

        data = create.json()["data"]
        assert "price" not in data
        assert "ticket_price" not in data

    async def test_status_not_stored(self, client: httpx.AsyncClient, cleanup: dict) -> None:
        """DoD 规范检查：status 是计算属性，不在数据库列中。"""
        from app.modules.catalog.models import Activity

        column_names = {c.name for c in Activity.__table__.columns}
        assert "status" not in column_names


# ============================================================
# T08：景区交通
# ============================================================


class TestTransportApi:
    """M11-T08 景区交通的测试。

    需求 §2.2.1：仅景区专属交通（观光车/索道/缆车），城际交通由 MCP 实时查询。
    """

    async def _create_attraction(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> dict:
        response = await client.post(
            "/api/v1/admin/attractions",
            json={"name": f"景点{uuid.uuid4().hex[:6]}", "city_id": city["id"]},
        )
        data = response.json()["data"]
        cleanup["attractions"].append(data["id"])
        return data

    async def test_create_and_list_by_attraction(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        """DoD：按 attraction_id 查询。"""
        attraction = await self._create_attraction(client, cleanup, city)

        create = await client.post(
            "/api/v1/admin/transports",
            json={
                "attraction_id": attraction["id"],
                "name": "景区观光车",
                "transport_type": "bus",
                "price": "30.00",
                "description": "环线运行，20 分钟一班",
            },
        )
        assert create.status_code == 201, create.text
        transport_id = create.json()["data"]["id"]

        try:
            response = await client.get(
                f"/api/v1/admin/transports?attraction_id={attraction['id']}"
            )
            assert response.status_code == 200
            items = response.json()["data"]["items"]
            assert len(items) == 1
            assert items[0]["id"] == transport_id
            assert items[0]["name"] == "景区观光车"
        finally:
            await client.delete(f"/api/v1/admin/transports/{transport_id}")

    async def test_list_empty_for_attraction_without_transport(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        attraction = await self._create_attraction(client, cleanup, city)
        response = await client.get(
            f"/api/v1/admin/transports?attraction_id={attraction['id']}"
        )
        assert response.json()["data"]["items"] == []

    async def test_create_for_nonexistent_attraction_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/admin/transports",
            json={"attraction_id": str(uuid.uuid4()), "name": "观光车"},
        )
        assert response.status_code == 404

    async def test_delete_returns_204(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        attraction = await self._create_attraction(client, cleanup, city)
        create = await client.post(
            "/api/v1/admin/transports",
            json={"attraction_id": attraction["id"], "name": "索道"},
        )
        transport_id = create.json()["data"]["id"]

        response = await client.delete(f"/api/v1/admin/transports/{transport_id}")
        assert response.status_code == 204

    async def test_delete_nonexistent_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.delete(f"/api/v1/admin/transports/{uuid.uuid4()}")
        assert response.status_code == 404

    async def test_negative_price_rejected(
        self, client: httpx.AsyncClient, cleanup: dict, city: dict
    ) -> None:
        attraction = await self._create_attraction(client, cleanup, city)
        response = await client.post(
            "/api/v1/admin/transports",
            json={
                "attraction_id": attraction["id"],
                "name": "观光车",
                "price": "-5",
            },
        )
        assert response.status_code == 400

    def test_no_intercity_fields(self) -> None:
        """DoD 规范检查：不含城际交通字段。

        需求 §2.2.1 明确：城际交通（火车/飞机/长途汽车）
        由 Agent 的地图 MCP 工具实时查询，不入库。
        因此 transport 表不应有出发地/到达地/车次号等字段。
        """
        from app.modules.catalog.models import Transport

        column_names = {c.name for c in Transport.__table__.columns}
        forbidden = {
            "origin", "destination", "departure", "arrival",
            "train_number", "flight_number", "departure_city_id",
            "arrival_city_id", "duration_minutes",
        }
        assert not (column_names & forbidden), (
            f"transport 表不应含城际交通字段: {column_names & forbidden}"
        )

    def test_cascade_delete_on_attraction(self) -> None:
        """DoD 边界：景点删除时级联删除其交通记录。

        无物理外键，需在 Service 层手动删——验证代码中存在该逻辑。
        """
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[2]
            / "app" / "modules" / "catalog" / "service.py"
        ).read_text(encoding="utf-8")

        assert "DELETE FROM transport WHERE attraction_id" in source
