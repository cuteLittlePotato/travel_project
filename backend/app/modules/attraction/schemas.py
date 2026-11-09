"""M02 景点内容的 C 端响应模型（API §4.1 ~ §4.9）。

与 B 端 ``catalog.schemas`` 分开定义：
    - B 端返回管理字段（``is_published``、``created_by``……），C 端不暴露
    - C 端字段名与 API 契约一一对应（``image_url`` 而非 ``cover_image_url``）
    - 两者演进节奏不同，共用会互相牵制
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RegionBrief(BaseModel):
    """城市简要信息（列表项、筛选栏共用）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str = Field(description="GB/T 2260 行政区划编码")
    level: int = Field(description="1=省，2=市")
    heat_score: Decimal


class CityWithProvince(RegionBrief):
    """详情页的城市，需带上省。"""

    province: RegionBrief | None = None


class CategoryBrief(BaseModel):
    """分类简要信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category_type: Literal["theme", "level"]
    sort_weight: int


class AttractionListItem(BaseModel):
    """景点列表项（API §4.1）。

    ``popularity`` 已由 service 计算好（``popularity_stat`` 优先，
    缺失时回退 ``base_popularity``），前端直接展示，不做二次判断。
    """

    id: uuid.UUID
    name: str
    city: RegionBrief | None
    categories: list[CategoryBrief]
    summary: str | None
    image_url: str | None = Field(description="取 image_urls 第一张")
    ticket_price: Decimal | None
    popularity: float
    recommend_reason: str | None = Field(
        default=None, description="M17 生成，未生成时为 null"
    )


class TransportItem(BaseModel):
    """景区交通（API §4.2 ``transports``）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    transport_type: str | None
    price: Decimal | None
    description: str | None
    operating_hours: dict[str, Any] | None


class RelatedPerson(BaseModel):
    id: uuid.UUID
    name: str
    dynasty: str | None
    relation: str


class RelatedEvent(BaseModel):
    id: uuid.UUID
    name: str
    event_time: str | None
    relation: str


class RelatedCulture(BaseModel):
    id: uuid.UUID
    name: str
    culture_type: str | None


class NearbyAttraction(BaseModel):
    id: uuid.UUID
    name: str
    distance_km: float


class AttractionRelated(BaseModel):
    """详情页的图谱关联（API §4.2）。

    由 M10 知识图谱查询得出，本模块只在 M10 就绪后填充；
    未就绪时各数组为空列表，前端按空态处理。
    """

    persons: list[RelatedPerson] = Field(default_factory=list)
    events: list[RelatedEvent] = Field(default_factory=list)
    cultures: list[RelatedCulture] = Field(default_factory=list)
    nearby_attractions: list[NearbyAttraction] = Field(default_factory=list)


class AttractionDetail(BaseModel):
    """景点详情（API §4.2）。"""

    id: uuid.UUID
    name: str
    city: CityWithProvince | None
    categories: list[CategoryBrief]
    latitude: Decimal | None
    longitude: Decimal | None
    address: str | None
    summary: str | None
    description: str | None = Field(description="富文本 HTML")
    image_urls: list[str]
    ticket_price: Decimal | None
    opening_hours: dict[str, Any] | None
    visit_duration_minutes: int | None
    best_seasons: list[str]
    website: str | None
    phone: str | None
    traffic_guide: str | None
    popularity: float
    transports: list[TransportItem]
    related: AttractionRelated


class CategoryGrouped(BaseModel):
    """分类列表（API §4.6）——按类型分组，前端分开展示筛选项。"""

    themes: list[CategoryBrief]
    levels: list[CategoryBrief]


class RegionList(BaseModel):
    """城市/省份列表（API §4.7）。"""

    items: list[RegionBrief]


class SuggestionItem(BaseModel):
    """搜索建议项（API §4.9）。"""

    type: Literal["attraction", "city"]
    id: uuid.UUID
    text: str
    city: str | None = None


class SuggestionList(BaseModel):
    items: list[SuggestionItem]


# ============================================================
# 发现页（API §4.8）
# ============================================================


class HotKnowledgeGraph(BaseModel):
    """发现页的热门知识图谱卡片。"""

    attraction_id: uuid.UUID
    name: str
    city: RegionBrief | None
    categories: list[CategoryBrief]
    entity_tags: list[str] = Field(
        description="如「3位皇帝」「2个历史事件」，由图谱实体统计生成"
    )
    sort_weight: int


class FeaturedFootprint(BaseModel):
    """发现页的精选足迹。"""

    footprint_id: uuid.UUID
    attraction_name: str
    author_nickname: str
    rating: int | None
    review_excerpt: str | None
    image_url: str | None


class RecommendedActivity(BaseModel):
    """发现页的推荐活动（API §4.8）。

    ``status`` 由 ``start_date``/``end_date`` 与当天日期实时计算，
    与 B 端的 ``Activity.status`` 属性同一套规则。
    """

    id: uuid.UUID
    title: str
    cover_image_url: str | None
    description: str | None
    activity_type: str | None
    start_date: date
    end_date: date
    status: Literal["upcoming", "ongoing", "ended"]
    city: RegionBrief | None
    detail_url: str | None


class DiscoverContent(BaseModel):
    """发现页聚合响应（API §4.8）。"""

    hot_knowledge_graphs: list[HotKnowledgeGraph]
    featured_footprints: list[FeaturedFootprint]
    recommended_activities: list[RecommendedActivity]
