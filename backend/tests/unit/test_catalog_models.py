"""M11 基础数据 ORM 模型的测试（M11-T01）。

CLAUDE.md §5.1 要求：模型必须与数据库 DDL 差异归零。
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.db.base import Base
from app.modules.catalog.constants import CategoryType, RegionLevel
from app.modules.catalog.models import (
    Activity,
    Attraction,
    AttractionCategory,
    AttractionCategoryRelation,
    Hotel,
    PopularityStat,
    Region,
    Restaurant,
    Transport,
)

EXPECTED_TABLES = {
    "region",
    "attraction_category",
    "attraction",
    "attraction_category_relation",
    "restaurant",
    "hotel",
    "transport",
    "activity",
    "popularity_stat",
}

ALL_MODELS = (
    Region,
    AttractionCategory,
    Attraction,
    AttractionCategoryRelation,
    Restaurant,
    Hotel,
    Transport,
    Activity,
    PopularityStat,
)


def _columns(model: type) -> set[str]:
    return {c.name for c in model.__table__.columns}


# ============================================================
# 表结构
# ============================================================


class TestTableStructure:
    def test_all_nine_tables_registered(self) -> None:
        registered = set(Base.metadata.tables)
        assert registered >= EXPECTED_TABLES, f"缺少: {EXPECTED_TABLES - registered}"

    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            (Region, {"id", "parent_id", "name", "level", "code", "description",
                      "cover_image_url", "heat_score", "sort_weight",
                      "created_at", "updated_at"}),
            (AttractionCategory, {"id", "name", "category_type", "parent_id",
                                  "description", "sort_weight", "created_at", "updated_at"}),
            (AttractionCategoryRelation, {"id", "attraction_id", "category_id", "created_at"}),
            (PopularityStat, {"id", "attraction_id", "view_count", "click_count",
                              "plan_count", "rating_sum", "rating_count",
                              "behavior_score", "final_popularity", "updated_at"}),
        ],
    )
    def test_columns_match_ddl(self, model: type, expected: set[str]) -> None:
        assert _columns(model) == expected

    def test_attraction_columns(self) -> None:
        cols = _columns(Attraction)
        assert cols == {
            "id", "name", "city_id", "latitude", "longitude", "address", "summary",
            "description", "image_urls", "ticket_price", "opening_hours",
            "visit_duration_minutes", "best_seasons", "website", "phone",
            "traffic_guide", "base_popularity", "is_published", "sort_weight",
            "created_at", "updated_at",
        }

    def test_activity_columns(self) -> None:
        cols = _columns(Activity)
        assert cols == {
            "id", "title", "description", "cover_image_url", "activity_type",
            "start_date", "end_date", "city_id", "attraction_id", "detail_url",
            "is_published", "sort_weight", "created_by", "created_at", "updated_at",
        }

    def test_primary_keys_are_uuid(self) -> None:
        from sqlalchemy.dialects.postgresql import UUID as PGUUID

        for model in ALL_MODELS:
            pk = next(iter(model.__table__.primary_key.columns))
            assert pk.name == "id"
            assert isinstance(pk.type, PGUUID)


class TestTimestampColumns:
    """各表的时间字段不同，基类选择必须对应。"""

    def test_tables_with_both_timestamps(self) -> None:
        for model in (
            Region, AttractionCategory, Attraction, Restaurant, Hotel, Transport, Activity
        ):
            cols = _columns(model)
            assert "created_at" in cols, f"{model.__name__} 缺 created_at"
            assert "updated_at" in cols, f"{model.__name__} 缺 updated_at"

    def test_popularity_stat_only_updated_at(self) -> None:
        cols = _columns(PopularityStat)
        assert "updated_at" in cols
        assert "created_at" not in cols

    def test_category_relation_only_created_at(self) -> None:
        cols = _columns(AttractionCategoryRelation)
        assert "created_at" in cols
        assert "updated_at" not in cols


# ============================================================
# 约束
# ============================================================


class TestConstraints:
    def test_no_physical_foreign_key(self) -> None:
        """DoD：模型不得声明物理外键。"""
        for model in ALL_MODELS:
            assert not model.__table__.foreign_keys, f"{model.__name__} 含物理外键"

    def test_no_relationship_declaration(self) -> None:
        from pathlib import Path

        source = Path(__file__).resolve().parents[2] / "app" / "modules" / "catalog" / "models.py"
        assert "relationship(" not in source.read_text(encoding="utf-8")

    def test_unique_indexes(self) -> None:
        """DDL 用 CREATE UNIQUE INDEX，模型必须用 Index(unique=True)。"""
        expected = {
            "region": "uk_region_code",
            "attraction_category": "uk_attr_cat_type_name",
            "attraction": "uk_attraction_name_city",
            "attraction_category_relation": "uk_attr_cat_rel",
            "popularity_stat": "uk_popularity_attraction",
        }
        for table_name, index_name in expected.items():
            table = Base.metadata.tables[table_name]
            unique_indexes = {
                idx.name for idx in table.indexes if idx.unique
            }
            assert index_name in unique_indexes, f"{table_name} 缺少 {index_name}"

    def test_region_level_check(self) -> None:
        checks = [
            str(c.sqltext) for c in Region.__table__.constraints
            if type(c).__name__ == "CheckConstraint"
        ]
        assert any("level IN (1, 2)" in c for c in checks)

    def test_category_type_check(self) -> None:
        checks = [
            str(c.sqltext) for c in AttractionCategory.__table__.constraints
            if type(c).__name__ == "CheckConstraint"
        ]
        assert any("theme" in c and "level" in c for c in checks)

    def test_activity_type_check(self) -> None:
        checks = [
            str(c.sqltext) for c in Activity.__table__.constraints
            if type(c).__name__ == "CheckConstraint"
        ]
        sql = " ".join(checks)
        for value in ("discount", "festival", "exhibition", "other"):
            assert value in sql

    def test_activity_date_check(self) -> None:
        checks = [
            str(c.sqltext) for c in Activity.__table__.constraints
            if type(c).__name__ == "CheckConstraint"
        ]
        assert any("end_date >= start_date" in c for c in checks)

    def test_activity_partial_indexes(self) -> None:
        """三个部分索引必须有 WHERE 条件。"""
        table = Base.metadata.tables["activity"]
        partial = ["idx_activity_dates", "idx_activity_city", "idx_activity_attraction"]
        for name in partial:
            idx = next(i for i in table.indexes if i.name == name)
            where = idx.dialect_options["postgresql"].get("where")
            assert where is not None, f"{name} 应为部分索引"


# ============================================================
# 模型行为
# ============================================================


class TestActivityStatus:
    """活动状态实时计算（API §17.1 决策：不存库）。"""

    def _make(self, start: date, end: date) -> Activity:
        return Activity(
            id=uuid.uuid4(),
            title="测试活动",
            start_date=start,
            end_date=end,
            created_by=uuid.uuid4(),
        )

    def test_upcoming(self) -> None:
        future = date.today() + timedelta(days=10)
        activity = self._make(future, future + timedelta(days=3))
        assert activity.status == "upcoming"

    def test_ongoing(self) -> None:
        today = date.today()
        activity = self._make(today - timedelta(days=1), today + timedelta(days=1))
        assert activity.status == "ongoing"

    def test_ongoing_on_start_day(self) -> None:
        today = date.today()
        activity = self._make(today, today + timedelta(days=3))
        assert activity.status == "ongoing"

    def test_ongoing_on_end_day(self) -> None:
        today = date.today()
        activity = self._make(today - timedelta(days=3), today)
        assert activity.status == "ongoing"

    def test_ended(self) -> None:
        past = date.today() - timedelta(days=10)
        activity = self._make(past, past + timedelta(days=3))
        assert activity.status == "ended"


class TestDefaults:
    def test_base_popularity_default(self) -> None:
        assert "50" in str(Attraction.__table__.c.base_popularity.server_default.arg)

    def test_final_popularity_default(self) -> None:
        assert "50" in str(
            PopularityStat.__table__.c.final_popularity.server_default.arg
        )

    def test_is_published_defaults_true(self) -> None:
        for model in (Attraction, Restaurant, Hotel, Activity):
            default = model.__table__.c.is_published.server_default
            assert "true" in str(default.arg).lower(), f"{model.__name__} 默认值应为 true"

    def test_need_reservation_defaults_false(self) -> None:
        default = Restaurant.__table__.c.need_reservation.server_default
        assert "false" in str(default.arg).lower()


class TestEnums:
    def test_region_level_values(self) -> None:
        assert RegionLevel.PROVINCE == "1"
        assert RegionLevel.CITY == "2"

    def test_category_type_values(self) -> None:
        assert CategoryType.THEME == "theme"
        assert CategoryType.LEVEL == "level"

    def test_enum_matches_check_constraint(self) -> None:
        checks = " ".join(
            str(c.sqltext) for c in AttractionCategory.__table__.constraints
            if type(c).__name__ == "CheckConstraint"
        )
        for value in CategoryType:
            assert f"'{value.value}'" in checks


class TestNullable:
    def test_activity_dates_required(self) -> None:
        assert Activity.__table__.c.start_date.nullable is False
        assert Activity.__table__.c.end_date.nullable is False

    def test_activity_city_optional(self) -> None:
        """city_id 为 NULL 表示全国性活动。"""
        assert Activity.__table__.c.city_id.nullable is True

    def test_activity_attraction_optional(self) -> None:
        assert Activity.__table__.c.attraction_id.nullable is True

    def test_attraction_city_required(self) -> None:
        assert Attraction.__table__.c.city_id.nullable is False

    def test_coordinates_optional(self) -> None:
        for model in (Attraction, Restaurant, Hotel):
            assert model.__table__.c.latitude.nullable is True
            assert model.__table__.c.longitude.nullable is True
