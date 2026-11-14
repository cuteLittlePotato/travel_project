"""M0-T13 数据库迁移基线的测试。

覆盖 DoD：
    1. upgrade head 后表数量为 43（不含分区子表）
    2. downgrade base 可完全回滚
    3. 迁移脚本无 FOREIGN KEY / REFERENCES
    4. 无 SERIAL / BIGSERIAL
    5. 表名字段名为 snake_case

不需要真实数据库的部分放在 TestMigrationScripts（静态检查），
需要数据库的放在 TestMigrationExecution（标 integration，不可达时跳过）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
VERSIONS_DIR = BACKEND_DIR / "app" / "db" / "migrations" / "versions"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
SCHEMA_SQL = BACKEND_DIR.parent / "scripts" / "sql" / "schema.sql"

#: 期望的主表数量（不含 6 个分区子表与 alembic_version）
EXPECTED_TABLE_COUNT = 43


def _migration_files() -> list[Path]:
    return sorted(p for p in VERSIONS_DIR.glob("*.py") if not p.name.startswith("__"))


def _alembic_config():
    """构造 Alembic Config。script_location 用绝对路径，避免受 cwd 影响。"""
    from alembic.config import Config

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_DIR / "app" / "db" / "migrations"))
    # 不在测试里让 alembic 接管日志配置：env.py 的 fileConfig 会清空 root
    # handler，导致同一次 pytest 运行中后续用例的 caplog 失效
    config.attributes["configure_logger"] = False
    return config


# ============================================================
# 静态检查（无需数据库）
# ============================================================


class TestMigrationScripts:
    def test_migration_files_exist(self) -> None:
        files = _migration_files()
        assert len(files) >= 14, f"迁移文件过少: {[f.name for f in files]}"

    def test_no_physical_foreign_key(self) -> None:
        """DoD：迁移脚本中不得出现 FOREIGN KEY / REFERENCES。"""
        offenders: list[str] = []
        for path in _migration_files():
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                lowered = stripped.lower()
                if "foreign key" in lowered or re.search(r"\breferences\s+\w", lowered):
                    offenders.append(f"{path.name}:{lineno}")
        assert not offenders, f"发现物理外键: {offenders}"

    def test_no_serial_primary_key(self) -> None:
        """DoD：主键必须是 UUID，不得用 SERIAL/BIGSERIAL。"""
        offenders: list[str] = []
        for path in _migration_files():
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                # 跳过文档字符串里的说明文字
                if "无 SERIAL" in line or ("BIGSERIAL" in line and "#" in line):
                    continue
                if re.search(
                    r"\bSERIAL\b|\bBIGSERIAL\b|nextval\(", line, re.I
                ) and line.lstrip().startswith(("sa.Column", '"')):
                    offenders.append(f"{path.name}:{lineno}")
        assert not offenders, f"发现自增主键: {offenders}"

    def test_primary_keys_are_uuid(self) -> None:
        """所有 primary_key=True 的列必须是 postgresql.UUID。"""
        offenders: list[str] = []
        for path in _migration_files():
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "primary_key=True" in line and "postgresql.UUID" not in line:
                    offenders.append(f"{path.name}:{lineno}: {line.strip()[:80]}")
        assert not offenders, f"非 UUID 主键: {offenders}"

    def test_table_names_are_snake_case(self) -> None:
        pattern = re.compile(r'op\.create_table\(\s*\n\s*"(\w+)"')
        for path in _migration_files():
            for name in pattern.findall(path.read_text(encoding="utf-8")):
                assert re.fullmatch(r"[a-z][a-z0-9_]*", name), f"非法表名: {name}"

    def test_revision_chain_is_linear(self) -> None:
        """每个迁移的 down_revision 必须是上一个的 revision，不能分叉。"""
        revisions: dict[str, str | None] = {}
        for path in _migration_files():
            content = path.read_text(encoding="utf-8")
            rev = re.search(r'^revision: str = "([^"]+)"', content, re.M)
            down = re.search(r'^down_revision: str \| None = (?:"([^"]+)"|None)', content, re.M)
            if rev:
                revisions[rev.group(1)] = down.group(1) if down and down.group(1) else None

        assert len(revisions) == len(_migration_files()), "有迁移文件缺少 revision 声明"
        assert sum(1 for v in revisions.values() if v is None) == 1, "只能有一个基线迁移"

        # 每个非基线 revision 都应被恰好引用一次
        referenced = [v for v in revisions.values() if v]
        assert len(referenced) == len(set(referenced)), "down_revision 有重复，存在分叉"

    def test_upgrade_and_downgrade_defined(self) -> None:
        for path in _migration_files():
            content = path.read_text(encoding="utf-8")
            assert "def upgrade() -> None:" in content, f"{path.name} 缺 upgrade"
            assert "def downgrade() -> None:" in content, f"{path.name} 缺 downgrade"

    def test_partition_tables_declared(self) -> None:
        """分区表必须在建表时声明 postgresql_partition_by。"""
        content = "".join(p.read_text(encoding="utf-8") for p in _migration_files())
        assert 'postgresql_partition_by="RANGE (created_at)"' in content
        # 两个分区表
        assert content.count('postgresql_partition_by="RANGE (created_at)"') == 2

    def test_partition_children_created(self) -> None:
        content = "".join(p.read_text(encoding="utf-8") for p in _migration_files())
        for table in ("model_call_log", "user_event"):
            assert f"{table}_p2026_11" in content
            assert f"{table}_default" in content

    def test_trigger_function_in_baseline(self) -> None:
        baseline = next(p for p in _migration_files() if "baseline" in p.name)
        content = baseline.read_text(encoding="utf-8")
        assert "trigger_set_updated_at" in content
        assert "pg_trgm" in content


class TestSchemaConsistency:
    """迁移与 schema.sql 的一致性。"""

    def test_table_count_matches_schema_sql(self) -> None:
        """迁移中建的表数应与 schema.sql 的主表数一致。"""
        sql = SCHEMA_SQL.read_text(encoding="utf-8")
        schema_tables = {
            m.group(1)
            for m in re.finditer(r"^CREATE TABLE (\w+)\s*\(", sql, re.M)
            if "PARTITION OF" not in sql[m.start(): m.start() + 120]
        }

        pattern = re.compile(r'op\.create_table\(\s*\n\s*"(\w+)"')
        migration_tables: set[str] = set()
        for path in _migration_files():
            migration_tables.update(pattern.findall(path.read_text(encoding="utf-8")))

        assert len(migration_tables) == EXPECTED_TABLE_COUNT
        assert migration_tables == schema_tables, (
            f"仅迁移有: {migration_tables - schema_tables}；"
            f"仅 schema.sql 有: {schema_tables - migration_tables}"
        )

    def test_all_schema_tables_covered(self) -> None:
        """schema.sql 的每张主表都必须在某个迁移中出现。"""
        sql = SCHEMA_SQL.read_text(encoding="utf-8")
        schema_tables = {
            m.group(1)
            for m in re.finditer(r"^CREATE TABLE (\w+)\s*\(", sql, re.M)
            if "PARTITION OF" not in sql[m.start(): m.start() + 120]
        }
        assert len(schema_tables) == EXPECTED_TABLE_COUNT

        migration_content = "".join(p.read_text(encoding="utf-8") for p in _migration_files())
        missing = [t for t in schema_tables if f'"{t}"' not in migration_content]
        assert not missing, f"未覆盖的表: {missing}"


# ============================================================
# 真实数据库执行（integration）
# ============================================================

pytestmark_integration = pytest.mark.integration


@pytest.mark.integration
@pytest.mark.destructive
class TestMigrationExecution:
    """需要真实数据库。先在空库上 upgrade head，再 downgrade base。

    运行前请确保数据库可用且可被清空（会 DROP SCHEMA public）。
    """

    @pytest.fixture(scope="class")
    async def migrated(self):
        from sqlalchemy import text

        from app.db.session import engine

        async def _reset() -> None:
            async with engine.begin() as conn:
                await conn.exec_driver_sql("DROP SCHEMA public CASCADE")
                await conn.exec_driver_sql("CREATE SCHEMA public")

        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            pytest.skip("数据库不可达")

        await _reset()
        yield
        await engine.dispose()

    async def test_upgrade_creates_43_tables(self, migrated: None) -> None:
        from alembic import command
        from sqlalchemy import text

        from app.db.session import engine

        config = _alembic_config()

        # Alembic 是同步 API，放到线程池执行
        import asyncio

        await asyncio.to_thread(command.upgrade, config, "head")

        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT count(*) FROM pg_tables WHERE schemaname='public' "
                    "AND tablename NOT LIKE '%\\_p2026\\_%' "
                    "AND tablename NOT LIKE '%\\_default' "
                    "AND tablename != 'alembic_version'"
                )
            )
            assert result.scalar() == EXPECTED_TABLE_COUNT

    async def test_downgrade_removes_all(self, migrated: None) -> None:
        from alembic import command
        from sqlalchemy import text

        from app.db.session import engine

        config = _alembic_config()

        import asyncio

        await asyncio.to_thread(command.upgrade, config, "head")
        await asyncio.to_thread(command.downgrade, config, "base")

        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")
            )
            # 只剩 alembic_version
            assert result.scalar() <= 1
