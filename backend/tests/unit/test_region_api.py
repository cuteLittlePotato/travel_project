"""C 端地区字典接口的测试（API §4.7）。

背景：个人资料的「常驻地区」原本让用户手填行政区划编码
（如 110000），这是不合理的交互。改为省市级联选择器后，
需要 C 端提供公开的地区列表接口。
"""

from __future__ import annotations

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
            text("SELECT to_regclass('public.region') IS NOT NULL")
        )
        if not result.scalar_one():
            pytest.skip("表未创建")


@pytest.fixture
async def client(db_ready: None) -> httpx.AsyncClient:
    from app.main import create_app

    # **不带任何认证**——地区字典是公开数据
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    )


class TestPublicAccess:
    async def test_no_auth_required(self, client: httpx.AsyncClient) -> None:
        """地区列表无需认证——筛选与个人资料都要用。"""
        async with client:
            response = await client.get("/api/v1/regions")

        assert response.status_code == 200

    async def test_returns_items(self, client: httpx.AsyncClient) -> None:
        async with client:
            response = await client.get("/api/v1/regions")

        data = response.json()["data"]
        assert "items" in data
        assert isinstance(data["items"], list)


class TestFiltering:
    async def test_filter_provinces(self, client: httpx.AsyncClient) -> None:
        async with client:
            response = await client.get("/api/v1/regions", params={"level": 1})

        items = response.json()["data"]["items"]
        assert all(item["level"] == 1 for item in items)

    async def test_filter_cities(self, client: httpx.AsyncClient) -> None:
        async with client:
            response = await client.get("/api/v1/regions", params={"level": 2})

        items = response.json()["data"]["items"]
        assert all(item["level"] == 2 for item in items)

    async def test_filter_by_parent(self, client: httpx.AsyncClient) -> None:
        """按省份查下属城市——级联选择器的第二级。"""
        async with client:
            provinces = (
                await client.get("/api/v1/regions", params={"level": 1})
            ).json()["data"]["items"]
            if not provinces:
                pytest.skip("地区数据未初始化")

            province = provinces[0]
            response = await client.get(
                "/api/v1/regions", params={"parent_id": province["id"]}
            )

        items = response.json()["data"]["items"]
        assert all(item["parent_id"] == province["id"] for item in items)
        assert all(item["level"] == 2 for item in items)

    async def test_invalid_level_rejected(self, client: httpx.AsyncClient) -> None:
        async with client:
            response = await client.get("/api/v1/regions", params={"level": 3})

        assert response.status_code == 400
        assert response.json()["code"] == 10001


class TestResponseStructure:
    async def test_has_required_fields(self, client: httpx.AsyncClient) -> None:
        async with client:
            response = await client.get("/api/v1/regions", params={"level": 1})

        items = response.json()["data"]["items"]
        if not items:
            pytest.skip("地区数据未初始化")

        item = items[0]
        for key in ("id", "name", "code", "level", "heat_score"):
            assert key in item, f"缺少字段 {key}"

    async def test_has_parent_id_for_cascade(self, client: httpx.AsyncClient) -> None:
        """前端组级联树靠 parent_id。"""
        async with client:
            response = await client.get("/api/v1/regions", params={"level": 2})

        items = response.json()["data"]["items"]
        if not items:
            pytest.skip("地区数据未初始化")

        assert all("parent_id" in item for item in items)
        assert all(item["parent_id"] is not None for item in items)

    async def test_does_not_expose_sort_weight(
        self, client: httpx.AsyncClient
    ) -> None:
        """``sort_weight`` 是运营配置字段，不需要暴露给 C 端。"""
        async with client:
            response = await client.get("/api/v1/regions", params={"level": 1})

        items = response.json()["data"]["items"]
        if not items:
            pytest.skip("地区数据未初始化")

        assert "sort_weight" not in items[0]
        assert "description" not in items[0]

    async def test_code_is_gb2260_format(self, client: httpx.AsyncClient) -> None:
        """编码是 6 位数字国标码——前端用它作为级联的 value 提交给后端。"""
        async with client:
            response = await client.get("/api/v1/regions")

        items = response.json()["data"]["items"]
        if not items:
            pytest.skip("地区数据未初始化")

        for item in items:
            assert len(item["code"]) == 6
            assert item["code"].isdigit()
