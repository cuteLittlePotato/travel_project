"""M12-T01 模型管理 ORM 与分区的测试。

覆盖 DoD：
    1. ``model`` 唯一约束 ``(category, model_code, base_url)``
    2. 部分唯一索引 ``idx_model_default``（每类别一个默认）
    3. ``category`` CHECK 含 chat/vision/embedding/rerank/ocr
    4. ``model_call_log`` 为分区表，主键 ``(id, created_at)``
    5. **无 ``vector_dim`` 字段**
    6. **无物理外键**
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint

from app.modules.model_gateway.constants import (
    DEFAULT_TIMEOUT_SECONDS,
    CallErrorType,
    CallerType,
    ModelCategory,
)
from app.modules.model_gateway.models import Model, ModelCallLog
from app.modules.model_gateway.partition import (
    PARTITION_LOOKAHEAD_MONTHS,
    add_months,
    ensure_partitions,
    list_partitions,
    month_range,
    months_to_ensure,
    partition_exists,
    partition_name,
)

MODELS_DIR = Path(__file__).resolve().parents[2] / "app" / "modules" / "model_gateway"


def _columns(model: type) -> set[str]:
    return {c.name for c in model.__table__.columns}


# ============================================================
# model 表结构
# ============================================================


class TestModelTable:
    def test_tablename(self) -> None:
        assert Model.__tablename__ == "model"

    def test_required_columns(self) -> None:
        columns = _columns(Model)
        for name in (
            "id",
            "name",
            "category",
            "model_code",
            "base_url",
            "api_key_encrypted",
            "max_context_tokens",
            "max_output_tokens",
            "timeout_seconds",
            "concurrency_limit",
            "price_input",
            "price_output",
            "description",
            "is_enabled",
            "is_default",
            "last_test_at",
            "last_test_ok",
            "created_at",
            "updated_at",
        ):
            assert name in columns, f"缺少列 {name}"

    def test_no_vector_dim(self) -> None:
        """DoD：规范检查——无 ``vector_dim`` 字段，维度由配置文件控制。"""
        assert "vector_dim" not in _columns(Model)
        assert "vector_dimension" not in _columns(Model)

    def test_unique_constraint_category_code_url(self) -> None:
        """DoD：``model`` 唯一约束 ``(category, model_code, base_url)``。"""
        unique_indexes = [
            idx
            for idx in Model.__table__.indexes
            if idx.unique and [c.name for c in idx.columns] == [
                "category",
                "model_code",
                "base_url",
            ]
        ]
        assert len(unique_indexes) == 1
        assert unique_indexes[0].name == "uk_model_category_code"

    def test_default_partial_unique_index(self) -> None:
        """DoD：部分唯一索引 ``idx_model_default``，每类别一个默认。"""
        target = next(idx for idx in Model.__table__.indexes if idx.name == "idx_model_default")

        assert target.unique is True
        assert [c.name for c in target.columns] == ["category"]
        # WHERE is_default = TRUE —— 部分索引的核心
        where = str(target.dialect_options["postgresql"].get("where"))
        assert "is_default" in where and "TRUE" in where.upper()

    def test_category_check_covers_all_five(self) -> None:
        """DoD：``category`` CHECK 含 chat/vision/embedding/rerank/ocr。"""
        check = next(
            c for c in Model.__table__.constraints if isinstance(c, CheckConstraint)
        )
        sql = str(check.sqltext)
        for category in ("chat", "vision", "embedding", "rerank", "ocr"):
            assert category in sql

    def test_category_enum_matches(self) -> None:
        assert ModelCategory.CHAT == "chat"
        assert ModelCategory.VISION == "vision"
        assert ModelCategory.EMBEDDING == "embedding"
        assert ModelCategory.RERANK == "rerank"
        assert ModelCategory.OCR == "ocr"
        assert len(ModelCategory) == 5

    def test_timeout_default(self) -> None:
        assert str(Model.__table__.c.timeout_seconds.server_default.arg) == str(
            DEFAULT_TIMEOUT_SECONDS
        )

    def test_is_default_not_null(self) -> None:
        assert Model.__table__.c.is_default.nullable is False
        assert Model.__table__.c.is_enabled.nullable is False

    def test_price_precision(self) -> None:
        """价格是 ``NUMERIC(12,6)``——千 token 单价需要 6 位小数。"""
        col = Model.__table__.c.price_input
        assert col.type.precision == 12
        assert col.type.scale == 6


# ============================================================
# model_call_log 表结构
# ============================================================


class TestModelCallLogTable:
    def test_tablename(self) -> None:
        assert ModelCallLog.__tablename__ == "model_call_log"

    def test_composite_primary_key(self) -> None:
        """DoD：分区表主键 ``(id, created_at)``。

        PostgreSQL 要求分区键包含在主键中，因此不能只有 ``id``。
        """
        pk_columns = [c.name for c in ModelCallLog.__table__.primary_key.columns]
        assert pk_columns == ["id", "created_at"]

    def test_required_columns(self) -> None:
        columns = _columns(ModelCallLog)
        for name in (
            "id",
            "model_id",
            "caller_type",
            "user_id",
            "session_id",
            "document_id",
            "token_input",
            "token_output",
            "latency_ms",
            "is_success",
            "error_type",
            "error_message",
            "cost_estimate",
            "created_at",
        ):
            assert name in columns, f"缺少列 {name}"

    def test_no_updated_at(self) -> None:
        """日志写入后不再修改，没有 updated_at。"""
        assert "updated_at" not in _columns(ModelCallLog)

    def test_counters_not_null_with_zero_default(self) -> None:
        for name in ("token_input", "token_output"):
            col = ModelCallLog.__table__.c[name]
            assert col.nullable is False
            assert str(col.server_default.arg) == "0"

    def test_is_success_required(self) -> None:
        assert ModelCallLog.__table__.c.is_success.nullable is False

    def test_indexes_declared(self) -> None:
        declared = {idx.name for idx in ModelCallLog.__table__.indexes}
        for name in (
            "idx_mcalllog_model_time",
            "idx_mcalllog_user_time",
            "idx_mcalllog_caller",
            "idx_mcalllog_success",
        ):
            assert name in declared

    def test_caller_type_enum(self) -> None:
        assert CallerType.USER_CHAT == "user_chat"
        assert CallerType.SYSTEM_DOCUMENT == "system_document"

    def test_error_type_enum(self) -> None:
        assert CallErrorType.TIMEOUT == "timeout"
        assert CallErrorType.AUTH == "auth"
        assert CallErrorType.RATE_LIMIT == "rate_limit"
        assert CallErrorType.SERVER_ERROR == "server_error"
        assert CallErrorType.FORMAT_INVALID == "format_invalid"


# ============================================================
# 规范检查（DoD 6）
# ============================================================


class TestNoForeignKeys:
    def test_model_has_no_foreign_keys(self) -> None:
        assert Model.__table__.foreign_keys == set()

    def test_model_call_log_has_no_foreign_keys(self) -> None:
        assert ModelCallLog.__table__.foreign_keys == set()

    def test_source_has_no_references(self) -> None:
        """DoD：源码 ``grep -iE 'foreign key|references'`` 无输出。"""
        for filename in ("models.py", "constants.py"):
            source = (MODELS_DIR / filename).read_text(encoding="utf-8")
            hits = re.findall(r"(?i)foreign\s+key|references", source)
            assert hits == [], f"{filename} 中出现了外键关键字：{hits}"

    def test_no_relationship_declaration(self) -> None:
        source = (MODELS_DIR / "models.py").read_text(encoding="utf-8")
        assert "relationship(" not in source


# ============================================================
# 分区命名与月份计算（纯函数，无 DB）
# ============================================================


class TestPartitionNaming:
    def test_name_format(self) -> None:
        assert partition_name("model_call_log", 2026, 11) == "model_call_log_p2026_11"
        assert partition_name("model_call_log", 2027, 1) == "model_call_log_p2027_01"

    def test_month_zero_padded(self) -> None:
        assert partition_name("t", 2026, 3) == "t_p2026_03"


class TestMonthRange:
    def test_regular_month(self) -> None:
        assert month_range(2026, 11) == ("2026-11-01", "2026-12-01")

    def test_december_rolls_to_next_year(self) -> None:
        assert month_range(2026, 12) == ("2026-12-01", "2027-01-01")

    def test_january(self) -> None:
        assert month_range(2027, 1) == ("2027-01-01", "2027-02-01")

    def test_february(self) -> None:
        """2 月不做特殊处理——范围只用到月份首日。"""
        assert month_range(2026, 2) == ("2026-02-01", "2026-03-01")


class TestAddMonths:
    def test_forward_within_year(self) -> None:
        assert add_months(2026, 1, 2) == (2026, 3)

    def test_forward_across_year(self) -> None:
        assert add_months(2026, 11, 3) == (2027, 2)

    def test_backward_across_year(self) -> None:
        assert add_months(2026, 1, -1) == (2025, 12)

    def test_zero_delta(self) -> None:
        assert add_months(2026, 6, 0) == (2026, 6)

    def test_multi_year_jump(self) -> None:
        assert add_months(2026, 6, 18) == (2027, 12)
        assert add_months(2026, 6, -18) == (2024, 12)


class TestMonthsToEnsure:
    def test_current_plus_lookahead(self) -> None:
        months = months_to_ensure(date(2026, 11, 8), lookahead=2)
        assert months == [(2026, 11), (2026, 12), (2027, 1)]

    def test_always_includes_current(self) -> None:
        months = months_to_ensure(date(2026, 11, 1), lookahead=0)
        assert months == [(2026, 11)]

    def test_lookahead_constant(self) -> None:
        assert PARTITION_LOOKAHEAD_MONTHS >= 1


# ============================================================
# 分区维护（需要数据库）
# ============================================================


pytestmark_db = pytest.mark.integration


class TestPartitionMaintenance:
    async def test_initial_partitions_exist(self) -> None:
        """迁移已建 2026-11 / 2026-12 与 DEFAULT 兜底分区。"""
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            names = await list_partitions(session, "model_call_log")

        assert "model_call_log_p2026_11" in names
        assert "model_call_log_p2026_12" in names
        assert "model_call_log_default" in names

    async def test_ensure_partitions_is_idempotent(self) -> None:
        """重复执行不报错、不重复建表。"""
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            first = await ensure_partitions(session)
            second = await ensure_partitions(session)

        assert second == []
        # 第一次可能建了新月份，也可能都已存在——都不影响幂等性断言
        assert isinstance(first, list)

    async def test_ensure_partitions_creates_next_month(self) -> None:
        """给定一个未来日期，能建出对应分区。"""
        from app.db.session import SessionLocal

        target = date(2030, 5, 15)
        async with SessionLocal() as session:
            if await partition_exists(session, "model_call_log_p2030_05"):
                pytest.skip("测试分区已存在，跳过以免污染")
            created = await ensure_partitions(session, today=target, lookahead=0)

        assert "model_call_log_p2030_05" in created

        # 清理
        from sqlalchemy import text

        async with SessionLocal() as session:
            await session.execute(text('DROP TABLE IF EXISTS "model_call_log_p2030_05"'))
            await session.commit()

    async def test_default_partition_exists(self) -> None:
        """DoD 边界：DEFAULT 分区兜底，超出范围的数据不会插入失败。"""
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            assert await partition_exists(session, "model_call_log_default")
