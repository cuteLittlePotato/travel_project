"""M11 基础数据业务逻辑。

事务边界（M0-T02 确认）：本层负责 commit。
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.modules.catalog.constants import (
    ERROR_ACTIVITY_NOT_FOUND,
    ERROR_ATTRACTION_NAME_DUPLICATE,
    ERROR_ATTRACTION_NOT_FOUND,
    ERROR_CATEGORY_IN_USE,
    ERROR_CATEGORY_NAME_DUPLICATE,
    ERROR_CATEGORY_NOT_FOUND,
    ERROR_CITY_NOT_FOUND,
    ERROR_HOTEL_NOT_FOUND,
    ERROR_PROVINCE_NOT_FOUND,
    ERROR_REGION_CODE_DUPLICATE,
    ERROR_REGION_HAS_CHILDREN,
    ERROR_REGION_IN_USE,
    ERROR_RESTAURANT_NOT_FOUND,
    REGION_LEVEL_CITY,
    REGION_LEVEL_PROVINCE,
)
from app.modules.catalog.models import (
    Activity,
    Attraction,
    AttractionCategory,
    Hotel,
    Region,
    Restaurant,
)
from app.modules.catalog.repository import CatalogRepository
from app.modules.catalog.schemas import (
    ActivityCreate,
    ActivityUpdate,
    AttractionCreate,
    AttractionUpdate,
    CategoryCreate,
    CategoryUpdate,
    HotelCreate,
    HotelUpdate,
    RegionCreate,
    RegionUpdate,
    RestaurantCreate,
    RestaurantUpdate,
    TransportCreate,
)
from app.utils.ids import uuid7

logger = logging.getLogger(__name__)


# ============================================================
# 异常
# ============================================================


class RegionCodeDuplicateError(BusinessError):
    def __init__(self) -> None:
        super().__init__(ERROR_REGION_CODE_DUPLICATE, "该行政区划编码已存在", http_status=409)


class RegionHasChildrenError(BusinessError):
    def __init__(self) -> None:
        super().__init__(ERROR_REGION_HAS_CHILDREN, "该省份下仍有城市，无法删除", http_status=409)


class RegionInUseError(BusinessError):
    def __init__(self) -> None:
        super().__init__(
            ERROR_REGION_IN_USE,
            "该城市下仍有景点/餐厅/酒店，无法删除",
            http_status=409,
        )


class RegionNotFoundError(BusinessError):
    def __init__(self, is_province: bool = True) -> None:
        code = ERROR_PROVINCE_NOT_FOUND if is_province else ERROR_CITY_NOT_FOUND
        message = "省份不存在" if is_province else "城市不存在"
        super().__init__(code, message, http_status=404)


class CategoryNameDuplicateError(BusinessError):
    def __init__(self) -> None:
        super().__init__(
            ERROR_CATEGORY_NAME_DUPLICATE, "同类型下的分类名称已存在", http_status=409
        )


class CategoryInUseError(BusinessError):
    def __init__(self) -> None:
        super().__init__(
            ERROR_CATEGORY_IN_USE, "该分类下仍有景点，无法删除", http_status=409
        )


class CategoryNotFoundError(BusinessError):
    def __init__(self) -> None:
        super().__init__(ERROR_CATEGORY_NOT_FOUND, "分类不存在", http_status=404)


class AttractionNameDuplicateError(BusinessError):
    def __init__(self) -> None:
        super().__init__(
            ERROR_ATTRACTION_NAME_DUPLICATE, "该城市下已存在同名景点", http_status=409
        )


class AttractionNotFoundError(BusinessError):
    def __init__(self) -> None:
        super().__init__(ERROR_ATTRACTION_NOT_FOUND, "景点不存在", http_status=404)


class AttractionInUseError(BusinessError):
    """景点被足迹/行程引用，不能删除。HTTP 409 + 21007。"""

    def __init__(self, references: dict[str, int]) -> None:
        detail = "、".join(f"{k} {v} 条" for k, v in references.items() if v > 0)
        super().__init__(
            ERROR_ATTRACTION_NOT_FOUND,
            f"该景点已被引用（{detail}），无法删除",
            data={"references": references},
            http_status=409,
        )


class CategoryIdsInvalidError(BusinessError):
    """category_ids 含不存在的分类。HTTP 400 + 21009。"""

    def __init__(self, invalid_ids: list[str]) -> None:
        super().__init__(
            21009,
            "部分分类不存在",
            data={"errors": [{"field": "category_ids", "reason": f"不存在的分类: {invalid_ids}"}]},
            http_status=400,
        )


class RestaurantNotFoundError(BusinessError):
    def __init__(self) -> None:
        super().__init__(ERROR_RESTAURANT_NOT_FOUND, "餐厅不存在", http_status=404)


class HotelNotFoundError(BusinessError):
    def __init__(self) -> None:
        super().__init__(ERROR_HOTEL_NOT_FOUND, "酒店不存在", http_status=404)


class ActivityNotFoundError(BusinessError):
    def __init__(self) -> None:
        super().__init__(ERROR_ACTIVITY_NOT_FOUND, "活动不存在", http_status=404)


# ============================================================
# 地区
# ============================================================


async def list_provinces(
    session: AsyncSession, *, keyword: str | None = None
) -> dict[str, Any]:
    """省份列表（API §12.1）。

    ``city_count`` 用一次 group by 查询批量取，避免 N+1。
    """
    repo = CatalogRepository(session)
    provinces = await repo.regions.list_provinces(keyword)
    city_counts = await repo.regions.count_cities_by_province()

    items = [
        {
            **{c.name: getattr(p, c.name) for c in Region.__table__.columns},
            "city_count": city_counts.get(p.id, 0),
        }
        for p in provinces
    ]
    return {"items": items}


async def list_cities(
    session: AsyncSession,
    *,
    province_id: uuid.UUID | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """城市列表（API §12.5）。"""
    from app.schemas.pagination import build_page

    repo = CatalogRepository(session)
    cities, total = await repo.regions.list_cities(
        province_id=province_id,
        keyword=keyword,
        offset=(page - 1) * page_size,
        limit=page_size,
    )

    # 批量取省份名称，避免 N+1
    province_ids = {c.parent_id for c in cities if c.parent_id}
    province_names: dict[uuid.UUID, str] = {}
    for pid in province_ids:
        province = await repo.regions.get_by_id(pid)
        if province:
            province_names[pid] = province.name

    items = [
        {
            **{col.name: getattr(c, col.name) for col in Region.__table__.columns},
            "province_name": province_names.get(c.parent_id) if c.parent_id else None,
            "attraction_count": 0,  # 列表不统计，详情页需要时再查
        }
        for c in cities
    ]
    return build_page(items=items, total=total, page=page, page_size=page_size)


async def create_region(
    session: AsyncSession, *, payload: RegionCreate, is_province: bool
) -> Region:
    """创建省份或城市（API §12.2 / §12.6）。

    - 省份：``level=1``，``parent_id`` 必须为空
    - 城市：``level=2``，``parent_id`` 必填且必须指向存在的省份
    """
    repo = CatalogRepository(session)

    if await repo.regions.exists_code(payload.code):
        raise RegionCodeDuplicateError()

    if is_province:
        region = Region(
            id=uuid7(),
            parent_id=None,
            level=REGION_LEVEL_PROVINCE,
            **payload.model_dump(exclude={"parent_id"}),
        )
    else:
        if payload.parent_id is None:
            raise BusinessError(
                ErrorCode.VALIDATION_FAILED,
                "创建城市必须指定所属省份",
                data={"errors": [{"field": "parent_id", "reason": "必填"}]},
            )
        parent = await repo.regions.get_by_id(payload.parent_id)
        if parent is None or parent.level != REGION_LEVEL_PROVINCE:
            raise RegionNotFoundError(is_province=True)

        region = Region(
            id=uuid7(),
            level=REGION_LEVEL_CITY,
            **payload.model_dump(),
        )

    repo.regions.add(region)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        logger.warning("地区编码冲突 code=%s: %s", payload.code, exc)
        raise RegionCodeDuplicateError() from exc

    await session.refresh(region)
    return region


async def update_region(
    session: AsyncSession, *, region_id: uuid.UUID, payload: RegionUpdate, is_province: bool
) -> None:
    """更新省份或城市（API §12.3 / §12.7）。

    ``parent_id`` 不在更新范围内——调整层级会让已挂在该城市下的景点失去归属。
    """
    repo = CatalogRepository(session)
    region = await repo.regions.get_by_id(region_id)
    if region is None:
        raise RegionNotFoundError(is_province)

    expected_level = REGION_LEVEL_PROVINCE if is_province else REGION_LEVEL_CITY
    if region.level != expected_level:
        raise RegionNotFoundError(is_province)

    if await repo.regions.exists_code(payload.code, exclude_id=region_id):
        raise RegionCodeDuplicateError()

    for key, value in payload.model_dump(exclude={"parent_id"}).items():
        setattr(region, key, value)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise RegionCodeDuplicateError() from exc


async def delete_region(
    session: AsyncSession, *, region_id: uuid.UUID, is_province: bool
) -> None:
    """删除省份或城市（API §12.4 / §12.8）。

    保护规则（DoD）：
        - 删除省份：有下级城市 → 21002
        - 删除城市：有景点/餐厅/酒店引用 → 21003
    """
    repo = CatalogRepository(session)
    region = await repo.regions.get_by_id(region_id)
    if region is None:
        raise RegionNotFoundError(is_province)

    expected_level = REGION_LEVEL_PROVINCE if is_province else REGION_LEVEL_CITY
    if region.level != expected_level:
        raise RegionNotFoundError(is_province)

    if is_province:
        if await repo.regions.count_children(region_id) > 0:
            raise RegionHasChildrenError()
    else:
        if await repo.city_in_use(region_id):
            raise RegionInUseError()

    await repo.regions.delete(region)
    await session.commit()


# ============================================================
# 分类
# ============================================================


async def list_categories(
    session: AsyncSession, *, category_type: str | None = None
) -> dict[str, Any]:
    """分类列表（API §12.9）。含每个分类的景点数（批量查询避免 N+1）。"""
    repo = CatalogRepository(session)
    categories = await repo.categories.list_all(category_type)
    counts = await repo.categories.count_attractions_bulk()

    items = [
        {
            **{c.name: getattr(cat, c.name) for c in AttractionCategory.__table__.columns},
            "attraction_count": counts.get(cat.id, 0),
        }
        for cat in categories
    ]
    return {"items": items}


async def create_category(
    session: AsyncSession, *, payload: CategoryCreate
) -> AttractionCategory:
    """创建分类（API §12.10）。同类型下名称唯一。"""
    repo = CatalogRepository(session)

    if await repo.categories.exists_name(payload.name, payload.category_type):
        raise CategoryNameDuplicateError()

    if payload.parent_id is not None:
        parent = await repo.categories.get_by_id(payload.parent_id)
        if parent is None:
            raise CategoryNotFoundError()
        if parent.category_type != payload.category_type:
            raise BusinessError(
                ErrorCode.VALIDATION_FAILED,
                "上级分类的类型必须与当前分类一致",
            )

    category = AttractionCategory(id=uuid7(), **payload.model_dump())
    repo.categories.add(category)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise CategoryNameDuplicateError() from exc

    await session.refresh(category)
    return category


async def update_category(
    session: AsyncSession, *, category_id: uuid.UUID, payload: CategoryUpdate
) -> None:
    repo = CatalogRepository(session)
    category = await repo.categories.get_by_id(category_id)
    if category is None:
        raise CategoryNotFoundError()

    if await repo.categories.exists_name(
        payload.name, category.category_type, exclude_id=category_id
    ):
        raise CategoryNameDuplicateError()

    updates = payload.model_dump(exclude={"category_type"})
    for key, value in updates.items():
        setattr(category, key, value)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise CategoryNameDuplicateError() from exc


async def delete_category(session: AsyncSession, *, category_id: uuid.UUID) -> None:
    """删除分类（API §12.12）。有景点引用时拒绝。"""
    repo = CatalogRepository(session)
    category = await repo.categories.get_by_id(category_id)
    if category is None:
        raise CategoryNotFoundError()

    if await repo.categories.count_attractions(category_id) > 0:
        raise CategoryInUseError()

    await repo.categories.delete(category)
    await session.commit()


# ============================================================
# 景点
# ============================================================


def _cover_image(image_urls: list[str] | None) -> str | None:
    """列表页只需第一张图，避免传输整个数组。"""
    return image_urls[0] if image_urls else None


async def list_attractions(
    session: AsyncSession,
    *,
    city_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    keyword: str | None = None,
    is_published: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """景点列表（API §12.13）。

    列表不返回大字段（description / traffic_guide），只返回列表页需要的。
    """
    from app.schemas.pagination import build_page

    repo = CatalogRepository(session)
    attractions, total = await repo.attractions.list(
        city_id=city_id,
        category_id=category_id,
        keyword=keyword,
        is_published=is_published,
        offset=(page - 1) * page_size,
        limit=page_size,
    )

    # 批量取分类，避免 N+1
    ids = [a.id for a in attractions]
    category_map = await repo.attractions.list_categories_bulk(ids)

    # 批量取实时热度（来自 popularity_stat，未计算时回退到 base_popularity）
    popularity_map = await repo.attractions.get_final_popularity(ids)

    # 批量取城市名
    city_ids = {a.city_id for a in attractions}
    city_names: dict[uuid.UUID, str] = {}
    for cid in city_ids:
        city = await repo.regions.get_by_id(cid)
        if city:
            city_names[cid] = city.name

    # 批量取分类名
    all_category_ids = {c for cs in category_map.values() for c in cs}
    category_names: dict[uuid.UUID, str] = {}
    for cat_id in all_category_ids:
        cat = await repo.categories.get_by_id(cat_id)
        if cat:
            category_names[cat_id] = cat.name

    items = [
        {
            "id": a.id,
            "name": a.name,
            "city_id": a.city_id,
            "city_name": city_names.get(a.city_id),
            "summary": a.summary,
            "cover_image_url": _cover_image(a.image_urls),
            "ticket_price": a.ticket_price,
            "base_popularity": a.base_popularity,
            "final_popularity": popularity_map.get(a.id, a.base_popularity),
            "is_published": a.is_published,
            "sort_weight": a.sort_weight,
            "categories": [
                category_names[c] for c in category_map.get(a.id, []) if c in category_names
            ],
            "created_at": a.created_at,
        }
        for a in attractions
    ]
    return build_page(items=items, total=total, page=page, page_size=page_size)


async def get_attraction(session: AsyncSession, *, attraction_id: uuid.UUID) -> dict[str, Any]:
    """景点详情（API §12.14）。"""
    repo = CatalogRepository(session)
    attraction = await repo.attractions.get_by_id(attraction_id)
    if attraction is None:
        raise AttractionNotFoundError()

    category_ids = await repo.attractions.list_categories(attraction_id)
    city = await repo.regions.get_by_id(attraction.city_id)

    return {
        **{c.name: getattr(attraction, c.name) for c in Attraction.__table__.columns},
        "city_name": city.name if city else None,
        "cover_image_url": _cover_image(attraction.image_urls),
        "categories": [],
        "category_ids": category_ids,
    }


async def create_attraction(
    session: AsyncSession, *, payload: AttractionCreate
) -> Attraction:
    """创建景点（API §12.13）。同城市下名称唯一。"""
    repo = CatalogRepository(session)

    city = await repo.regions.get_by_id(payload.city_id)
    if city is None or city.level != REGION_LEVEL_CITY:
        raise RegionNotFoundError(is_province=False)

    if await repo.attractions.exists_name_in_city(payload.name, payload.city_id):
        raise AttractionNameDuplicateError()

    data = payload.model_dump(exclude={"category_ids"})
    attraction = Attraction(id=uuid7(), **data)
    repo.attractions.add(attraction)

    if payload.category_ids:
        await repo.attractions.replace_categories(attraction.id, payload.category_ids)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AttractionNameDuplicateError() from exc

    await session.refresh(attraction)
    return attraction


async def update_attraction(
    session: AsyncSession, *, attraction_id: uuid.UUID, payload: AttractionUpdate
) -> None:
    """更新景点（API §12.14）。``category_ids`` 为空表示清空全部分类。"""
    repo = CatalogRepository(session)
    attraction = await repo.attractions.get_by_id(attraction_id)
    if attraction is None:
        raise AttractionNotFoundError()

    if await repo.attractions.exists_name_in_city(
        payload.name, payload.city_id, exclude_id=attraction_id
    ):
        raise AttractionNameDuplicateError()

    data = payload.model_dump(exclude={"category_ids"})
    for key, value in data.items():
        setattr(attraction, key, value)

    # 分类关联按传入值整体替换（空列表 = 清空）
    await repo.attractions.replace_categories(attraction_id, payload.category_ids)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AttractionNameDuplicateError() from exc


async def delete_attraction(session: AsyncSession, *, attraction_id: uuid.UUID) -> None:
    """删除景点（API §12.17）。

    **删除前的引用检查**（DoD 要求返回 21007）：
    若景点已被足迹、行程活动或运营活动引用，拒绝删除——
    这些引用代表用户已产生的真实数据（去过的记录、计划里的行程），
    删除景点会让它们变成孤儿。

    未被引用时：先删分类关联（含 popularity_stat 与 transport 的逻辑关联），
    再删景点本身。
    """
    repo = CatalogRepository(session)
    attraction = await repo.attractions.get_by_id(attraction_id)
    if attraction is None:
        raise AttractionNotFoundError()

    references = await repo.attractions.count_references(attraction_id)
    if any(v > 0 for v in references.values()):
        raise AttractionInUseError(references)

    await repo.attractions.replace_categories(attraction_id, [])

    # 清理逻辑关联的附属数据（无物理外键，需手动删）
    from sqlalchemy import text

    await session.execute(
        text("DELETE FROM popularity_stat WHERE attraction_id = :aid"),
        {"aid": attraction_id},
    )
    await session.execute(
        text("DELETE FROM transport WHERE attraction_id = :aid"), {"aid": attraction_id}
    )

    await repo.attractions.delete(attraction)
    await session.commit()


async def set_attraction_categories(
    session: AsyncSession, *, attraction_id: uuid.UUID, category_ids: list[uuid.UUID]
) -> None:
    """批量设置景点分类（API §12.17.1）。

    **整体替换语义**：以请求体为准，不在其中的关联被删除；空数组清空全部。
    所有 category_id 必须存在，否则 21009（400）。
    """
    repo = CatalogRepository(session)

    attraction = await repo.attractions.get_by_id(attraction_id)
    if attraction is None:
        raise AttractionNotFoundError()

    # 校验全部分类存在
    invalid: list[str] = []
    for cid in category_ids:
        if await repo.categories.get_by_id(cid) is None:
            invalid.append(str(cid))
    if invalid:
        raise CategoryIdsInvalidError(invalid)

    await repo.attractions.replace_categories(attraction_id, category_ids)
    await session.commit()


# ============================================================
# 餐厅
# ============================================================


async def list_restaurants(
    session: AsyncSession,
    *,
    city_id: uuid.UUID | None = None,
    keyword: str | None = None,
    is_published: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    from app.schemas.pagination import build_page

    repo = CatalogRepository(session)
    restaurants, total = await repo.restaurants.list(
        city_id=city_id,
        keyword=keyword,
        is_published=is_published,
        offset=(page - 1) * page_size,
        limit=page_size,
    )

    city_ids = {r.city_id for r in restaurants}
    city_names: dict[uuid.UUID, str] = {}
    for cid in city_ids:
        city = await repo.regions.get_by_id(cid)
        if city:
            city_names[cid] = city.name

    items = [
        {
            "id": r.id,
            "name": r.name,
            "city_id": r.city_id,
            "city_name": city_names.get(r.city_id),
            "cuisine_type": r.cuisine_type,
            "address": r.address,
            "avg_cost": r.avg_cost,
            "business_hours": r.business_hours,
            "cover_image_url": _cover_image(r.image_urls),
            "is_published": r.is_published,
            "created_at": r.created_at,
        }
        for r in restaurants
    ]
    return build_page(items=items, total=total, page=page, page_size=page_size)


async def get_restaurant(
    session: AsyncSession, *, restaurant_id: uuid.UUID
) -> dict[str, Any]:
    """餐厅详情（API §12.20.1）。

    返回**全部可编辑字段**，供 B 端编辑表单回填。
    列表接口只返回展示所需字段——两者分离是刻意的：
    列表数据量随记录数增长，详情固定为单条。
    """
    repo = CatalogRepository(session)
    restaurant = await repo.restaurants.get_by_id(restaurant_id)
    if restaurant is None:
        raise RestaurantNotFoundError()

    city = await repo.regions.get_by_id(restaurant.city_id)

    return {
        **{c.name: getattr(restaurant, c.name) for c in Restaurant.__table__.columns},
        "city_name": city.name if city else None,
        "cover_image_url": _cover_image(restaurant.image_urls),
    }


async def create_restaurant(
    session: AsyncSession, *, payload: RestaurantCreate
) -> Restaurant:
    repo = CatalogRepository(session)
    city = await repo.regions.get_by_id(payload.city_id)
    if city is None or city.level != REGION_LEVEL_CITY:
        raise RegionNotFoundError(is_province=False)

    restaurant = Restaurant(id=uuid7(), **payload.model_dump())
    repo.restaurants.add(restaurant)
    await session.commit()
    await session.refresh(restaurant)
    return restaurant


async def update_restaurant(
    session: AsyncSession, *, restaurant_id: uuid.UUID, payload: RestaurantUpdate
) -> None:
    repo = CatalogRepository(session)
    restaurant = await repo.restaurants.get_by_id(restaurant_id)
    if restaurant is None:
        raise RestaurantNotFoundError()

    for key, value in payload.model_dump().items():
        setattr(restaurant, key, value)
    await session.commit()


async def delete_restaurant(session: AsyncSession, *, restaurant_id: uuid.UUID) -> None:
    repo = CatalogRepository(session)
    restaurant = await repo.restaurants.get_by_id(restaurant_id)
    if restaurant is None:
        raise RestaurantNotFoundError()

    await repo.restaurants.delete(restaurant)
    await session.commit()


# ============================================================
# 酒店
# ============================================================


async def list_hotels(
    session: AsyncSession,
    *,
    city_id: uuid.UUID | None = None,
    keyword: str | None = None,
    is_published: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    from app.schemas.pagination import build_page

    repo = CatalogRepository(session)
    hotels, total = await repo.hotels.list(
        city_id=city_id,
        keyword=keyword,
        is_published=is_published,
        offset=(page - 1) * page_size,
        limit=page_size,
    )

    city_ids = {h.city_id for h in hotels}
    city_names: dict[uuid.UUID, str] = {}
    for cid in city_ids:
        city = await repo.regions.get_by_id(cid)
        if city:
            city_names[cid] = city.name

    items = [
        {
            "id": h.id,
            "name": h.name,
            "city_id": h.city_id,
            "city_name": city_names.get(h.city_id),
            "star_level": h.star_level,
            "address": h.address,
            "min_price": h.min_price,
            "max_price": h.max_price,
            "cover_image_url": _cover_image(h.image_urls),
            "is_published": h.is_published,
            "created_at": h.created_at,
        }
        for h in hotels
    ]
    return build_page(items=items, total=total, page=page, page_size=page_size)


async def get_hotel(session: AsyncSession, *, hotel_id: uuid.UUID) -> dict[str, Any]:
    """酒店详情（API §12.24.1）。返回全部可编辑字段。"""
    repo = CatalogRepository(session)
    hotel = await repo.hotels.get_by_id(hotel_id)
    if hotel is None:
        raise HotelNotFoundError()

    city = await repo.regions.get_by_id(hotel.city_id)

    return {
        **{c.name: getattr(hotel, c.name) for c in Hotel.__table__.columns},
        "city_name": city.name if city else None,
        "cover_image_url": _cover_image(hotel.image_urls),
    }


async def create_hotel(session: AsyncSession, *, payload: HotelCreate) -> Hotel:
    repo = CatalogRepository(session)
    city = await repo.regions.get_by_id(payload.city_id)
    if city is None or city.level != REGION_LEVEL_CITY:
        raise RegionNotFoundError(is_province=False)

    hotel = Hotel(id=uuid7(), **payload.model_dump())
    repo.hotels.add(hotel)
    await session.commit()
    await session.refresh(hotel)
    return hotel


async def update_hotel(
    session: AsyncSession, *, hotel_id: uuid.UUID, payload: HotelUpdate
) -> None:
    repo = CatalogRepository(session)
    hotel = await repo.hotels.get_by_id(hotel_id)
    if hotel is None:
        raise HotelNotFoundError()

    for key, value in payload.model_dump().items():
        setattr(hotel, key, value)
    await session.commit()


async def delete_hotel(session: AsyncSession, *, hotel_id: uuid.UUID) -> None:
    repo = CatalogRepository(session)
    hotel = await repo.hotels.get_by_id(hotel_id)
    if hotel is None:
        raise HotelNotFoundError()

    await repo.hotels.delete(hotel)
    await session.commit()


# ============================================================
# 景区交通
# ============================================================


async def list_transports(
    session: AsyncSession, *, attraction_id: uuid.UUID
) -> dict[str, Any]:
    """景区交通列表（API §12.28）。按 ``attraction_id`` 查询。

    需求 §2.2.1：只存**景区专属**交通（观光车/索道/缆车），
    城际交通由 Agent 的地图 MCP 工具实时查询，不入库。
    """
    from sqlalchemy import select

    from app.modules.catalog.models import Transport

    result = await session.execute(
        select(Transport)
        .where(Transport.attraction_id == attraction_id)
        .order_by(Transport.name)
    )
    items = [
        {c.name: getattr(t, c.name) for c in Transport.__table__.columns}
        for t in result.scalars().all()
    ]
    return {"items": items}


async def create_transport(
    session: AsyncSession, *, payload: TransportCreate
) -> Any:
    """创建景区交通（API §12.29）。"""
    from app.modules.catalog.models import Transport

    repo = CatalogRepository(session)
    attraction = await repo.attractions.get_by_id(payload.attraction_id)
    if attraction is None:
        raise AttractionNotFoundError()

    transport = Transport(id=uuid7(), **payload.model_dump())
    session.add(transport)
    await session.commit()
    await session.refresh(transport)
    return transport


async def delete_transport(session: AsyncSession, *, transport_id: uuid.UUID) -> None:
    """删除景区交通（API §12.30）。"""
    from app.modules.catalog.models import Transport

    transport = await session.get(Transport, transport_id)
    if transport is None:
        raise BusinessError(21015, "交通记录不存在", http_status=404)

    await session.delete(transport)
    await session.commit()


# ============================================================
# 活动
# ============================================================


async def list_activities(
    session: AsyncSession,
    *,
    city_id: uuid.UUID | None = None,
    is_published: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    from app.schemas.pagination import build_page

    repo = CatalogRepository(session)
    activities, total = await repo.activities.list(
        city_id=city_id,
        is_published=is_published,
        offset=(page - 1) * page_size,
        limit=page_size,
    )

    items = [
        {
            **{c.name: getattr(a, c.name) for c in Activity.__table__.columns},
            "status": a.status,  # 实时计算
        }
        for a in activities
    ]
    return build_page(items=items, total=total, page=page, page_size=page_size)


async def get_activity(session: AsyncSession, *, activity_id: uuid.UUID) -> dict[str, Any]:
    """活动详情（API §12.31.1）。返回全部可编辑字段。"""
    repo = CatalogRepository(session)
    activity = await repo.activities.get_by_id(activity_id)
    if activity is None:
        raise ActivityNotFoundError()

    city = (
        await repo.regions.get_by_id(activity.city_id)
        if activity.city_id
        else None
    )

    return {
        **{c.name: getattr(activity, c.name) for c in Activity.__table__.columns},
        # status 是 ORM 上的 @property（由日期实时计算），不在 columns 里
        "status": activity.status,
        "city_name": city.name if city else None,
    }


async def create_activity(
    session: AsyncSession, *, payload: ActivityCreate, created_by: uuid.UUID
) -> Activity:
    repo = CatalogRepository(session)
    activity = Activity(
        id=uuid7(),
        created_by=created_by,
        **payload.model_dump(),
    )
    repo.activities.add(activity)
    await session.commit()
    await session.refresh(activity)
    return activity


async def update_activity(
    session: AsyncSession, *, activity_id: uuid.UUID, payload: ActivityUpdate
) -> None:
    repo = CatalogRepository(session)
    activity = await repo.activities.get_by_id(activity_id)
    if activity is None:
        raise ActivityNotFoundError()

    for key, value in payload.model_dump().items():
        setattr(activity, key, value)
    await session.commit()


async def set_activity_published(
    session: AsyncSession, *, activity_id: uuid.UUID, is_published: bool
) -> None:
    """活动上下架（API §12.34）。下架后 C 端不再展示。"""
    repo = CatalogRepository(session)
    activity = await repo.activities.get_by_id(activity_id)
    if activity is None:
        raise ActivityNotFoundError()

    activity.is_published = is_published
    await session.commit()
    logger.info("活动%s activity_id=%s", "上架" if is_published else "下架", activity_id)


async def delete_activity(session: AsyncSession, *, activity_id: uuid.UUID) -> None:
    repo = CatalogRepository(session)
    activity = await repo.activities.get_by_id(activity_id)
    if activity is None:
        raise ActivityNotFoundError()

    await repo.activities.delete(activity)
    await session.commit()


# ============================================================
# 热度（供 M11-T10 数据管道调用）
# ============================================================


async def get_attraction_base_popularity(
    session: AsyncSession, attraction_id: uuid.UUID
) -> Decimal:
    """取景点的基础热度，供热度管道计算使用。

    只读，不 commit。
    """
    repo = CatalogRepository(session)
    attraction = await repo.attractions.get_by_id(attraction_id)
    if attraction is None:
        return Decimal("50")
    return attraction.base_popularity


__all__: list[str] = [
    "ActivityNotFoundError",
    "AttractionInUseError",
    "AttractionNameDuplicateError",
    "AttractionNotFoundError",
    "CategoryIdsInvalidError",
    "CategoryInUseError",
    "CategoryNameDuplicateError",
    "CategoryNotFoundError",
    "HotelNotFoundError",
    "RegionCodeDuplicateError",
    "RegionHasChildrenError",
    "RegionInUseError",
    "RegionNotFoundError",
    "RestaurantNotFoundError",
    "create_activity",
    "create_attraction",
    "create_category",
    "create_hotel",
    "create_region",
    "create_restaurant",
    "create_transport",
    "delete_activity",
    "delete_attraction",
    "delete_category",
    "delete_hotel",
    "delete_region",
    "delete_restaurant",
    "delete_transport",
    "get_attraction",
    "get_attraction_base_popularity",
    "list_activities",
    "list_attractions",
    "list_categories",
    "list_cities",
    "list_hotels",
    "list_provinces",
    "list_restaurants",
    "list_transports",
    "set_activity_published",
    "set_attraction_categories",
    "update_activity",
    "update_attraction",
    "update_category",
    "update_hotel",
    "update_region",
    "update_restaurant",
]
