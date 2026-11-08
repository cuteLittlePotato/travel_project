"""M0 审查新增：Alembic 对象过滤规则的测试。

背景：ORM 模型先行的方案下，``alembic check`` 必须只比较主表。
分区子表由 DDL 直接创建（PARTITION OF），ORM 无法表达，若不排除，
每次 check 都会报告「应删除 6 个分区子表」，噪声掩盖真实差异。
"""

from __future__ import annotations

import pytest

from app.db.migrations.filters import include_object


class TestIncludeObject:
    def test_main_tables_included(self) -> None:
        """43 张主表必须参与比较。"""
        for table in ("user", "attraction", "trip_plan", "model", "user_event"):
            assert include_object(None, table, "table", False, None) is True

    @pytest.mark.parametrize(
        "table",
        [
            "model_call_log_p2026_11",
            "model_call_log_p2026_12",
            "user_event_p2026_11",
            "user_event_p2026_12",
        ],
    )
    def test_partition_children_excluded(self, table: str) -> None:
        assert include_object(None, table, "table", False, None) is False

    @pytest.mark.parametrize(
        "table", ["model_call_log_default", "user_event_default"]
    )
    def test_default_partitions_excluded(self, table: str) -> None:
        assert include_object(None, table, "table", False, None) is False

    def test_alembic_version_excluded(self) -> None:
        assert include_object(None, "alembic_version", "table", False, None) is False

    def test_non_table_types_included(self) -> None:
        """列、索引、约束不受表过滤影响。"""
        for type_ in ("column", "index", "unique_constraint", "check_constraint"):
            assert include_object(None, "some_name", type_, False, None) is True

    def test_none_name_passes(self) -> None:
        assert include_object(None, None, "table", False, None) is True

    def test_partition_marker_mid_name(self) -> None:
        """名字中间的 _p2026_ 也要识别（不只看前缀）。"""
        assert include_object(None, "foo_p2026_05_bar", "table", False, None) is False


class TestFilterConsistency:
    def test_env_uses_shared_filter(self) -> None:
        """env.py 必须复用 filters.py 的规则，不能各写一套。"""
        from pathlib import Path

        env_path = (
            Path(__file__).resolve().parents[2] / "app" / "db" / "migrations" / "env.py"
        )
        content = env_path.read_text(encoding="utf-8")
        assert "from app.db.migrations.filters import include_object" in content
        assert "include_object=_include_object" in content

    def test_drift_script_uses_shared_filter(self) -> None:
        from pathlib import Path

        script = Path(__file__).resolve().parents[2] / "scripts" / "check_model_drift.py"
        content = script.read_text(encoding="utf-8")
        assert "from app.db.migrations.filters import include_object" in content


class TestModuleTableMapping:
    """M0 审查新增：`--module` 参数依赖的模块-表映射。

    背景：`Base.metadata` 是全局的，导入某个模块的模型后，其他模块的表
    也会参与比较。只靠 import 无法做到「只看本模块」，必须显式声明范围，
    否则 M01 开工时会看到「M04/M09/M11 的表都没写模型」这类预期内噪音。
    """

    def test_all_43_tables_covered(self) -> None:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from check_model_drift import MODULE_TABLES

        tables = [t for ts in MODULE_TABLES.values() for t in ts]
        assert len(tables) == 43, f"应覆盖 43 张表，实际 {len(tables)}"
        assert len(set(tables)) == 43, "存在重复归属的表"

    def test_no_table_in_multiple_modules(self) -> None:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from check_model_drift import MODULE_TABLES

        seen: dict[str, str] = {}
        for module, tables in MODULE_TABLES.items():
            for table in tables:
                assert table not in seen, (
                    f"{table} 同时属于 {seen.get(table)} 和 {module}"
                )
                seen[table] = module

    def test_matches_schema_sql(self) -> None:
        """模块映射中的表必须都能在 schema.sql 里找到。"""
        import re
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        sys.path.insert(0, str(root / "backend" / "scripts"))
        from check_model_drift import MODULE_TABLES

        sql = (root / "scripts" / "sql" / "schema.sql").read_text(encoding="utf-8")
        schema_tables = {
            m.group(1)
            for m in re.finditer(r"^CREATE TABLE (\w+)\s*\(", sql, re.M)
            if "PARTITION OF" not in sql[m.start() : m.start() + 120]
        }

        mapped = {t for ts in MODULE_TABLES.values() for t in ts}
        assert mapped == schema_tables, (
            f"仅映射有: {mapped - schema_tables}；"
            f"仅 schema.sql 有: {schema_tables - mapped}"
        )


class TestArchitectureDocConsistency:
    """确保架构文档不再对「模型放哪里」给出两种说法。"""

    def test_doc_states_models_live_in_modules(self) -> None:
        from pathlib import Path

        doc = Path(__file__).resolve().parents[3] / "docs" / "design" / "02.整体架构设计.md"
        content = doc.read_text(encoding="utf-8")

        assert "模型定义在各自模块的 `models.py`" in content
        assert "只做聚合导入" in content

    def test_doc_states_model_first_workflow(self) -> None:
        from pathlib import Path

        doc = Path(__file__).resolve().parents[3] / "docs" / "design" / "02.整体架构设计.md"
        content = doc.read_text(encoding="utf-8")

        assert "模型先行" in content
        assert "check_model_drift.py" in content


class TestClaudeMdRule:
    """CLAUDE.md 中的 ORM 模型规则必须存在，防止被误删。"""

    def test_claude_md_has_orm_rule_section(self) -> None:
        from pathlib import Path

        claude_md = Path(__file__).resolve().parents[3] / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")

        assert "## 5.1 ORM 模型规则" in content

    def test_rule_mentions_key_points(self) -> None:
        from pathlib import Path

        content = (
            Path(__file__).resolve().parents[3] / "CLAUDE.md"
        ).read_text(encoding="utf-8")

        # 六条核心约定都要在
        for phrase in (
            "模型先行",
            "app/modules/<module>/models.py",
            "check_model_drift.py",
            "不一次性写全",
            "禁止物理外键",
            "alembic revision --autogenerate",
        ):
            assert phrase in content, f"CLAUDE.md 缺少规则要点: {phrase}"
