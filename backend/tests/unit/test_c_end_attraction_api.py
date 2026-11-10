"""M02-T01/T02/T03/T04 C 端景点接口的测试。

覆盖 M02-T01 DoD：
    1. 列表查询仅返回 ``is_published=true`` 的景点
    2. 分类筛选为「且」关系（多分类同时满足）
    3. 热度值来自 ``popularity_stat.final_popularity``，无记录时回退
       ``base_popularity``
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.modules.attraction.repository import SUPPORTED_SORT_FIELDS

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
        for table in ("attraction", "attraction_category", "region"):
            result = await session.execute(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": f"public.{table}"},
            )
            if not result.scalar_one():
                pytest.skip(f"表 {table} 未创建")


@pytest.fixture
async def client(db_ready: None) -> httpx.AsyncClient:
    from app.main import create_app

    # **不带认证**：C 端景点浏览是公开的
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    )


@pytest.fixture
async def fixture_data(db_ready: None) -> Any:
    """造一套完整的测试数据：省 + 市 + 两个分类 + 多个景点。"""
    from app.db.session import SessionLocal
    from app.utils.ids import uuid7

    province_id = uuid7()
    city_id = uuid7()
    theme_id = uuid7()
    level_id = uuid7()
    created: dict[str, Any] = {
        "province_id": province_id,
        "city_id": city_id,
        "theme_id": theme_id,
        "level_id": level_id,
        "attraction_ids": [],
    }
    suffix = uuid.uuid4().hex[:6]

    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                INSERT INTO region (id, name, level, code, parent_id, heat_score,
                                    sort_weight, created_at, updated_at)
                VALUES (:id, :name, 1, :code, NULL, 0, 100, NOW(), NOW())
                """
            ),
            {"id": province_id, "name": f"测试省{suffix}", "code": f"9{uuid.uuid4().int % 100000:05d}"},
        )
        await session.execute(
            text(
                """
                INSERT INTO region (id, name, level, code, parent_id, heat_score,
                                    sort_weight, created_at, updated_at)
                VALUES (:id, :name, 2, :code, :pid, 0, 100, NOW(), NOW())
                """
            ),
            {
                "id": city_id,
                "name": f"测试市{suffix}",
                "code": f"9{uuid.uuid4().int % 100000:05d}",
                "pid": province_id,
            },
        )
        for cat_id, name, ctype in (
            (theme_id, f"主题{suffix}", "theme"),
            (level_id, f"等级{suffix}", "level"),
        ):
            await session.execute(
                text(
                    """
                    INSERT INTO attraction_category (id, name, category_type,
                                                     sort_weight, created_at, updated_at)
                    VALUES (:id, :name, :ctype, 100, NOW(), NOW())
                    """
                ),
                {"id": cat_id, "name": name, "ctype": ctype},
            )
        await session.commit()

    yield created

    async with SessionLocal() as session:
        for aid in created["attraction_ids"]:
            await session.execute(
                text("DELETE FROM attraction_category_relation WHERE attraction_id = :id"),
                {"id": aid},
            )
            await session.execute(
                text("DELETE FROM popularity_stat WHERE attraction_id = :id"),
                {"id": aid},
            )
            await session.execute(
                text("DELETE FROM attraction WHERE id = :id"), {"id": aid}
            )
        for cid in (theme_id, level_id):
            await session.execute(
                text("DELETE FROM attraction_category WHERE id = :id"), {"id": cid}
            )
        for rid in (city_id, province_id):
            await session.execute(text("DELETE FROM region WHERE id = :id"), {"id": rid})
        await session.commit()


async def _create_attraction(
    fixture_data: dict,
    *,
    name: str,
    is_published: bool = True,
    base_popularity: str = "50",
    category_ids: list | None = None,
    final_popularity: str | None = None,
) -> uuid.UUID:
    """直接写库创建景点，避免依赖 B 端接口。"""
    from app.db.session import SessionLocal
    from app.utils.ids import uuid7

    attraction_id = uuid7()
    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                INSERT INTO attraction (id, name, city_id, base_popularity,
                                        is_published, sort_weight, created_at, updated_at)
                VALUES (:id, :name, :cid, :bp, :pub, 0, NOW(), NOW())
                """
            ),
            {
                "id": attraction_id,
                "name": name,
                "cid": fixture_data["city_id"],
                "bp": base_popularity,
                "pub": is_published,
            },
        )
        for cat_id in category_ids or []:
            await session.execute(
                text(
                    """
                    INSERT INTO attraction_category_relation
                        (id, attraction_id, category_id, created_at)
                    VALUES (:id, :aid, :cid, NOW())
                    """
                ),
                {"id": uuid7(), "aid": attraction_id, "cid": cat_id},
            )
        if final_popularity is not None:
            await session.execute(
                text(
                    """
                    INSERT INTO popularity_stat (id, attraction_id, final_popularity,
                                                 updated_at)
                    VALUES (gen_random_uuid(), :aid, :fp, NOW())
                    """
                ),
                {"aid": attraction_id, "fp": final_popularity},
            )
        await session.commit()

    fixture_data["attraction_ids"].append(attraction_id)
    return attraction_id


# ============================================================
# DoD 1：仅返回已上架景点
# ============================================================


class TestPublishedFilter:
    async def test_only_published_returned(
        self, client: httpx.AsyncClient, fixture_data: dict
    ) -> None:
        """DoD：列表查询仅返回 ``is_published=true`` 的景点。"""
        suffix = uuid.uuid4().hex[:6]
        published = await _create_attraction(
            fixture_data, name=f"已上架{suffix}"
        )
        await _create_attraction(
            fixture_data, name=f"未上架{suffix}", is_published=False
        )

        async with client:
            response = await client.get(
                "/api/v1/attractions", params={"keyword": f"上架{suffix}"}
            )

        ids = {item["id"] for item in response.json()["data"]["items"]}
        assert str(published) in ids
        assert len(ids) == 1, "未上架景点不应出现"

    async def test_offline_detail_returns_404(
        self, client: httpx.AsyncClient, fixture_data: dict
    ) -> None:
        """DoD：未上架景点的详情视同不存在。"""
        suffix = uuid.uuid4().hex[:6]
        offline = await _create_attraction(
            fixture_data, name=f"隐藏{suffix}", is_published=False
        )

        async with client:
            response = await client.get(f"/api/v1/attractions/{offline}")

        assert response.status_code == 404
        assert response.json()["code"] == 12001


# ============================================================
# DoD 2：分类筛选为「且」关系
# ============================================================


class TestCombinedFilters:
    async def test_keyword_and_province_together(
        self, client: httpx.AsyncClient, fixture_data: dict
    ) -> None:
        """keyword + province_id 同时传**不能报错**。

        回归测试：原实现里两者各自 `join(Region)`，SQL 变成
        `FROM attraction JOIN region ... JOIN region ...`，
        PostgreSQL 报「table name "region" specified more than once」。
        而这恰恰是「搜索 + 按省筛选」这种最常见的组合。
        """
        suffix = uuid.uuid4().hex[:6]
        await _create_attraction(fixture_data, name=f"组合筛选{suffix}")

        async with client:
            response = await client.get(
                "/api/v1/attractions",
                params={
                    "keyword": suffix,
                    "province_id": str(fixture_data["province_id"]),
                },
            )

        assert response.status_code == 200, response.text

    async def test_keyword_city_and_province(
        self, client: httpx.AsyncClient, fixture_data: dict
    ) -> None:
        """三个条件同时传也不应出错。"""
        suffix = uuid.uuid4().hex[:6]
        await _create_attraction(fixture_data, name=f"三条件{suffix}")

        async with client:
            response = await client.get(
                "/api/v1/attractions",
                params={
                    "keyword": suffix,
                    "city_id": str(fixture_data["city_id"]),
                    "province_id": str(fixture_data["province_id"]),
                },
            )

        assert response.status_code == 200, response.text
        assert response.json()["data"]["total"] >= 1

    async def test_province_filter_alone(
        self, client: httpx.AsyncClient, fixture_data: dict
    ) -> None:
        suffix = uuid.uuid4().hex[:6]
        await _create_attraction(fixture_data, name=f"仅省份{suffix}")

        async with client:
            response = await client.get(
                "/api/v1/attractions",
                params={"province_id": str(fixture_data["province_id"])},
            )

        assert response.status_code == 200
        assert response.json()["data"]["total"] >= 1


class TestCategoryAndRelation:
    async def test_both_categories_required(
        self, client: httpx.AsyncClient, fixture_data: dict
    ) -> None:
        """DoD：多分类为「且」——只满足其一的景点不应出现。"""
        suffix = uuid.uuid4().hex[:6]
        theme_id = fixture_data["theme_id"]
        level_id = fixture_data["level_id"]

        both = await _create_attraction(
            fixture_data,
            name=f"双分类{suffix}",
            category_ids=[theme_id, level_id],
        )
        only_theme = await _create_attraction(
            fixture_data, name=f"仅主题{suffix}", category_ids=[theme_id]
        )

        async with client:
            response = await client.get(
                "/api/v1/attractions",
                params={
                    "category_ids": f"{theme_id},{level_id}",
                    "keyword": suffix,
                },
            )

        ids = {item["id"] for item in response.json()["data"]["items"]}
        assert str(both) in ids
        assert str(only_theme) not in ids, "只满足一个分类的景点不应出现"

    async def test_single_category_works(
        self, client: httpx.AsyncClient, fixture_data: dict
    ) -> None:
        suffix = uuid.uuid4().hex[:6]
        theme_id = fixture_data["theme_id"]
        target = await _create_attraction(
            fixture_data, name=f"单分类{suffix}", category_ids=[theme_id]
        )

        async with client:
            response = await client.get(
                "/api/v1/attractions",
                params={"category_ids": str(theme_id), "keyword": suffix},
            )

        ids = {item["id"] for item in response.json()["data"]["items"]}
        assert str(target) in ids

    async def test_invalid_uuid_ignored(
        self, client: httpx.AsyncClient, fixture_data: dict
    ) -> None:
        """非法的分类 ID 被忽略，不影响列表返回。"""
        async with client:
            response = await client.get(
                "/api/v1/attractions", params={"category_ids": "not-a-uuid"}
            )

        assert response.status_code == 200


# ============================================================
# DoD 3：热度回退
# ============================================================


class TestPopularityFallback:
    async def test_uses_stat_when_present(
        self, client: httpx.AsyncClient, fixture_data: dict
    ) -> None:
        """DoD：有统计记录时用 ``final_popularity``。"""
        suffix = uuid.uuid4().hex[:6]
        attraction = await _create_attraction(
            fixture_data,
            name=f"有统计{suffix}",
            base_popularity="30",
            final_popularity="88.5",
        )

        async with client:
            response = await client.get(f"/api/v1/attractions/{attraction}")

        assert response.json()["data"]["popularity"] == 88.5

    async def test_falls_back_to_base(
        self, client: httpx.AsyncClient, fixture_data: dict
    ) -> None:
        """DoD：无统计记录时回退 ``base_popularity``（而不是 0）。"""
        suffix = uuid.uuid4().hex[:6]
        attraction = await _create_attraction(
            fixture_data, name=f"无统计{suffix}", base_popularity="72"
        )

        async with client:
            response = await client.get(f"/api/v1/attractions/{attraction}")

        assert response.json()["data"]["popularity"] == 72.0

    async def test_list_also_applies_fallback(
        self, client: httpx.AsyncClient, fixture_data: dict
    ) -> None:
        """列表同样回退——新景点不能因为没统计记录而显示 0 热度。"""
        suffix = uuid.uuid4().hex[:6]
        await _create_attraction(
            fixture_data, name=f"列表回退{suffix}", base_popularity="66"
        )

        async with client:
            response = await client.get(
                "/api/v1/attractions", params={"keyword": suffix}
            )

        item = response.json()["data"]["items"][0]
        assert item["popularity"] == 66.0


# ============================================================
# 排序
# ============================================================


class TestSorting:
    async def test_invalid_sort_by_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        async with client:
            response = await client.get(
                "/api/v1/attractions", params={"sort_by": "bogus"}
            )

        assert response.status_code == 400

    async def test_sort_by_price(
        self, client: httpx.AsyncClient, fixture_data: dict
    ) -> None:
        suffix = uuid.uuid4().hex[:6]
        cheap = await _create_attraction(fixture_data, name=f"便宜{suffix}")
        # 直接设价格
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            await session.execute(
                text("UPDATE attraction SET ticket_price = 10 WHERE id = :id"),
                {"id": cheap},
            )
            await session.commit()

        async with client:
            response = await client.get(
                "/api/v1/attractions",
                params={
                    "keyword": suffix,
                    "sort_by": "ticket_price",
                    "sort_order": "asc",
                },
            )

        assert response.status_code == 200

    def test_supported_fields(self) -> None:
        assert {"popularity", "created_at", "ticket_price"} == SUPPORTED_SORT_FIELDS


# ============================================================
# 分类与地区字典
# ============================================================


class TestDictionaries:
    async def test_categories_grouped(self, client: httpx.AsyncClient) -> None:
        """API §4.6：按 theme / level 分组。"""
        async with client:
            response = await client.get("/api/v1/attraction-categories")

        data = response.json()["data"]
        assert "themes" in data
        assert "levels" in data

    async def test_regions_public(self, client: httpx.AsyncClient) -> None:
        async with client:
            response = await client.get("/api/v1/regions")

        assert response.status_code == 200


# ============================================================
# 搜索建议
# ============================================================


class TestSuggestions:
    async def test_returns_suggestions(
        self, client: httpx.AsyncClient, fixture_data: dict
    ) -> None:
        suffix = uuid.uuid4().hex[:6]
        await _create_attraction(fixture_data, name=f"建议测试{suffix}")

        async with client:
            response = await client.get(
                "/api/v1/attractions/suggestions", params={"keyword": suffix}
            )

        items = response.json()["data"]["items"]
        assert any(i["type"] == "attraction" for i in items)

    async def test_includes_regions(
        self, client: httpx.AsyncClient, fixture_data: dict
    ) -> None:
        """地区建议包含省份——搜「浙江」想找的是整个省。"""
        suffix = uuid.uuid4().hex[:6]
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            await session.execute(
                text("UPDATE region SET name = :n WHERE id = :id"),
                {"n": f"建议省{suffix}", "id": fixture_data["province_id"]},
            )
            await session.commit()

        async with client:
            response = await client.get(
                "/api/v1/attractions/suggestions", params={"keyword": suffix}
            )

        items = response.json()["data"]["items"]
        assert any(i["type"] == "city" for i in items)

    async def test_keyword_required(self, client: httpx.AsyncClient) -> None:
        async with client:
            response = await client.get("/api/v1/attractions/suggestions")

        assert response.status_code == 400


# ============================================================
# 公开访问
# ============================================================


class TestPublicAccess:
    async def test_no_auth_needed(self, client: httpx.AsyncClient) -> None:
        """C 端景点浏览无需登录（API §16.3 权限矩阵）。"""
        async with client:
            for path in (
                "/api/v1/attractions",
                "/api/v1/attraction-categories",
                "/api/v1/regions",
            ):
                response = await client.get(path)
                assert response.status_code == 200, f"{path} 返回 {response.status_code}"
