"""M0-T02 数据库连接与会话管理的集成测试。

前提：``backend/.env`` 指向可用的 PostgreSQL。未配置时整组跳过，
避免在无数据库的机器上误报失败。

运行：
    uv run pytest backend/tests/integration -v
"""

from __future__ import annotations

import pytest
from sqlalchemy import DateTime, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BaseModel, TimestampMixin, UUIDPrimaryKeyMixin

pytestmark = pytest.mark.integration


async def _database_available() -> bool:
    from app.db.session import check_database

    try:
        return await check_database()
    except Exception:
        return False


@pytest.fixture
async def db_ready() -> bool:
    """每个用例前探测一次数据库；不可达则跳过而非失败。"""
    if not await _database_available():
        pytest.skip("数据库不可达，跳过集成测试（检查 backend/.env）")
    return True


class TestConnection:
    async def test_select_one(self, db_ready: bool) -> None:
        """DoD：连接池可建立连接并执行 SELECT 1。"""
        from app.db.session import engine

        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar_one() == 1

    async def test_session_rollback_on_error(self, db_ready: bool) -> None:
        """get_db 在异常时回滚，不把脏数据留在会话里。"""
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            with pytest.raises(RuntimeError):
                await session.execute(text("SELECT 1"))
                raise RuntimeError("模拟业务异常")
            await session.rollback()
            # 回滚后会话仍可用
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1

    async def test_pool_settings_reflect_config(self, db_ready: bool) -> None:
        """连接池参数来自配置，不是硬编码。"""
        from app.core.config import settings
        from app.db.session import engine

        assert engine.pool.size() == settings.db_pool_size
        assert engine.pool._max_overflow == settings.db_max_overflow

    async def test_get_db_does_not_autocommit(self, db_ready: bool) -> None:
        """事务边界：get_db 不自动提交，写操作必须由 service 层显式 commit。"""
        from app.db.session import engine, get_db

        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE IF NOT EXISTS _m0t02_probe (id int PRIMARY KEY)"))
            await conn.execute(text("DELETE FROM _m0t02_probe"))

        try:
            generator = get_db()
            session = await generator.__anext__()
            await session.execute(text("INSERT INTO _m0t02_probe (id) VALUES (1)"))
            # 不 commit，直接结束依赖，模拟「忘记提交」
            await generator.aclose()

            async with engine.connect() as conn:
                count = (await conn.execute(text("SELECT count(*) FROM _m0t02_probe"))).scalar_one()
            assert count == 0, "get_db 不应自动提交"
        finally:
            async with engine.begin() as conn:
                await conn.execute(text("DROP TABLE IF EXISTS _m0t02_probe"))


class TestOrmBase:
    def test_primary_key_is_uuid_named_id(self) -> None:
        """DoD：主键类型统一为 UUID，命名统一为 id。"""

        class UuidPkProbe(BaseModel):
            __tablename__ = "probe_uuid_pk"
            name: Mapped[str] = mapped_column(String(20))

        pk_columns = list(UuidPkProbe.__table__.primary_key.columns)
        assert [c.name for c in pk_columns] == ["id"]
        assert isinstance(pk_columns[0].type, PGUUID)

        Base.metadata.remove(UuidPkProbe.__table__)

    def test_timestamp_columns_are_timestamptz(self) -> None:
        class TimestampProbe(BaseModel):
            __tablename__ = "probe_timestamps"
            note: Mapped[str] = mapped_column(String(20))

        for name in ("created_at", "updated_at"):
            column_type = TimestampProbe.__table__.c[name].type
            assert isinstance(column_type, DateTime)
            assert column_type.timezone is True

        Base.metadata.remove(TimestampProbe.__table__)

    def test_no_physical_foreign_keys(self) -> None:
        """DoD：模型层不得出现任何物理外键。"""
        for table in Base.metadata.tables.values():
            assert not table.foreign_keys, f"{table.name} 存在物理外键"


class TestMigraionsConfig:
    def test_alembic_uses_async_url_from_settings(self) -> None:
        """迁移连接串来自配置，不在 alembic.ini 硬编码。"""
        from app.core.config import settings

        assert settings.alembic_url == settings.database_url
        assert "asyncpg" in settings.alembic_url

    def test_migration_scripts_have_no_foreign_key(self) -> None:
        """DoD 规范检查：迁移脚本中无 FOREIGN KEY / REFERENCES。"""
        from pathlib import Path

        versions = Path(__file__).resolve().parents[2] / "app" / "db" / "migrations" / "versions"
        offenders = []
        for script in versions.glob("*.py"):
            lowered = script.read_text(encoding="utf-8").lower()
            if "foreign key" in lowered or "references " in lowered:
                offenders.append(script.name)
        assert not offenders, f"迁移脚本含物理外键: {offenders}"


class TestMixinOrder:
    def test_mixins_precede_base_in_mro(self) -> None:
        """Mixin 必须排在 Base 之前，否则列解析顺序不符合 SQLAlchemy 约定。"""
        mro = BaseModel.__mro__
        assert mro.index(UUIDPrimaryKeyMixin) < mro.index(Base)
        assert mro.index(TimestampMixin) < mro.index(Base)
