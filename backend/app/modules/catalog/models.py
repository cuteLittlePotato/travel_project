"""M11 基础数据的 ORM 模型。

对应 ``scripts/sql/schema.sql`` 的九张表：
    region / attraction_category / attraction / attraction_category_relation
    restaurant / hotel / transport / activity / popularity_stat

规范（docs/rules/database-rules.md）：
    - 主键 UUID，命名 ``id``
    - 时间统一 TIMESTAMPTZ
    - **禁止物理外键**：表间关系用逻辑关联字段表达

基类选择依据（各表的时间字段不同）：
    | 表 | 时间字段 | 基类 |
    |---|---|---|
    | region / attraction_category / attraction / restaurant / hotel / transport / activity | created + updated | ``BaseModel`` |
    | popularity_stat | 仅 updated_at | ``UUIDPrimaryKeyMixin + UpdatedAtMixin + Base`` |
    | attraction_category_relation | 仅 created_at | ``UUIDPrimaryKeyMixin + CreatedAtMixin + Base`` |
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BaseModel, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin
from app.modules.catalog.constants import ActivityType

# ============================================================
# region
# ============================================================


class Region(BaseModel):
    """行政区划（省 / 市两级）。

    ``parent_id`` 指向省级记录的 id，市级记录的 ``parent_id`` 必填。
    省 / 市都可能有独立的封面图与热度（用于首页地区入口）。
    """

    __tablename__ = "region"
    __table_args__ = (
        Index("uk_region_code", "code", unique=True),
        Index("idx_region_parent_id", "parent_id"),
        Index("idx_region_level", "level"),
        CheckConstraint("level IN (1, 2)", name="ck_region_level"),
        {"comment": "省市行政区划"},
    )

    parent_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    #: 1 = 省级，2 = 市级
    level: Mapped[int] = mapped_column(
        SmallInteger, nullable=False,
        comment='层级：1=省，2=市',
    )
    #: GB/T 2260 行政区划编码
    code: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment='行政区划编码',
    )
    description: Mapped[str | None] = mapped_column(Text)
    cover_image_url: Mapped[str | None] = mapped_column(String(500))
    heat_score: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="0"
    )
    sort_weight: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    def __repr__(self) -> str:
        return f"<Region {self.name} level={self.level}>"


# ============================================================
# attraction_category
# ============================================================


class AttractionCategory(BaseModel):
    """景点分类。

    两类：``theme``（主题，如历史人文）与 ``level``（等级，如 5A）。
    同一类型下名称唯一。
    """

    __tablename__ = "attraction_category"
    __table_args__ = (
        Index("uk_attr_cat_type_name", "category_type", "name", unique=True),
        Index("idx_attr_cat_type", "category_type", "sort_weight"),
        Index("idx_attr_cat_parent", "parent_id"),
        CheckConstraint("category_type IN ('theme', 'level')", name="category_type"),
        {"comment": "景点分类字典（B端维护）"},
    )

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    category_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment='分类类型：theme=主题类型（历史人文/自然景色），level=等级称号（5A景区/世界遗产）',
    )
    #: 主题分类可分级（如「人文」下分「古迹」「博物馆」），等级分类不分级
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        comment='上级分类，支持二级分类',
    )
    description: Mapped[str | None] = mapped_column(String(200))
    sort_weight: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    def __repr__(self) -> str:
        return f"<AttractionCategory {self.category_type}:{self.name}>"


# ============================================================
# attraction
# ============================================================


class Attraction(BaseModel):
    """景点主表。

    ``image_urls`` / ``opening_hours`` / ``best_seasons`` 均为 JSONB：
    - ``image_urls``: ``["https://...", ...]``
    - ``opening_hours``: ``{"weekday": "08:00-17:00", "weekend": "08:00-18:00"}``
      或 ``{"note": "全天开放"}``
    - ``best_seasons``: ``["春季", "秋季"]``

    ``base_popularity`` 是**运营配置的基础分**，与 ``popularity_stat``
    的实时热度分开存——前者不被定时任务覆盖。
    """

    __tablename__ = "attraction"
    __table_args__ = (
        Index("uk_attraction_name_city", "name", "city_id", unique=True),
        Index("idx_attraction_city_id", "city_id"),
        Index("idx_attraction_published", "is_published", text("sort_weight DESC")),
        Index("idx_attraction_geo", "latitude", "longitude"),
        {"comment": "景点信息"},
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    city_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    address: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    image_urls: Mapped[list[str] | None] = mapped_column(JSONB)
    ticket_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    opening_hours: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        comment='开放时间，如 {"mon":"09:00-17:00"}',
    )
    visit_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    best_seasons: Mapped[list[str] | None] = mapped_column(JSONB)
    website: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(50))
    traffic_guide: Mapped[str | None] = mapped_column(Text)
    #: 运营配置的基础热度，与 popularity_stat 的实时分独立
    base_popularity: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="50",
        comment='基础热度权重（运营配置，0-100）',
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    sort_weight: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    def __repr__(self) -> str:
        return f"<Attraction {self.name}>"


# ============================================================
# attraction_category_relation
# ============================================================


class AttractionCategoryRelation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """景点与分类的多对多关联。

    没有 ``updated_at``——关系变更即删除重建。
    """

    __tablename__ = "attraction_category_relation"
    __table_args__ = (
        Index("uk_attr_cat_rel", "attraction_id", "category_id", unique=True),
        Index("idx_attr_cat_rel_attraction", "attraction_id"),
        Index("idx_attr_cat_rel_category", "category_id"),
        {"comment": "景点与分类的关联（多对多）"},
    )

    attraction_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)


# ============================================================
# restaurant
# ============================================================


class Restaurant(BaseModel):
    """餐厅。"""

    __tablename__ = "restaurant"
    __table_args__ = (
        Index("idx_restaurant_city_id", "city_id"),
        Index("idx_restaurant_cuisine", "cuisine_type"),
        Index("idx_restaurant_geo", "latitude", "longitude"),
        {"comment": "餐厅信息"},
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    city_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    cuisine_type: Mapped[str | None] = mapped_column(String(50))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    address: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    avg_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        comment='人均消费（元）',
    )
    business_hours: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    signature_dishes: Mapped[list[str] | None] = mapped_column(JSONB)
    image_urls: Mapped[list[str] | None] = mapped_column(JSONB)
    need_reservation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    phone: Mapped[str | None] = mapped_column(String(50))
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    def __repr__(self) -> str:
        return f"<Restaurant {self.name}>"


# ============================================================
# hotel
# ============================================================


class Hotel(BaseModel):
    """酒店。"""

    __tablename__ = "hotel"
    __table_args__ = (
        Index("idx_hotel_city_id", "city_id"),
        Index("idx_hotel_star", "star_level"),
        Index("idx_hotel_geo", "latitude", "longitude"),
        {"comment": "酒店信息"},
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    city_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    star_level: Mapped[str | None] = mapped_column(
        String(20),
        comment='星级：5星级/4星级/3星级/经济型/精品酒店/民宿',
    )
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    address: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    max_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    room_types: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB
    )
    facilities: Mapped[list[str] | None] = mapped_column(JSONB)
    image_urls: Mapped[list[str] | None] = mapped_column(JSONB)
    booking_url: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(50))
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    def __repr__(self) -> str:
        return f"<Hotel {self.name}>"


# ============================================================
# transport
# ============================================================


class Transport(BaseModel):
    """景区交通方式（如「景区内有观光车」）。

    ``transport_type`` 数据库无 CHECK 约束，是自由文本，
    推荐值见 ``constants.TransportType``。
    """

    __tablename__ = "transport"
    __table_args__ = (
        Index("idx_transport_attraction_id", "attraction_id"),
        {"comment": "景区专属交通（观光车、索道等），城际交通不入库"},
    )

    attraction_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    transport_type: Mapped[str | None] = mapped_column(String(50))
    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    description: Mapped[str | None] = mapped_column(Text)
    operating_hours: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    def __repr__(self) -> str:
        return f"<Transport {self.name}>"


# ============================================================
# activity
# ============================================================


class Activity(BaseModel):
    """运营活动。

    **状态不存库**——活动是否进行中由 ``start_date`` / ``end_date``
    与当前日期实时计算（API 设计 §17.1 决策）。
    这样避免定时任务滞后导致状态不准。
    """

    __tablename__ = "activity"
    __table_args__ = (
        Index("idx_activity_published", "is_published", text("sort_weight DESC")),
        # 两个部分索引：只为有值的行建索引，减小体积
        Index(
            "idx_activity_dates",
            "start_date",
            "end_date",
            postgresql_where=text("is_published = TRUE"),
        ),
        Index(
            "idx_activity_city",
            "city_id",
            postgresql_where=text("city_id IS NOT NULL"),
        ),
        Index(
            "idx_activity_attraction",
            "attraction_id",
            postgresql_where=text("attraction_id IS NOT NULL"),
        ),
        CheckConstraint(
            f"activity_type IN ({', '.join(repr(v.value) for v in ActivityType)})",
            name="activity_type",
        ),
        CheckConstraint("end_date >= start_date", name="activity_date"),
        {"comment": "旅游活动（发现页推荐用）"},
    )

    # 重写 id 仅为加注释（继承自 UUIDPrimaryKeyMixin，语义不变）
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        comment="活动状态（未开始/进行中/已结束）由 start_date、end_date 与当前时间实时计算，不单独存储",
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    cover_image_url: Mapped[str | None] = mapped_column(String(500))
    activity_type: Mapped[str | None] = mapped_column(
        String(50),
        comment='类型：discount=特惠，festival=节庆，exhibition=展览，other=其他',
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: 目标城市，NULL 表示全国
    city_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        comment='目标城市，NULL 表示全国性活动',
    )
    #: 关联景点，NULL 表示不限定
    attraction_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        comment='关联景点，NULL 表示不限定',
    )
    detail_url: Mapped[str | None] = mapped_column(
        String(500),
        comment='活动详情页外部链接，价格等信息在此页面展示',
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    sort_weight: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )

    @property
    def status(self) -> str:
        """实时计算活动状态（不存库）。

        - ``upcoming``：未开始
        - ``ongoing``：进行中
        - ``ended``：已结束
        """
        today = date.today()
        if today < self.start_date:
            return "upcoming"
        if today > self.end_date:
            return "ended"
        return "ongoing"

    def __repr__(self) -> str:
        return f"<Activity {self.title}>"


# ============================================================
# popularity_stat
# ============================================================


class PopularityStat(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    """景点热度统计。

    与 ``attraction.base_popularity`` 的关系（评审 §Q5）：
        - ``base_popularity``：运营配置的基础分，**不被定时任务覆盖**
        - ``final_popularity``：由数据管道（M11-T10）调用 M17-T02 的
          纯算法计算得出，写入本表

    只有 ``updated_at``，没有 ``created_at``——本表随景点创建而生成，
    创建时间即景点创建时间，无独立语义。
    """

    __tablename__ = "popularity_stat"
    __table_args__ = (
        Index("uk_popularity_attraction", "attraction_id", unique=True),
        Index("idx_popularity_final", text("final_popularity DESC")),
        {"comment": "景点热度统计"},
    )

    attraction_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    click_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    plan_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rating_sum: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    #: 行为分（由 M17-T02 算法计算，0-100）
    behavior_score: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="0",
        comment='用户行为得分（0-100）',
    )
    #: 最终热度 = base_popularity × 0.6 + behavior_score × 0.4
    final_popularity: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="50",
        comment='最终热度 = base_popularity * 0.6 + behavior_score * 0.4',
    )

    def __repr__(self) -> str:
        return f"<PopularityStat attraction={self.attraction_id} score={self.final_popularity}>"


__all__ = [
    "Activity",
    "Attraction",
    "AttractionCategory",
    "AttractionCategoryRelation",
    "Hotel",
    "PopularityStat",
    "Region",
    "Restaurant",
    "Transport",
]
