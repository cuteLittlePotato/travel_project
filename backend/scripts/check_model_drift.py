"""检查 ORM 模型与数据库实际 DDL 的差异。

用途（M0 审查确认的工作流）：
    每个模块写完 ORM 模型后运行本脚本，确认模型与已有 DDL 完全一致。
    差异归零后，模型即为唯一真相，后续表结构变更走 autogenerate。

用法：
    cd backend && uv run python scripts/check_model_drift.py
    cd backend && uv run python scripts/check_model_drift.py --module account

输出：
    无差异 → 退出码 0
    有差异 → 列出逐项差异，退出码 1

注意（M0 审查发现的坑）：
    分区子表（*_p2026_*、*_default）由 DDL 直接创建，ORM 无法表达，
    env.py 的 include_object 已将其排除，本脚本沿用同一过滤逻辑。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.db.base import Base
from app.db.migrations.filters import include_object as _include_object


def _describe(diff: tuple) -> str:
    """把 alembic 的差异元组转成可读文本。"""
    kind = diff[0]
    if kind == "add_table":
        return f"模型有、库中没有：表 {diff[1].name}"
    if kind == "remove_table":
        return f"库中有、模型中没有：表 {diff[1].name}"
    if kind == "add_column":
        return f"模型有、库中没有：{diff[2]} 的列 {diff[3].name}"
    if kind == "remove_column":
        return f"库中有、模型中没有：{diff[2]} 的列 {diff[3].name}"
    if kind in ("add_index", "remove_index"):
        return f"{'模型有、库中没有' if kind == 'add_index' else '库中有、模型中没有'}：索引 {diff[1].name}"
    if kind in ("add_constraint", "remove_constraint"):
        return f"{'模型有、库中没有' if kind == 'add_constraint' else '库中有、模型中没有'}：约束 {diff[1].name}"
    if kind == "modify_type":
        return f"类型不一致：{diff[1]} → {diff[2]}"
    if kind == "modify_nullable":
        return f"可空性不一致：{diff[1]}"
    if kind == "modify_default":
        return f"默认值不一致：{diff[1]}"
    return f"其他差异：{diff}"


#: 模块名 -> 该模块拥有的表。用于 --module 模式下限定比较范围。
#:
#: 为什么需要这个映射：`Base.metadata` 是全局的，一旦导入某个模块的模型，
#: 其他已导入模块的表也会参与比较。只靠 import 无法做到「只看本模块」，
#: 必须显式告诉检查器哪些表属于本次范围。
MODULE_TABLES: dict[str, set[str]] = {
    "account": {"user", "oauth_binding", "user_profile", "user_setting", "notification"},
    "catalog": {
        "region",
        "attraction_category",
        "attraction",
        "attraction_category_relation",
        "restaurant",
        "hotel",
        "transport",
        "activity",
    },
    "attraction": {"popularity_stat"},
    "knowledge_base": {"knowledge_base", "kb_document", "kb_chunk"},
    "knowledge_graph": {
        "kg_person",
        "kg_event",
        "kg_culture",
        "kg_relation_type",
        "featured_knowledge_graph",
    },
    "chat": {"chat_session", "chat_message", "chat_pending_interaction", "agent_checkpoint"},
    "memory": {"memory_long_term"},
    "trip_plan": {"trip_plan", "plan_candidate", "plan_day", "plan_activity"},
    "footprint": {"footprint"},
    "model_gateway": {"model", "model_call_log"},
    "quota": {"user_quota"},
    "system": {
        "admin_user",
        "role",
        "permission",
        "role_permission",
        "admin_user_role",
        "operation_log",
        "site_setting",
    },
    "recommend": {"user_event"},
}


def check(module: str | None = None) -> int:
    import asyncio

    # 确保所有模型被导入（含各模块已写好的）
    import app.db.models  # noqa: F401

    if module:
        if module not in MODULE_TABLES:
            print(f"[FAIL] unknown module: {module}")
            print(f"       available: {', '.join(sorted(MODULE_TABLES))}")
            return 2
        import importlib

        try:
            importlib.import_module(f"app.modules.{module}.models")
        except ModuleNotFoundError:
            print(f"[FAIL] app/modules/{module}/models.py not found")
            return 2

    # --module 模式下只比较属于该模块的表，其余视为「尚未开始」而忽略
    scoped_tables = MODULE_TABLES[module] if module else None

    def _include(obj, name, type_, reflected, compare_to) -> bool:
        if not _include_object(obj, name, type_, reflected, compare_to):
            return False
        if scoped_tables is None:
            return True
        if type_ == "table":
            return name in scoped_tables
        # 列/索引/约束：靠父表名判断
        parent = getattr(getattr(obj, "table", None), "name", None)
        if parent is None and isinstance(compare_to, tuple):
            parent = getattr(getattr(compare_to[1], "table", None), "name", None)
        return parent is None or parent in scoped_tables

    async def _run() -> list:
        # 复用项目的异步引擎，避免额外引入同步驱动（psycopg）
        from app.db.session import engine

        async with engine.connect() as connection:

            def _compare(sync_conn):
                ctx = MigrationContext.configure(
                    sync_conn,
                    opts={"compare_type": True, "include_object": _include},
                )
                return compare_metadata(ctx, Base.metadata)

            return await connection.run_sync(_compare)

    diffs = asyncio.run(_run())

    if not diffs:
        print("[OK] model matches database DDL")
        return 0

    print(f"[FAIL] {len(diffs)} diffs found:")
    print()
    for diff in diffs:
        print(f"  - {_describe(diff)}")

    print()
    print("Rules:")
    print("  - DB has / model missing  -> add to model, do NOT change DDL")
    print("  - model has / DB missing  -> confirm design change, then new migration")
    print("  - type/default mismatch   -> follow docs/design/03")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 ORM 模型与 DDL 的差异")
    parser.add_argument("--module", help="只检查某个模块（如 account）")
    args = parser.parse_args()
    return check(args.module)


if __name__ == "__main__":
    raise SystemExit(main())
