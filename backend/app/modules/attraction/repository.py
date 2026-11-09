"""M02 景点内容的 C 端只读数据访问层。

与 ``modules.catalog.repository`` 的区别：
    ``catalog`` 是 B 端管理（增删改查都能做），本模块是 C 端消费，
    **只有查询，且查询条件固定带 ``is_published = true``**。

为什么不直接复用 catalog 的 Repository：
    1. C 端的列表查询条件不同（多分类「且」关系、省份筛选、三种排序）
    2. C 端必须过滤上下架，B 端要能查全部——同一方法不能同时满足
    3. B 端改字段不应波及 C 端查询契约

模型仍复用 ``modules.catalog.models``——表是 M11 建的，M02 只读，
不在本模块重复定义模型（CLAUDE.md §5.1 的「模型先行」针对建表模块）。
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import (
    Attraction,
    AttractionCategory,
    AttractionCategoryRelation,
    PopularityStat,
    Region,
    Transport,
)

#: C 端排序方式（API §4.1 ``sort_by``）
SORT_POPULARITY = "popularity"
SORT_CREATED_AT = "created_at"
SORT_TICKET_PRICE = "ticket_price"

SUPPORTED_SORT_FIELDS = frozenset({SORT_POPULARITY, SORT_CREATED_AT, SORT_TICKET_PRICE})


class AttractionQueryRepository:
    """C 端景点查询。

    只做数据读取，不含业务规则。热度回退、空分类处理等在 service 层。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------------- 列表 ----------------

    async def list_published(
        self,
        *,
        keyword: str | None = None,
        city_id: uuid.UUID | None = None,
        province_id: uuid.UUID | None = None,
        category_ids: list[uuid.UUID] | None = None,
        sort_by: str = "popularity",
        sort_order: str = "desc",
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Attraction], int]:
        """C 端景点列表（API §4.1）。

        **多分类为「且」关系**（DoD）：需要景点同时关联所有给定分类。
        实现方式是对 ``attraction_category_relation`` 按 ``attraction_id``
        分组计数——计数等于分类数即为「且」。

        热度排序需要 LEFT JOIN ``popularity_stat``，无记录时回退
        ``base_popularity``（``COALESCE``），否则新景点会排到最后。
        """
        stmt = select(Attraction).where(Attraction.is_published.is_(True))

        if keyword:
            # 名称或城市名的模糊匹配
            stmt = stmt.join(Region, Region.id == Attraction.city_id).where(
                Attraction.name.ilike(f"%{keyword}%")
                | Region.name.ilike(f"%{keyword}%")
            )
        if city_id is not None:
            stmt = stmt.where(Attraction.city_id == city_id)
        if province_id is not None:
            # 景点挂在市上，省市关系靠 region.parent_id 表达
            stmt = stmt.join(Region, Region.id == Attraction.city_id).where(
                Region.parent_id == province_id
            )

        if category_ids:
            # 且关系：按 attraction_id 分组，命中分类数 == 传入分类数
            subq = (
                select(AttractionCategoryRelation.attraction_id)
                .where(AttractionCategoryRelation.category_id.in_(category_ids))
                .group_by(AttractionCategoryRelation.attraction_id)
                .having(
                    func.count(AttractionCategoryRelation.category_id)
                    == len(set(category_ids))
                )
                .subquery()
            )
            stmt = stmt.where(Attraction.id.in_(select(subq.c.attraction_id)))

        # 计数在排序/分页之前，用原始条件的子查询
        total = (
            await self.session.execute(
                select(func.count()).select_from(stmt.subquery())
            )
        ).scalar_one()

        stmt = self._apply_sort(stmt, sort_by=sort_by, sort_order=sort_order)
        # 分页必须有稳定次序，否则翻页时同热度景点会重复/遗漏
        stmt = stmt.order_by(Attraction.id).offset(offset).limit(limit)

        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total

    def _apply_sort(self, stmt: Select[Any], *, sort_by: str, sort_order: str) -> Select[Any]:
        descending = sort_order != "asc"

        if sort_by == "popularity":
            # LEFT JOIN + COALESCE：无 popularity_stat 记录时用 base_popularity
            stmt = stmt.outerjoin(
                PopularityStat, PopularityStat.attraction_id == Attraction.id
            )
            effective = func.coalesce(
                PopularityStat.final_popularity, Attraction.base_popularity
            )
            return stmt.order_by(effective.desc() if descending else effective.asc())

        if sort_by == "ticket_price":
            # 价格为空的景点排在最后（NULLS LAST），否则「从低到高」会把免费/未填的混在前面
            column = Attraction.ticket_price
            return stmt.order_by(
                column.desc().nullslast() if descending else column.asc().nullslast()
            )

        column = Attraction.created_at
        return stmt.order_by(column.desc() if descending else column.asc())

    # ---------------- 批量补全（避免 N+1） ----------------

    async def get_cities(self, city_ids: list[uuid.UUID]) -> dict[uuid.UUID, Region]:
        if not city_ids:
            return {}
        rows = (
            await self.session.execute(select(Region).where(Region.id.in_(set(city_ids))))
        ).scalars().all()
        return {row.id: row for row in rows}

    async def get_parent_regions(
        self, region_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, Region]:
        """批量取上级省份（详情页需要展示「省 / 市」两级）。"""
        if not region_ids:
            return {}
        rows = (
            await self.session.execute(
                select(Region).where(Region.id.in_(set(region_ids)))
            )
        ).scalars().all()
        return {row.id: row for row in rows}

    async def get_categories_bulk(
        self, attraction_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[AttractionCategory]]:
        """批量取景点分类，按景点分组。"""
        if not attraction_ids:
            return {}
        result = await self.session.execute(
            select(
                AttractionCategoryRelation.attraction_id,
                AttractionCategory,
            )
            .join(
                AttractionCategory,
                AttractionCategory.id == AttractionCategoryRelation.category_id,
            )
            .where(AttractionCategoryRelation.attraction_id.in_(set(attraction_ids)))
            .order_by(AttractionCategory.sort_weight.desc(), AttractionCategory.name)
        )
        mapping: dict[uuid.UUID, list[AttractionCategory]] = {}
        for attraction_id, category in result.all():
            mapping.setdefault(attraction_id, []).append(category)
        return mapping

    async def get_popularity_bulk(
        self, attraction_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, Decimal]:
        """批量取最终热度（DoD：无记录时由 service 回退 base_popularity）。"""
        if not attraction_ids:
            return {}
        result = await self.session.execute(
            select(
                PopularityStat.attraction_id, PopularityStat.final_popularity
            ).where(PopularityStat.attraction_id.in_(set(attraction_ids)))
        )
        return {row[0]: row[1] for row in result.all()}

    # ---------------- 详情 ----------------

    async def get_published_by_id(self, attraction_id: uuid.UUID) -> Attraction | None:
        """详情查询（DoD：未上架视同不存在，由 service 转 12001）。"""
        result = await self.session.execute(
            select(Attraction).where(
                Attraction.id == attraction_id,
                Attraction.is_published.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_categories(self, attraction_id: uuid.UUID) -> list[AttractionCategory]:
        result = await self.session.execute(
            select(AttractionCategory)
            .join(
                AttractionCategoryRelation,
                AttractionCategory.id == AttractionCategoryRelation.category_id,
            )
            .where(AttractionCategoryRelation.attraction_id == attraction_id)
            .order_by(AttractionCategory.sort_weight.desc(), AttractionCategory.name)
        )
        return list(result.scalars().all())

    async def list_transports(self, attraction_id: uuid.UUID) -> list[Transport]:
        result = await self.session.execute(
            select(Transport)
            .where(Transport.attraction_id == attraction_id)
            .order_by(Transport.created_at, Transport.name)
        )
        return list(result.scalars().all())

    async def get_popularity(self, attraction_id: uuid.UUID) -> Decimal | None:
        result = await self.session.execute(
            select(PopularityStat.final_popularity).where(
                PopularityStat.attraction_id == attraction_id
            )
        )
        return result.scalar_one_or_none()

    # ---------------- 分类 / 城市字典（C 端筛选栏） ----------------

    async def list_categories_grouped(
        self, category_type: str | None = None
    ) -> list[AttractionCategory]:
        stmt = select(AttractionCategory)
        if category_type is not None:
            stmt = stmt.where(AttractionCategory.category_type == category_type)
        stmt = stmt.order_by(
            AttractionCategory.sort_weight.desc(), AttractionCategory.name
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_regions(
        self, *, level: int | None = None, parent_id: uuid.UUID | None = None
    ) -> list[Region]:
        stmt = select(Region)
        if level is not None:
            stmt = stmt.where(Region.level == level)
        if parent_id is not None:
            stmt = stmt.where(Region.parent_id == parent_id)
        stmt = stmt.order_by(Region.sort_weight.desc(), Region.name)
        return list((await self.session.execute(stmt)).scalars().all())

    # ---------------- 搜索建议 ----------------

    async def suggest(self, keyword: str, *, limit: int = 10) -> tuple[list[Attraction], list[Region]]:
        """搜索建议（API §4.9）：景点名 + 城市名各取一批。"""
        pattern = f"%{keyword}%"

        attractions = list(
            (
                await self.session.execute(
                    select(Attraction)
                    .where(
                        Attraction.is_published.is_(True),
                        Attraction.name.ilike(pattern),
                    )
                    .order_by(Attraction.sort_weight.desc(), Attraction.name)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

        cities = list(
            (
                await self.session.execute(
                    select(Region)
                    .where(Region.name.ilike(pattern))
                    .order_by(Region.sort_weight.desc(), Region.name)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

        return attractions, cities


async def table_exists(session: AsyncSession, table_name: str) -> bool:
    """检查表是否存在——M10 图谱表可能尚未建立。"""
    result = await session.execute(
        text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"public.{table_name}"}
    )
    return bool(result.scalar_one())
