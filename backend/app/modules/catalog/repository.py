"""M11 基础数据的数据访问层。

只做数据操作，不含业务规则。不 commit（由 service 负责）。
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.constants import REGION_LEVEL_CITY, REGION_LEVEL_PROVINCE
from app.modules.catalog.models import (
    Activity,
    Attraction,
    AttractionCategory,
    AttractionCategoryRelation,
    Hotel,
    PopularityStat,
    Region,
    Restaurant,
)
from app.utils.ids import uuid7


class RegionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, region_id: uuid.UUID) -> Region | None:
        return await self.session.get(Region, region_id)

    async def get_by_code(self, code: str) -> Region | None:
        result = await self.session.execute(select(Region).where(Region.code == code))
        return result.scalar_one_or_none()

    async def exists_code(self, code: str, exclude_id: uuid.UUID | None = None) -> bool:
        stmt = select(func.count()).select_from(Region).where(Region.code == code)
        if exclude_id is not None:
            stmt = stmt.where(Region.id != exclude_id)
        return (await self.session.execute(stmt)).scalar_one() > 0

    async def list_provinces(self, keyword: str | None = None) -> list[Region]:
        stmt = (
            select(Region)
            .where(Region.level == REGION_LEVEL_PROVINCE)
            .order_by(Region.sort_weight.desc(), Region.id)
        )
        if keyword:
            stmt = stmt.where(Region.name.ilike(f"%{keyword}%"))
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_cities(
        self,
        *,
        province_id: uuid.UUID | None = None,
        keyword: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Region], int]:
        conditions = [Region.level == REGION_LEVEL_CITY]
        if province_id is not None:
            conditions.append(Region.parent_id == province_id)
        if keyword:
            conditions.append(Region.name.ilike(f"%{keyword}%"))

        total = (
            await self.session.execute(
                select(func.count()).select_from(Region).where(*conditions)
            )
        ).scalar_one()

        stmt = (
            select(Region)
            .where(*conditions)
            .order_by(Region.sort_weight.desc(), Region.id)
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def count_children(self, province_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Region)
            .where(Region.parent_id == province_id)
        )
        return result.scalar_one()

    async def count_cities_by_province(self) -> dict[uuid.UUID, int]:
        """一次查询统计所有省份的城市数，避免 N+1。"""
        result = await self.session.execute(
            select(Region.parent_id, func.count())
            .where(Region.level == REGION_LEVEL_CITY, Region.parent_id.isnot(None))
            .group_by(Region.parent_id)
        )
        return {row[0]: row[1] for row in result.all()}

    def add(self, region: Region) -> Region:
        self.session.add(region)
        return region

    async def delete(self, region: Region) -> None:
        await self.session.delete(region)


class CategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, category_id: uuid.UUID) -> AttractionCategory | None:
        return await self.session.get(AttractionCategory, category_id)

    async def exists_name(
        self, name: str, category_type: str, exclude_id: uuid.UUID | None = None
    ) -> bool:
        stmt = (
            select(func.count())
            .select_from(AttractionCategory)
            .where(
                AttractionCategory.name == name,
                AttractionCategory.category_type == category_type,
            )
        )
        if exclude_id is not None:
            stmt = stmt.where(AttractionCategory.id != exclude_id)
        return (await self.session.execute(stmt)).scalar_one() > 0

    async def list_all(
        self, category_type: str | None = None
    ) -> list[AttractionCategory]:
        stmt = select(AttractionCategory).order_by(
            AttractionCategory.category_type,
            AttractionCategory.sort_weight.desc(),
            AttractionCategory.name,
        )
        if category_type:
            stmt = stmt.where(AttractionCategory.category_type == category_type)
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_attractions(self, category_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(AttractionCategoryRelation)
            .where(AttractionCategoryRelation.category_id == category_id)
        )
        return result.scalar_one()

    async def count_attractions_bulk(self) -> dict[uuid.UUID, int]:
        """一次查询统计所有分类下的景点数，避免 N+1。"""
        result = await self.session.execute(
            select(
                AttractionCategoryRelation.category_id, func.count()
            ).group_by(AttractionCategoryRelation.category_id)
        )
        return {row[0]: row[1] for row in result.all()}

    def add(self, category: AttractionCategory) -> AttractionCategory:
        self.session.add(category)
        return category

    async def delete(self, category: AttractionCategory) -> None:
        await self.session.delete(category)


class AttractionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, attraction_id: uuid.UUID) -> Attraction | None:
        return await self.session.get(Attraction, attraction_id)

    async def exists_name_in_city(
        self,
        name: str,
        city_id: uuid.UUID,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        stmt = (
            select(func.count())
            .select_from(Attraction)
            .where(Attraction.name == name, Attraction.city_id == city_id)
        )
        if exclude_id is not None:
            stmt = stmt.where(Attraction.id != exclude_id)
        return (await self.session.execute(stmt)).scalar_one() > 0

    async def list(
        self,
        *,
        city_id: uuid.UUID | None = None,
        category_id: uuid.UUID | None = None,
        keyword: str | None = None,
        is_published: bool | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Attraction], int]:
        conditions = []
        if city_id is not None:
            conditions.append(Attraction.city_id == city_id)
        if keyword:
            conditions.append(Attraction.name.ilike(f"%{keyword}%"))
        if is_published is not None:
            conditions.append(Attraction.is_published.is_(is_published))

        stmt = select(Attraction).where(*conditions)
        if category_id is not None:
            stmt = stmt.join(
                AttractionCategoryRelation,
                AttractionCategoryRelation.attraction_id == Attraction.id,
            ).where(AttractionCategoryRelation.category_id == category_id)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            stmt.order_by(Attraction.sort_weight.desc(), Attraction.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def count_by_city(self, city_id: uuid.UUID) -> int:
        """用于删除城市前的引用检查。"""
        result = await self.session.execute(
            select(func.count()).select_from(Attraction).where(Attraction.city_id == city_id)
        )
        return result.scalar_one()

    async def get_final_popularity(
        self, attraction_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, Decimal]:
        """批量取最终热度，避免列表页 N+1。

        ``popularity_stat`` 由 M11-T10 的数据管道维护，景点创建时可能尚不存在，
        因此未命中时由调用方回退到 ``base_popularity``。
        """
        if not attraction_ids:
            return {}
        result = await self.session.execute(
            select(PopularityStat.attraction_id, PopularityStat.final_popularity).where(
                PopularityStat.attraction_id.in_(attraction_ids)
            )
        )
        return {row[0]: row[1] for row in result.all()}

    async def count_references(self, attraction_id: uuid.UUID) -> dict[str, int]:
        """统计景点被业务引用的次数（删除前检查，DoD 要求返回 21007）。

        引用来源（M04 计划 / M05 足迹）：
            - ``footprint.attraction_id``
            - ``plan_activity.attraction_id``
            - ``activity.attraction_id``（运营活动关联）

        **用原生 SQL 而非 ORM 模型**：这些表属于 M04/M05 模块，
        在 catalog 模块内导入它们的模型会形成跨模块耦合。
        """
        from sqlalchemy import text

        queries = {
            "footprint": "SELECT count(*) FROM footprint WHERE attraction_id = :aid",
            "plan_activity": (
                "SELECT count(*) FROM plan_activity WHERE attraction_id = :aid"
            ),
            "activity": "SELECT count(*) FROM activity WHERE attraction_id = :aid",
        }
        counts: dict[str, int] = {}
        for name, sql in queries.items():
            try:
                result = await self.session.execute(text(sql), {"aid": attraction_id})
                counts[name] = result.scalar_one()
            except Exception:
                # 表不存在（模块未建）时视为无引用
                counts[name] = 0
        return counts

    async def list_categories(self, attraction_id: uuid.UUID) -> list[uuid.UUID]:
        result = await self.session.execute(
            select(AttractionCategoryRelation.category_id).where(
                AttractionCategoryRelation.attraction_id == attraction_id
            )
        )
        return list(result.scalars().all())

    async def list_categories_bulk(
        self, attraction_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[uuid.UUID]]:
        """批量查分类，避免列表页 N+1。"""
        if not attraction_ids:
            return {}
        result = await self.session.execute(
            select(
                AttractionCategoryRelation.attraction_id,
                AttractionCategoryRelation.category_id,
            ).where(AttractionCategoryRelation.attraction_id.in_(attraction_ids))
        )
        mapping: dict[uuid.UUID, list[uuid.UUID]] = {}
        for attraction_id, category_id in result.all():
            mapping.setdefault(attraction_id, []).append(category_id)
        return mapping

    async def replace_categories(
        self, attraction_id: uuid.UUID, category_ids: list[uuid.UUID]
    ) -> None:
        """替换分类关联（删除旧的 + 插入新的）。"""
        from sqlalchemy import delete

        await self.session.execute(
            delete(AttractionCategoryRelation).where(
                AttractionCategoryRelation.attraction_id == attraction_id
            )
        )
        for category_id in category_ids:
            self.session.add(
                AttractionCategoryRelation(
                    id=uuid7(),
                    attraction_id=attraction_id,
                    category_id=category_id,
                )
            )

    def add(self, attraction: Attraction) -> Attraction:
        self.session.add(attraction)
        return attraction

    async def delete(self, attraction: Attraction) -> None:
        await self.session.delete(attraction)


class RestaurantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, restaurant_id: uuid.UUID) -> Restaurant | None:
        return await self.session.get(Restaurant, restaurant_id)

    async def list(
        self,
        *,
        city_id: uuid.UUID | None = None,
        keyword: str | None = None,
        is_published: bool | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Restaurant], int]:
        conditions = []
        if city_id is not None:
            conditions.append(Restaurant.city_id == city_id)
        if keyword:
            conditions.append(Restaurant.name.ilike(f"%{keyword}%"))
        if is_published is not None:
            conditions.append(Restaurant.is_published.is_(is_published))

        total = (
            await self.session.execute(
                select(func.count()).select_from(Restaurant).where(*conditions)
            )
        ).scalar_one()

        stmt = (
            select(Restaurant)
            .where(*conditions)
            .order_by(Restaurant.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def count_by_city(self, city_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Restaurant).where(Restaurant.city_id == city_id)
        )
        return result.scalar_one()

    def add(self, restaurant: Restaurant) -> Restaurant:
        self.session.add(restaurant)
        return restaurant

    async def delete(self, restaurant: Restaurant) -> None:
        await self.session.delete(restaurant)


class HotelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, hotel_id: uuid.UUID) -> Hotel | None:
        return await self.session.get(Hotel, hotel_id)

    async def list(
        self,
        *,
        city_id: uuid.UUID | None = None,
        keyword: str | None = None,
        is_published: bool | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Hotel], int]:
        conditions = []
        if city_id is not None:
            conditions.append(Hotel.city_id == city_id)
        if keyword:
            conditions.append(Hotel.name.ilike(f"%{keyword}%"))
        if is_published is not None:
            conditions.append(Hotel.is_published.is_(is_published))

        total = (
            await self.session.execute(
                select(func.count()).select_from(Hotel).where(*conditions)
            )
        ).scalar_one()

        stmt = (
            select(Hotel)
            .where(*conditions)
            .order_by(Hotel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def count_by_city(self, city_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Hotel).where(Hotel.city_id == city_id)
        )
        return result.scalar_one()

    def add(self, hotel: Hotel) -> Hotel:
        self.session.add(hotel)
        return hotel

    async def delete(self, hotel: Hotel) -> None:
        await self.session.delete(hotel)


class ActivityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, activity_id: uuid.UUID) -> Activity | None:
        return await self.session.get(Activity, activity_id)

    async def list(
        self,
        *,
        city_id: uuid.UUID | None = None,
        is_published: bool | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Activity], int]:
        conditions = []
        if city_id is not None:
            conditions.append(Activity.city_id == city_id)
        if is_published is not None:
            conditions.append(Activity.is_published.is_(is_published))

        total = (
            await self.session.execute(
                select(func.count()).select_from(Activity).where(*conditions)
            )
        ).scalar_one()

        stmt = (
            select(Activity)
            .where(*conditions)
            .order_by(Activity.sort_weight.desc(), Activity.start_date.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all()), total

    def add(self, activity: Activity) -> Activity:
        self.session.add(activity)
        return activity

    async def delete(self, activity: Activity) -> None:
        await self.session.delete(activity)


class CatalogRepository:
    """M11 各实体的聚合入口。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.regions = RegionRepository(session)
        self.categories = CategoryRepository(session)
        self.attractions = AttractionRepository(session)
        self.restaurants = RestaurantRepository(session)
        self.hotels = HotelRepository(session)
        self.activities = ActivityRepository(session)

    async def city_in_use(self, city_id: uuid.UUID) -> bool:
        """城市是否被景点/餐厅/酒店引用。用于删除前检查。"""
        return any(
            [
                await self.attractions.count_by_city(city_id) > 0,
                await self.restaurants.count_by_city(city_id) > 0,
                await self.hotels.count_by_city(city_id) > 0,
            ]
        )


__all__ = [
    "ActivityRepository",
    "AttractionRepository",
    "CatalogRepository",
    "CategoryRepository",
    "HotelRepository",
    "RegionRepository",
    "RestaurantRepository",
]
