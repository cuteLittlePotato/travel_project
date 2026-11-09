"""M11 基础数据的枚举与常量。

与 ``scripts/sql/schema.sql`` 中的 CHECK 约束一一对应。
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum


class RegionLevel(StrEnum):
    """行政区划层级（``region.level``）。

    只支持两级：省 / 市。需求未要求区县级别。
    """

    PROVINCE = "1"
    CITY = "2"


#: ``region.level`` 是 SMALLINT，用整数而非字符串
REGION_LEVEL_PROVINCE = 1
REGION_LEVEL_CITY = 2


class CategoryType(StrEnum):
    """分类类型（``attraction_category.category_type``）。

    - ``theme``：主题分类（历史人文、自然风光…）
    - ``level``：等级分类（5A、4A…）
    """

    THEME = "theme"
    LEVEL = "level"


class ActivityType(StrEnum):
    """活动类型（``activity.activity_type``）。"""

    DISCOUNT = "discount"
    FESTIVAL = "festival"
    EXHIBITION = "exhibition"
    OTHER = "other"


class TransportType(StrEnum):
    """景区交通方式（``transport.transport_type``）。

    **注意**：数据库该字段没有 CHECK 约束（`VARCHAR(50)`），
    这里的枚举是**推荐值**，允许运营输入其他方式（如「摆渡车」）。
    前端下拉框用本枚举做建议选项，后端不做强校验。
    """

    WALK = "walk"
    BUS = "bus"
    SUBWAY = "subway"
    TAXI = "taxi"
    BOAT = "boat"
    CABLE_CAR = "cable_car"
    TRAIN = "train"


class HotelStarLevel(StrEnum):
    """酒店星级（``hotel.star_level``）。

    同样是推荐值，数据库无 CHECK 约束。
    """

    FIVE = "five"
    FOUR = "four"
    THREE = "three"
    TWO = "two"
    ONE = "one"
    BOUTIQUE = "boutique"


# ============================================================
# 业务常量
# ============================================================

#: 景点基础热度默认值（``attraction.base_popularity`` 的 DDL 默认值）
DEFAULT_BASE_POPULARITY = Decimal("50.00")

#: 热度最终分默认值（``popularity_stat.final_popularity``）
DEFAULT_FINAL_POPULARITY = Decimal("50.00")

#: 名称最大长度（``attraction.name`` / ``restaurant.name`` / ``hotel.name``）
NAME_MAX_LENGTH = 100

#: 简介最大长度（``attraction.summary``）
SUMMARY_MAX_LENGTH = 200

#: 封面图 URL 最大长度
COVER_IMAGE_MAX_LENGTH = 500

#: 单条记录最多图片数（``image_urls`` JSONB 数组）
MAX_IMAGE_COUNT = 10

#: 定位坐标精度（``NUMERIC(10, 7)``）
COORDINATE_DECIMAL_PLACES = 7

#: 纬度范围
LATITUDE_MIN = Decimal("-90")
LATITUDE_MAX = Decimal("90")

#: 经度范围
LONGITUDE_MIN = Decimal("-180")
LONGITUDE_MAX = Decimal("180")

#: 批量导入单次最多条数（M11-T05）
IMPORT_MAX_ROWS = 1000

#: 导出单次最多条数
EXPORT_MAX_ROWS = 10000


# ============================================================
# M11 错误码（码段 21000-21999，API §1.7）
# ============================================================

#: 行政区划编码已存在
ERROR_REGION_CODE_DUPLICATE = 21001
#: 省份下仍有城市，不能删除
ERROR_REGION_HAS_CHILDREN = 21002
#: 城市被景点/餐厅/酒店引用，不能删除
ERROR_REGION_IN_USE = 21003
#: 分类名称重复（同类型下）
ERROR_CATEGORY_NAME_DUPLICATE = 21004
#: 分类下仍有景点，不能删除
ERROR_CATEGORY_IN_USE = 21005
#: 景点名称在该城市下重复
ERROR_ATTRACTION_NAME_DUPLICATE = 21006
#: 景点不存在
ERROR_ATTRACTION_NOT_FOUND = 21007
#: 餐厅不存在
ERROR_RESTAURANT_NOT_FOUND = 21008
#: 酒店不存在
ERROR_HOTEL_NOT_FOUND = 21009
#: 活动不存在
ERROR_ACTIVITY_NOT_FOUND = 21010
#: 活动日期非法（结束早于开始）
ERROR_ACTIVITY_DATE_INVALID = 21011
#: 城市不存在
ERROR_CITY_NOT_FOUND = 21012
#: 省份不存在
ERROR_PROVINCE_NOT_FOUND = 21013
#: 分类不存在
ERROR_CATEGORY_NOT_FOUND = 21014
