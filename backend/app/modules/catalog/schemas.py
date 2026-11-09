"""M11 基础数据的请求/响应模型。

与 ORM 模型分离（架构 §4.3）。
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

from app.modules.catalog.constants import (
    COVER_IMAGE_MAX_LENGTH,
    LATITUDE_MAX,
    LATITUDE_MIN,
    LONGITUDE_MAX,
    LONGITUDE_MIN,
    NAME_MAX_LENGTH,
    SUMMARY_MAX_LENGTH,
    ActivityType,
)

#: 国标行政区划编码：6 位数字（GB/T 2260）
REGION_CODE_PATTERN = r"^\d{6}$"


def _validate_coordinates(lat: Decimal | None, lon: Decimal | None) -> None:
    """坐标成对出现且范围合法。

    只给纬度不给经度（或反之）无法定位，直接拒绝。
    """
    if (lat is None) != (lon is None):
        raise ValueError("经纬度必须同时提供或同时为空")
    if lat is not None and not (LATITUDE_MIN <= lat <= LATITUDE_MAX):
        raise ValueError(f"纬度需在 {LATITUDE_MIN} ~ {LATITUDE_MAX} 之间")
    if lon is not None and not (LONGITUDE_MIN <= lon <= LONGITUDE_MAX):
        raise ValueError(f"经度需在 {LONGITUDE_MIN} ~ {LONGITUDE_MAX} 之间")


# ============================================================
# 地区
# ============================================================


class RegionCreate(BaseModel):
    """创建省份或城市（API §12.2 / §12.6）。"""

    name: str = Field(min_length=1, max_length=50, description="名称")
    code: str = Field(
        pattern=REGION_CODE_PATTERN,
        description="6 位国标行政区划编码（GB/T 2260）",
    )
    parent_id: uuid.UUID | None = Field(default=None, description="上级省份 ID，市级必填")
    description: str | None = Field(default=None, max_length=1000)
    cover_image_url: str | None = Field(default=None, max_length=COVER_IMAGE_MAX_LENGTH)
    heat_score: Decimal = Field(default=Decimal("0"), ge=0, le=100, description="热度 0-100")
    sort_weight: int = Field(default=0)

    @field_validator("cover_image_url")
    @classmethod
    def _check_url(cls, v: str | None) -> str | None:
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("图片地址必须以 http:// 或 https:// 开头")
        return v


class RegionUpdate(RegionCreate):
    """更新省份或城市（API §12.3 / §12.7）。

    **不包含 ``parent_id``**——地区的层级关系不允许通过更新接口修改，
    否则会让已挂在该城市下的景点失去归属。需要调整层级只能删除重建。
    """

    parent_id: None = Field(default=None, exclude=True)


class RegionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    level: int
    code: str
    description: str | None
    cover_image_url: str | None
    heat_score: Decimal
    sort_weight: int
    created_at: datetime
    updated_at: datetime


class ProvinceListItem(RegionResponse):
    """省份列表项（API §12.1）。含 ``city_count``。"""

    city_count: int = 0


class ProvinceListResponse(BaseModel):
    items: list[ProvinceListItem]


class CityListItem(RegionResponse):
    """城市列表项（API §12.5）。含所属省份名称，便于 B 端表格展示。"""

    province_name: str | None = None
    attraction_count: int = 0


# ============================================================
# 景点分类
# ============================================================


class CategoryCreate(BaseModel):
    """创建景点分类（API §12.10）。"""

    name: str = Field(min_length=1, max_length=50)
    category_type: Annotated[str, Field(pattern="^(theme|level)$")]
    parent_id: uuid.UUID | None = Field(default=None, description="上级分类，支持二级")
    description: str | None = Field(default=None, max_length=200)
    sort_weight: int = 0


class CategoryUpdate(CategoryCreate):
    """更新分类。``category_type`` 不可改——更改类型会让已有分类关系语义错乱。"""

    category_type: None = Field(default=None, exclude=True)


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category_type: str
    parent_id: uuid.UUID | None
    description: str | None
    sort_weight: int
    created_at: datetime
    updated_at: datetime


class CategoryWithCount(CategoryResponse):
    """含该分类下的景点数量，用于 B 端展示与删除前提示。"""

    attraction_count: int = 0


# ============================================================
# 景点
# ============================================================


#: 开放时间的星期 key。顺序即前端展示顺序
WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

#: 表示当天闭馆的取值
OPENING_HOURS_CLOSED = "closed"

#: ``HH:mm-HH:mm`` 格式
_TIME_RANGE_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$"

#: 备注长度上限
OPENING_HOURS_NOTE_MAX_LENGTH = 200


class OpeningHours(BaseModel):
    """景点开放时间（``attraction.opening_hours`` JSONB）。

    结构（数据库设计 §3.2）::

        {
          "mon": "09:00-17:00",
          "tue": "09:00-17:00",
          "wed": "closed",
          "note": "16:30 停止入场"
        }

    校验规则：
        - 值只能是 ``HH:mm-HH:mm`` 或 ``closed``
        - 结束时间必须晚于开始时间
        - key 只允许 ``mon``~``sun`` 与 ``note``（禁止脏数据入库）

    **为什么用白名单模型而不是 ``dict[str, Any]``**：
        后者会接受任意结构，比如 ``{"foo": "bar"}``，脏数据一旦入库，
        C 端按星期展示时就会拿到无法解析的内容。
    """

    model_config = ConfigDict(extra="forbid")

    mon: str | None = None
    tue: str | None = None
    wed: str | None = None
    thu: str | None = None
    fri: str | None = None
    sat: str | None = None
    sun: str | None = None
    note: str | None = Field(default=None, max_length=OPENING_HOURS_NOTE_MAX_LENGTH)

    @field_validator(*WEEKDAY_KEYS)
    @classmethod
    def _check_day(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value == OPENING_HOURS_CLOSED:
            return value

        if not re.match(_TIME_RANGE_PATTERN, value):
            raise ValueError(
                f"开放时间格式应为 HH:mm-HH:mm 或 {OPENING_HOURS_CLOSED}，收到：{value}"
            )

        start, end = value.split("-")
        if end <= start:
            raise ValueError(f"结束时间必须晚于开始时间：{value}")
        return value

    @model_validator(mode="after")
    def _check_not_empty(self) -> OpeningHours:
        """至少要有一天的数据或备注，全空没有意义。"""
        has_day = any(getattr(self, key) is not None for key in WEEKDAY_KEYS)
        if not has_day and not self.note:
            raise ValueError("开放时间至少要设置一天或填写备注")
        return self

    @model_serializer(mode="wrap")
    def _drop_empty(self, handler):
        """序列化时丢弃未设置的字段。

        ``model_dump()`` 默认会带上所有 ``None`` 字段，
        存进 JSONB 就是一堆 ``null``，既占空间又让 C 端要处理 null。
        """
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class AttractionCreate(BaseModel):
    """创建景点（API §12.13）。"""

    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    city_id: uuid.UUID
    latitude: Decimal | None = Field(default=None, ge=LATITUDE_MIN, le=LATITUDE_MAX)
    longitude: Decimal | None = Field(default=None, ge=LONGITUDE_MIN, le=LONGITUDE_MAX)
    address: str | None = Field(default=None, max_length=255)
    summary: str | None = Field(default=None, max_length=SUMMARY_MAX_LENGTH)
    description: str | None = None
    image_urls: list[str] | None = Field(default=None, max_length=10)
    ticket_price: Decimal | None = Field(default=None, ge=0)
    opening_hours: OpeningHours | None = None
    visit_duration_minutes: int | None = Field(default=None, ge=1, le=7 * 24 * 60)
    best_seasons: list[str] | None = Field(default=None, max_length=4)
    website: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=50)
    traffic_guide: str | None = None
    base_popularity: Decimal = Field(default=Decimal("50"), ge=0, le=100)
    is_published: bool = True
    sort_weight: int = 0
    #: 分类 ID 列表。创建时一并建立关联关系
    category_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @field_validator("image_urls")
    @classmethod
    def _check_images(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        for url in v:
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"图片地址格式不正确: {url}")
        return v

    @model_validator(mode="after")
    def _check_coordinates(self) -> AttractionCreate:
        """经纬度必须同时提供或同时为空（只给一个无法定位）。"""
        _validate_coordinates(self.latitude, self.longitude)
        return self


class AttractionUpdate(AttractionCreate):
    """更新景点（API §12.14）。``category_ids`` 为空表示清空全部分类关联。"""


class AttractionCategorySetRequest(BaseModel):
    """批量设置景点分类（API §12.17.1）。

    **整体替换语义**：以本列表为准，不在其中的关联被删除。空数组清空全部。
    """

    category_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=10, description="完整分类列表，可为空"
    )


class ActivityPublishRequest(BaseModel):
    """活动上下架（API §12.34）。"""

    is_published: bool


class AttractionListItem(BaseModel):
    """景点列表项（API §12.13 列表）。列表不返回大字段（description/traffic_guide）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    city_id: uuid.UUID
    city_name: str | None = None
    summary: str | None
    cover_image_url: str | None = None
    ticket_price: Decimal | None
    base_popularity: Decimal
    #: 实时热度，来自 popularity_stat；未计算时等于 base_popularity
    final_popularity: Decimal | None = None
    is_published: bool
    sort_weight: int
    categories: list[str] = Field(default_factory=list)
    created_at: datetime


class AttractionDetail(AttractionListItem):
    """景点详情（API §12.14）。列表项 + 完整字段。"""

    latitude: Decimal | None
    longitude: Decimal | None
    address: str | None
    description: str | None
    image_urls: list[str] | None
    opening_hours: dict[str, Any] | None
    visit_duration_minutes: int | None
    best_seasons: list[str] | None
    website: str | None
    phone: str | None
    traffic_guide: str | None
    category_ids: list[uuid.UUID] = Field(default_factory=list)
    updated_at: datetime


# ============================================================
# 餐厅 / 酒店
# ============================================================


class RestaurantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    city_id: uuid.UUID
    cuisine_type: str | None = Field(default=None, max_length=50)
    latitude: Decimal | None = Field(default=None, ge=LATITUDE_MIN, le=LATITUDE_MAX)
    longitude: Decimal | None = Field(default=None, ge=LONGITUDE_MIN, le=LONGITUDE_MAX)
    address: str | None = Field(default=None, max_length=255)
    summary: str | None = None
    avg_cost: Decimal | None = Field(default=None, ge=0)
    business_hours: dict[str, Any] | None = None
    signature_dishes: list[str] | None = None
    image_urls: list[str] | None = None
    need_reservation: bool = False
    phone: str | None = Field(default=None, max_length=50)
    is_published: bool = True


class RestaurantUpdate(RestaurantCreate):
    pass


class RestaurantListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    city_id: uuid.UUID
    city_name: str | None = None
    cuisine_type: str | None
    address: str | None
    avg_cost: Decimal | None
    cover_image_url: str | None = None
    is_published: bool
    created_at: datetime


class HotelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    city_id: uuid.UUID
    star_level: str | None = Field(default=None, max_length=20)
    latitude: Decimal | None = Field(default=None, ge=LATITUDE_MIN, le=LATITUDE_MAX)
    longitude: Decimal | None = Field(default=None, ge=LONGITUDE_MIN, le=LONGITUDE_MAX)
    address: str | None = Field(default=None, max_length=255)
    summary: str | None = None
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    room_types: list[dict[str, Any]] | None = None
    facilities: list[str] | None = None
    image_urls: list[str] | None = None
    booking_url: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=50)
    is_published: bool = True

    @field_validator("max_price")
    @classmethod
    def _check_price_range(cls, v: Decimal | None, info: Any) -> Decimal | None:
        min_price = info.data.get("min_price")
        if v is not None and min_price is not None and v < min_price:
            raise ValueError("最高价不能低于最低价")
        return v


class HotelUpdate(HotelCreate):
    pass


class HotelListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    city_id: uuid.UUID
    city_name: str | None = None
    star_level: str | None
    address: str | None
    min_price: Decimal | None
    max_price: Decimal | None
    is_published: bool
    created_at: datetime


# ============================================================
# 活动
# ============================================================


class TransportCreate(BaseModel):
    """创建景区交通（API §12.29）。

    需求 §2.2.1：**仅景区专属交通**（观光车、索道、缆车等），
    城际交通不进库——由 Agent 的地图 MCP 工具实时查询。
    """

    attraction_id: uuid.UUID = Field(description="所属景点")
    name: str = Field(min_length=1, max_length=100, description="如「景区观光车」")
    transport_type: str | None = Field(
        default=None, max_length=50, description="推荐值见 constants.TransportType"
    )
    price: Decimal | None = Field(default=None, ge=0, description="票价（元）")
    description: str | None = None
    operating_hours: dict[str, Any] | None = None


class TransportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    attraction_id: uuid.UUID
    name: str
    transport_type: str | None
    price: Decimal | None
    description: str | None
    operating_hours: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class ActivityCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    cover_image_url: str | None = Field(default=None, max_length=COVER_IMAGE_MAX_LENGTH)
    activity_type: ActivityType | None = None
    start_date: date
    end_date: date
    city_id: uuid.UUID | None = Field(default=None, description="NULL 表示全国")
    attraction_id: uuid.UUID | None = None
    detail_url: str | None = Field(default=None, max_length=500)
    is_published: bool = True
    sort_weight: int = 0

    @field_validator("end_date")
    @classmethod
    def _check_date_range(cls, v: date, info: Any) -> date:
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("结束日期不能早于开始日期")
        return v


class ActivityUpdate(ActivityCreate):
    pass


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    cover_image_url: str | None
    activity_type: str | None
    start_date: date
    end_date: date
    city_id: uuid.UUID | None
    attraction_id: uuid.UUID | None
    detail_url: str | None
    is_published: bool
    sort_weight: int
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    #: 实时计算的状态（不存库）
    status: str = "upcoming"
