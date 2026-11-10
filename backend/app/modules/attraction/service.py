"""M02 景点内容的 C 端业务逻辑（API §4.1 ~ §4.9）。

职责边界：
    - Repository 只取数据，本层负责**组装响应**（补城市名、分类、热度回退）
    - 热度回退、空值兜底这类业务规则在此，不污染查询层
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, NotFoundError
from app.modules.attraction.repository import (
    SUPPORTED_SORT_FIELDS,
    AttractionQueryRepository,
)
from app.modules.attraction.schemas import (
    AttractionDetail,
    AttractionListItem,
    AttractionRelated,
    CategoryBrief,
    CategoryGrouped,
    CityWithProvince,
    RegionBrief,
    RegionList,
    SuggestionItem,
    SuggestionList,
    TransportItem,
)
from app.modules.catalog.models import Attraction, AttractionCategory, Region

logger = logging.getLogger(__name__)


# ============================================================
# 错误码（M02 段 12000-12999）
# ============================================================

ERROR_ATTRACTION_NOT_FOUND = 12001
ERROR_ATTRACTION_OFFLINE = 12002  # 未上架，C 端视同不存在


class AttractionNotFoundError(NotFoundError):
    """景点不存在或未上架（API §4.2）。

    **不区分「不存在」与「未上架」**：对 C 端用户而言两者都是
    「看不到这个景点」，区分会让人能探测哪些景点存在但被下架。
    """

    def __init__(self) -> None:
        super().__init__("景点不存在", code=ERROR_ATTRACTION_NOT_FOUND)


# ============================================================
# 序列化辅助
# ============================================================


def _region_brief(region: Region | None) -> RegionBrief | None:
    if region is None:
        return None
    return RegionBrief.model_validate(region)


def _category_brief(category: AttractionCategory) -> CategoryBrief:
    return CategoryBrief(
        id=category.id,
        name=category.name,
        category_type=category.category_type,  # type: ignore[arg-type]
        sort_weight=category.sort_weight,
    )


def _cover_image(image_urls: list[str] | None) -> str | None:
    """取第一张作为封面。"""
    return image_urls[0] if image_urls else None


def _effective_popularity(
    attraction: Attraction, stat_value: Decimal | None
) -> float:
    """热度：``popularity_stat.final_popularity`` 优先，缺失时回退 ``base_popularity``。

    ``popularity_stat`` 由 M11-T10 的数据管道维护。景点刚创建时
    还没有统计记录，此时不能显示 0——那会让新景点看起来最冷门，
    而它只是还没有行为数据。
    """
    value = stat_value if stat_value is not None else attraction.base_popularity
    return float(value)


# ============================================================
# 列表（API §4.1）
# ============================================================


async def list_attractions(
    session: AsyncSession,
    *,
    keyword: str | None = None,
    city_id: uuid.UUID | None = None,
    province_id: uuid.UUID | None = None,
    category_ids: list[uuid.UUID] | None = None,
    sort_by: str = "popularity",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """C 端景点列表（API §4.1）。

    仅返回已上架景点。分类筛选为「且」关系。
    """
    if sort_by not in SUPPORTED_SORT_FIELDS:
        raise BusinessError(10001, f"不支持的排序字段：{sort_by}", http_status=400)

    repo = AttractionQueryRepository(session)
    items, total = await repo.list_published(
        keyword=keyword,
        city_id=city_id,
        province_id=province_id,
        category_ids=category_ids,
        sort_by=sort_by,
        sort_order=sort_order,
        offset=(page - 1) * page_size,
        limit=page_size,
    )

    # 批量补全，避免 N+1
    ids = [item.id for item in items]
    cities = await repo.get_regions_bulk([item.city_id for item in items])
    categories_map = await repo.get_categories_bulk(ids)
    popularity_map = await repo.get_popularity_bulk(ids)

    payload = []
    for item in items:
        categories = [
            _category_brief(c) for c in categories_map.get(item.id, [])
        ]
        payload.append(
            AttractionListItem(
                id=item.id,
                name=item.name,
                city=_region_brief(cities.get(item.city_id)),
                categories=categories,
                summary=item.summary,
                image_url=_cover_image(item.image_urls),
                ticket_price=item.ticket_price,
                popularity=_effective_popularity(
                    item, popularity_map.get(item.id)
                ),
                # M17 尚未开发，推荐理由恒为 null
                recommend_reason=None,
            ).model_dump(mode="json")
        )

    return {
        "items": payload,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


# ============================================================
# 详情（API §4.2）
# ============================================================


async def get_attraction_detail(
    session: AsyncSession, *, attraction_id: uuid.UUID
) -> dict[str, Any]:
    """景点详情（API §4.2）。

    未上架景点视同不存在（12001）。

    ``related`` 由 M10 知识图谱提供。**M10 尚未开发**，本任务先返回
    空数组——前端按空态处理，不会因此报错。M02-T06 接入后填充。
    """
    repo = AttractionQueryRepository(session)

    attraction = await repo.get_published_by_id(attraction_id)
    if attraction is None:
        raise AttractionNotFoundError()

    categories = await repo.get_categories(attraction_id)
    transports = await repo.list_transports(attraction_id)
    stat = await repo.get_popularity(attraction_id)

    # 城市 + 省份
    regions = await repo.get_regions_bulk([attraction.city_id])
    city = regions.get(attraction.city_id)
    province = (
        regions.get(city.parent_id) if city and city.parent_id else None
    )
    if province is None and city and city.parent_id:
        # 省份不在首批查询结果里（只查了城市 ID），单独补
        province_map = await repo.get_regions_bulk([city.parent_id])
        province = province_map.get(city.parent_id)

    city_payload = None
    if city is not None:
        city_payload = CityWithProvince(
            **_region_brief(city).model_dump(),  # type: ignore[union-attr]
            province=_region_brief(province),
        )

    detail = AttractionDetail(
        id=attraction.id,
        name=attraction.name,
        city=city_payload,
        categories=[_category_brief(c) for c in categories],
        latitude=attraction.latitude,
        longitude=attraction.longitude,
        address=attraction.address,
        summary=attraction.summary,
        description=attraction.description,
        image_urls=attraction.image_urls or [],
        ticket_price=attraction.ticket_price,
        opening_hours=attraction.opening_hours,
        visit_duration_minutes=attraction.visit_duration_minutes,
        best_seasons=attraction.best_seasons or [],
        website=attraction.website,
        phone=attraction.phone,
        traffic_guide=attraction.traffic_guide,
        popularity=_effective_popularity(attraction, stat),
        transports=[TransportItem.model_validate(t) for t in transports],
        related=AttractionRelated(),
    )
    return detail.model_dump(mode="json")


# ============================================================
# 分类与地区字典（API §4.6 / §4.7）
# ============================================================


async def list_categories(session: AsyncSession) -> dict[str, Any]:
    """分类列表（API §4.6）。

    按 ``category_type`` 分组返回，前端分开展示筛选项。
    """
    repo = AttractionQueryRepository(session)
    categories = await repo.list_categories_grouped()

    themes = [
        _category_brief(c) for c in categories if c.category_type == "theme"
    ]
    levels = [
        _category_brief(c) for c in categories if c.category_type == "level"
    ]

    return CategoryGrouped(themes=themes, levels=levels).model_dump(mode="json")


async def list_regions(
    session: AsyncSession,
    *,
    level: int | None = None,
    parent_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """地区列表（API §4.7）。"""
    repo = AttractionQueryRepository(session)
    regions = await repo.list_regions(level=level, parent_id=parent_id)

    items = [
        brief for region in regions if (brief := _region_brief(region)) is not None
    ]
    return RegionList(items=items).model_dump(mode="json")


# ============================================================
# 搜索建议（API §4.9）
# ============================================================


async def suggest(
    session: AsyncSession, *, keyword: str, limit: int = 10
) -> dict[str, Any]:
    """搜索建议（API §4.9）。

    返回景点与地区混合列表。地区**包含省份与城市**——
    搜「浙江」的用户想找的是整个省，只返回城市会漏掉这类意图。
    """
    repo = AttractionQueryRepository(session)
    attractions, regions = await repo.suggest(keyword, limit=limit)

    # 景点建议需要城市名做副标题
    cities = await repo.get_regions_bulk([a.city_id for a in attractions])

    items: list[SuggestionItem] = []

    for attraction in attractions:
        city = cities.get(attraction.city_id)
        items.append(
            SuggestionItem(
                type="attraction",
                id=attraction.id,
                text=attraction.name,
                city=city.name if city else None,
            )
        )

    for region in regions:
        items.append(
            SuggestionItem(
                type="city",
                id=region.id,
                text=region.name,
                city=None,
            )
        )

    return SuggestionList(items=items).model_dump(mode="json")
