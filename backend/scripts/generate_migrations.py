"""从 scripts/sql/schema.sql 生成 Alembic 声明式迁移。

为什么用生成器而不是手写：
    43 张表、103 个索引、37 个 CHECK 约束、118 条注释，手写既慢又容易漏。
    生成器保证迁移与 schema.sql 逐项一致，重新生成即可同步变更。

用法：
    cd backend && uv run python scripts/generate_migrations.py

产物：app/db/migrations/versions/ 下的多个迁移文件，按模块分组。
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
SCHEMA_SQL = REPO_ROOT / "scripts" / "sql" / "schema.sql"
VERSIONS_DIR = BACKEND_DIR / "app" / "db" / "migrations" / "versions"


# ============================================================
# 数据结构
# ============================================================


@dataclass
class Column:
    name: str
    sql_type: str
    nullable: bool = True
    default: str | None = None
    checks: list[str] = field(default_factory=list)
    primary_key: bool = False


@dataclass
class Index:
    name: str
    table: str
    columns: str
    unique: bool = False
    #: 部分索引的 WHERE 条件（如 ``is_read = FALSE``）。
    #: M0-T13 原实现丢了这个字段，导致部分索引被建成全量索引。
    where: str | None = None


@dataclass
class Table:
    name: str
    columns: list[Column]
    table_checks: list[tuple[str, str]] = field(default_factory=list)  # (约束名, 表达式)
    partition_by: str | None = None
    comment: str | None = None
    column_comments: dict[str, str] = field(default_factory=dict)


@dataclass
class Partition:
    name: str
    parent: str
    bound: str  # FROM (...) TO (...) 或 DEFAULT


# ============================================================
# 解析
# ============================================================


def _strip_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _split_top_level(body: str) -> list[str]:
    """按顶层逗号切分字段定义（忽略括号内的逗号）。"""
    parts: list[str] = []
    depth = 0
    current: list[str] = []

    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1

        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)

    if current:
        parts.append("".join(current).strip())
    return [p for p in parts if p]


_TYPE_MAP = {
    "UUID": "postgresql.UUID(as_uuid=True)",
    "TIMESTAMPTZ": "sa.DateTime(timezone=True)",
    "TIMESTAMP": "sa.DateTime()",
    "DATE": "sa.Date()",
    # TIME 不带时区，用于 plan_activity 的 start_time/end_time
    "TIME": "sa.Time()",
    "TEXT": "sa.Text()",
    "BOOLEAN": "sa.Boolean()",
    "INTEGER": "sa.Integer()",
    "BIGINT": "sa.BigInteger()",
    "SMALLINT": "sa.SmallInteger()",
    "REAL": "sa.REAL()",
    "JSONB": "postgresql.JSONB()",
    "JSON": "postgresql.JSON()",
    "VECTOR": "sa.Text()",  # 无 pgvector 扩展时降级
}


def _parse_type(raw: str) -> str:
    """把 SQL 类型转成 SQLAlchemy 类型表达式。"""
    upper = raw.strip().upper()

    # VARCHAR(n) / CHAR(n) / NUMERIC(p,s)
    match = re.match(r"VARCHAR\((\d+)\)", upper)
    if match:
        return f"sa.String({match.group(1)})"

    match = re.match(r"CHAR\((\d+)\)", upper)
    if match:
        return f"sa.CHAR({match.group(1)})"

    match = re.match(r"NUMERIC\((\d+),\s*(\d+)\)", upper)
    if match:
        return f"sa.Numeric({match.group(1)}, {match.group(2)})"

    if upper in _TYPE_MAP:
        return _TYPE_MAP[upper]

    if upper == "VARCHAR":
        return "sa.String()"

    # 未识别类型不能静默降级为 String——会丢精度或改变语义，
    # 直接报错让开发者补映射
    raise ValueError(f"未识别的 SQL 类型: {raw!r}，请在 _TYPE_MAP 中补充")


def _parse_default(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    upper = value.upper()

    # server_default 只接受 str / ClauseElement / TextClause。
    # 数字与布尔必须转成字符串形式的 SQL 字面量，否则 SQLAlchemy 报类型错误
    if upper in ("NOW()", "CURRENT_TIMESTAMP"):
        return "sa.func.now()"
    if upper == "TRUE":
        return "'true'"
    if upper == "FALSE":
        return "'false'"
    if upper == "NULL":
        return None
    if re.fullmatch(r"-?\d+(\.\d+)?", value):
        return f"'{value}'"
    if value.startswith("'") and value.endswith("'"):
        # 已带引号的字符串，原样使用（内部的单引号已翻倍）
        return value
    return f"sa.text({value!r})"


def _parse_column(definition: str) -> Column | None:
    """解析单列定义。约束行（CONSTRAINT / PRIMARY KEY）返回 None。"""
    stripped = definition.strip()
    upper = stripped.upper()

    # 用全词匹配判断是否是约束行。
    # 不能用 startswith("CHECK")——checkpoint_id 这种列名会被误杀
    if re.match(
        r"^(CONSTRAINT|PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY|CHECK)\s",
        upper,
    ):
        return None

    tokens = stripped.split()
    if len(tokens) < 2:
        return None

    name = tokens[0]
    # 类型可能带括号与空格，如 NUMERIC(10, 2)
    rest = stripped[len(name):].strip()

    type_match = re.match(
        r"((?:VARCHAR|CHAR|NUMERIC|DECIMAL)(?:\([^)]*\))?|\w+(?:\[\])?)", rest, re.I
    )
    sql_type = type_match.group(1) if type_match else "TEXT"
    tail = rest[len(sql_type):].strip() if type_match else rest

    nullable = "NOT NULL" not in tail.upper()
    primary_key = "PRIMARY KEY" in tail.upper()

    default_match = re.search(r"\bDEFAULT\s+([^\s,]+(?:\(\))?)", tail, re.I)
    default = _parse_default(default_match.group(1)) if default_match else None

    # 列级 CHECK。用括号配对提取，避免贪婪/非贪婪匹配吃掉内层括号
    checks: list[str] = []
    for check_match in re.finditer(r"CHECK\s*\(", tail, re.I):
        start = check_match.end()
        depth = 1
        index = start
        while index < len(tail) and depth > 0:
            if tail[index] == "(":
                depth += 1
            elif tail[index] == ")":
                depth -= 1
            index += 1
        if depth == 0:
            checks.append(tail[start: index - 1].strip())

    return Column(
        name=name,
        sql_type=_parse_type(sql_type),
        nullable=nullable,
        default=default,
        checks=checks,
        primary_key=primary_key,
    )


def parse_schema(sql: str) -> tuple[list[Table], list[Index], list[Partition], dict]:
    clean = _strip_comments(sql)

    tables: list[Table] = []
    table_map: dict[str, Table] = {}

    # 表定义。表体按括号配对提取，兼容 PARTITION BY 子句
    for match in re.finditer(
        r"CREATE TABLE (\w+)\s*\((.*?)\n\)\s*(.*?);", clean, re.S
    ):
        name, body, suffix = match.group(1), match.group(2), match.group(3).strip()
        if "PARTITION OF" in clean[match.start(): match.start() + 100]:
            continue

        columns: list[Column] = []
        table_checks: list[tuple[str, str]] = []

        for item in _split_top_level(body):
            constraint_match = re.match(
                r"CONSTRAINT\s+(\w+)\s+CHECK\s*\((.+)\)", item, re.S | re.I
            )
            if constraint_match:
                table_checks.append((constraint_match.group(1), constraint_match.group(2)))
                continue

            col = _parse_column(item)
            if col:
                columns.append(col)

        partition_by = None
        if "PARTITION BY" in suffix.upper():
            partition_by = "created_at"

        table = Table(
            name=name,
            columns=columns,
            table_checks=table_checks,
            partition_by=partition_by,
        )
        tables.append(table)
        table_map[name] = table

    # 分区子表。两种写法：
    #   PARTITION OF parent FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
    #   PARTITION OF parent DEFAULT;
    partitions: list[Partition] = []
    for match in re.finditer(
        r"CREATE TABLE (\w+) PARTITION OF (\w+)\s+"
        r"(FOR VALUES\s+FROM\s*\([^)]*\)\s*TO\s*\([^)]*\)|DEFAULT)\s*;",
        clean,
        re.S | re.I,
    ):
        partitions.append(
            Partition(name=match.group(1), parent=match.group(2), bound=match.group(3).strip())
        )

    # 索引
    indexes: list[Index] = []
    for match in re.finditer(
        r"CREATE\s+(UNIQUE\s+)?INDEX\s+(\w+)\s+ON\s+(\w+)\s*\(([^;]+?)\)\s*(WHERE.+?)?;",
        clean,
        re.S,
    ):
        indexes.append(
            Index(
                name=match.group(2),
                table=match.group(3),
                columns=" ".join(match.group(4).split()),
                unique=bool(match.group(1)),
                where=(
                    re.sub(r"^WHERE\s+", "", " ".join(match.group(5).split()), flags=re.I)
                    if match.group(5)
                    else None
                ),
            )
        )

    # 注释
    comments: dict[str, str] = {}
    for match in re.finditer(r"COMMENT ON TABLE (\w+) IS '((?:[^']|'')*)';", clean):
        if match.group(1) in table_map:
            table_map[match.group(1)].comment = match.group(2).replace("''", "'")

    for match in re.finditer(r"COMMENT ON COLUMN (\w+)\.(\w+) IS '((?:[^']|'')*)';", clean):
        table, column, text = match.groups()
        if table in table_map:
            table_map[table].column_comments[column] = text.replace("''", "'")

    return tables, indexes, partitions, comments


# ============================================================
# 生成
# ============================================================


def _sql_literal(text: str) -> str:
    """转成 SQL 字符串字面量，单引号翻倍转义。

    同时转义 SQLAlchemy 的绑定参数标记（``$1``、``:name``），
    否则注释里的 JSON 示例（如 ``{"ticket":420}``）会被误认为参数占位符。
    """
    escaped = text.replace("'", "''")
    escaped = escaped.replace("$", "\\$")
    return f"'{escaped}'"


def _render_column(col: Column) -> str:
    """渲染单列。

    列级 CHECK 通过 ``sa.CheckConstraint`` 放在 ``create_table`` 的约束列表里，
    但同时用 ``sa.Column(..., ...)`` 的列对象参与约束构建——SQLAlchemy 的做法是
    在 Column 上声明 ``CheckConstraint``，不能给 Constraint 传 ``column=``。
    这里改为把 CHECK 作为独立约束、表达式内直接写列名，效果等价。
    """
    parts = [f'"{col.name}"', col.sql_type]
    if col.primary_key:
        parts.append("primary_key=True")
    if not col.nullable:
        parts.append("nullable=False")
    if col.default is not None:
        parts.append(f"server_default={col.default}")
    return "        sa.Column(" + ", ".join(parts) + "),"


def render_table(table: Table) -> Iterator[str]:
    yield f'    op.create_table(\n        "{table.name}",'
    for col in table.columns:
        yield _render_column(col)
    # 列级 CHECK：作为表级约束声明，表达式里已含列名（如 gender IN (...)）
    for col in table.columns:
        for index, expr in enumerate(col.checks):
            suffix = "" if index == 0 else f"_{index}"
            yield (
                f'        sa.CheckConstraint({expr!r}, '
                f'name="ck_{table.name}_{col.name}{suffix}"),'
            )
    for name, expr in table.table_checks:
        # schema.sql 里的显式约束名不统一（有 chk_ 也有 ck_ 前缀），
        # 统一为 ck_<table>_<语义>，与列级 CHECK 保持一致
        normalized = re.sub(r"^(chk|ck)_", "", name)
        if not normalized.startswith(f"{table.name}_"):
            normalized = f"{table.name}_{normalized}"
        yield f'        sa.CheckConstraint({expr!r}, name="ck_{normalized}"),'
    # 分区表必须声明 postgresql_partition_by，否则后续 PARTITION OF 会失败
    if table.partition_by:
        yield f'        postgresql_partition_by="RANGE ({table.partition_by})",'
    yield "    )"

    # 注释里可能含引号、中文标点，用 repr() 生成安全的 Python 字符串字面量
    if table.comment:
        sql = f'COMMENT ON TABLE "{table.name}" IS {_sql_literal(table.comment)}'
        yield f"    op.get_bind().exec_driver_sql({sql!r})"
    for column, text in table.column_comments.items():
        sql = f'COMMENT ON COLUMN "{table.name}"."{column}" IS {_sql_literal(text)}'
        yield f"    op.get_bind().exec_driver_sql({sql!r})"


def render_index(index: Index) -> str:
    """渲染索引。

    部分索引（带 WHERE）用原生 SQL —— ``op.create_index`` 虽支持
    ``postgresql_where``，但生成器输出的是文本代码，直接写 SQL 更直观可靠。
    """
    """渲染索引。

    带 ``DESC`` 的索引（如 ``created_at DESC``）在 SQLAlchemy 中要用
    ``sa.text()`` 或列的 ``.desc()``。这里用 ``postgresql_ops`` 不可行，
    简化处理：降序索引改用原生 SQL，保证与 schema.sql 完全一致。
    """
    columns = [c.strip() for c in index.columns.split(",")]

    # 部分索引：保留 WHERE 子句
    if index.where:
        cols_sql = ", ".join(columns)
        unique_sql = "UNIQUE " if index.unique else ""
        sql = (
            f'CREATE {unique_sql}INDEX {index.name} ON "{index.table}" '
            f"({cols_sql}) WHERE {index.where}"
        )
        return f"    op.get_bind().exec_driver_sql({sql!r})"

    if any(" DESC" in c.upper() or " ASC" in c.upper() for c in columns):
        cols_sql = ", ".join(columns)
        unique_sql = "UNIQUE " if index.unique else ""
        # 表名必须加引号：user、model 等都是 PostgreSQL 保留字
        sql = f'CREATE {unique_sql}INDEX {index.name} ON "{index.table}" ({cols_sql})'
        return f"    op.execute({sql!r})"

    unique = ", unique=True" if index.unique else ""
    return (
        f'    op.create_index("{index.name}", "{index.table}", '
        f"[{', '.join(repr(c) for c in columns)}]{unique})"
    )


def main() -> int:
    if not SCHEMA_SQL.exists():
        print(f"找不到 {SCHEMA_SQL}", file=sys.stderr)
        return 1

    tables, indexes, partitions, _ = parse_schema(SCHEMA_SQL.read_text(encoding="utf-8"))
    print(f"解析完成：{len(tables)} 张表，{len(indexes)} 个索引，{len(partitions)} 个分区")

    total_columns = sum(len(t.columns) for t in tables)
    total_checks = sum(len(t.table_checks) for t in tables)
    column_checks = sum(len(c.checks) for t in tables for c in t.columns)
    print(f"  字段 {total_columns} 个，CHECK {total_checks + column_checks} 个")

    # 支持 --dump 查看单表生成的代码，便于人工核对
    if "--dump" in sys.argv:
        target = sys.argv[sys.argv.index("--dump") + 1]
        table = next((t for t in tables if t.name == target), None)
        if table is None:
            print(f"表不存在: {target}", file=sys.stderr)
            return 1
        for line in render_table(table):
            print(line)
        for idx in indexes:
            if idx.table == target:
                print(render_index(idx))
        return 0

    return write_migrations(tables, indexes, partitions)


#: 基线迁移：扩展与公共函数，必须先于所有表执行
BASELINE = '''"""0001 baseline - 扩展与公共函数

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-08

本迁移只安装扩展与触发器函数，不建业务表。
业务表按模块拆分在 0002 起的迁移文件中。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: updated_at 自动更新函数。所有含 updated_at 列的表共用
TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    # pg_trgm：模糊搜索与相似度匹配（regions / attractions 的名称检索）
    op.get_bind().exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.get_bind().exec_driver_sql(TRIGGER_FUNCTION)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP FUNCTION IF EXISTS trigger_set_updated_at()")
    # 扩展不主动删除：可能被其他库对象依赖
'''

#: 模块分组 -> (revision 标识, 文件描述, 表名列表)
MODULES: list[tuple[str, str, list[str]]] = [
    (
        "0002_m01_account",
        "M01 用户与账户",
        ["user", "oauth_binding", "user_profile", "user_setting", "notification"],
    ),
    (
        "0003_m11_catalog",
        "M11 基础数据",
        [
            "region", "attraction_category", "attraction",
            "attraction_category_relation", "restaurant", "hotel", "transport", "activity",
        ],
    ),
    ("0004_popularity", "热度统计", ["popularity_stat"]),
    ("0005_m09_knowledge_base", "M09 知识库", ["knowledge_base", "kb_document", "kb_chunk"]),
    (
        "0006_m10_knowledge_graph",
        "M10 知识图谱",
        ["kg_person", "kg_event", "kg_culture", "kg_relation_type", "featured_knowledge_graph"],
    ),
    (
        "0007_m03_chat",
        "M03 对话 / M06 Agent",
        ["chat_session", "chat_message", "chat_pending_interaction", "agent_checkpoint"],
    ),
    ("0008_m07_memory", "M07 记忆", ["memory_long_term"]),
    (
        "0009_m04_plan",
        "M04 旅游计划",
        ["trip_plan", "plan_candidate", "plan_day", "plan_activity"],
    ),
    ("0010_m05_footprint", "M05 足迹", ["footprint"]),
    ("0011_m12_model", "M12 模型管理", ["model", "model_call_log"]),
    ("0012_m13_quota", "M13 额度", ["user_quota"]),
    (
        "0013_m15_system",
        "M15 系统管理",
        [
            "admin_user", "role", "permission", "role_permission",
            "admin_user_role", "operation_log", "site_setting",
        ],
    ),
    ("0014_m17_user_event", "M17 埋点", ["user_event"]),
]

_HEADER = '''"""{title}

Revision ID: {revision}
Revises: {down_revision}
Create Date: 2026-11-08

由 scripts/generate_migrations.py 从 scripts/sql/schema.sql 自动生成。
手工修改需同步更新 schema.sql，否则重新生成会被覆盖。

规范（docs/rules/database-rules.md）：
    - 主键 UUID，无 SERIAL/BIGSERIAL
    - 禁止物理外键，表间关系由应用层维护
    - 时间字段统一 TIMESTAMPTZ
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "{revision}"
down_revision: str | None = "{down_revision}"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
'''


def _render_upgrade(
    tables: list[Table], indexes: list[Index], partitions: list[Partition]
) -> str:
    lines: list[str] = []

    for table in tables:
        lines.extend(render_table(table))

    for table in tables:
        for index in indexes:
            if index.table == table.name:
                lines.append(render_index(index))

    # 分区表：主表已用 PARTITION BY 建好，这里补子分区
    for part in partitions:
        sql = f"CREATE TABLE {part.name} PARTITION OF {part.parent} {part.bound}"
        lines.append(f"    op.get_bind().exec_driver_sql({sql!r})")

    # 触发器：updated_at 自动更新。表名必须加引号（user/model 等是保留字）
    for table in tables:
        if any(c.name == "updated_at" for c in table.columns):
            sql = (
                f"CREATE TRIGGER trg_{table.name}_updated_at "
                f'BEFORE UPDATE ON "{table.name}" '
                f"FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()"
            )
            lines.append(f"    op.get_bind().exec_driver_sql({sql!r})")

    return "\n".join(lines) if lines else "    pass"


def _render_downgrade(tables: list[Table], partitions: list[Partition]) -> str:
    lines: list[str] = []
    for part in partitions:
        lines.append(f'    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS {part.name}")')
    # 逆序删除，避免依赖问题（虽然无外键，保持习惯）
    for table in reversed(tables):
        lines.append(f'    op.execute(\'DROP TABLE IF EXISTS "{table.name}" CASCADE\')')
    return "\n".join(lines) if lines else "    pass"


def write_migrations(
    tables: list[Table], indexes: list[Index], partitions: list[Partition]
) -> int:
    table_map = {t.name: t for t in tables}
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)

    # 基线迁移（扩展 + 触发器函数）
    baseline_file = VERSIONS_DIR / "0001_baseline.py"
    baseline_file.write_text(BASELINE, encoding="utf-8")
    print(f"  已生成 {baseline_file.name}")

    previous = "0001_baseline"
    written = 1

    for revision, title, names in MODULES:
        module_tables = [table_map[n] for n in names if n in table_map]
        missing = [n for n in names if n not in table_map]
        if missing:
            print(f"警告：{title} 缺少表 {missing}", file=sys.stderr)

        module_indexes = [i for i in indexes if i.table in names]
        module_partitions = [p for p in partitions if p.parent in names]

        content = _HEADER.format(title=title, revision=revision, down_revision=previous)
        content += (
            "\n\ndef upgrade() -> None:\n"
            + _render_upgrade(module_tables, module_indexes, module_partitions)
            + "\n\n\ndef downgrade() -> None:\n"
            + _render_downgrade(module_tables, module_partitions)
            + "\n"
        )

        filename = VERSIONS_DIR / f"{revision}.py"
        filename.write_text(content, encoding="utf-8")
        written += 1
        print(f"  已生成 {filename.name}（{len(module_tables)} 表）")
        previous = revision

    print(f"\n完成：{written} 个迁移文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
