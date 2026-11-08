"""Alembic 迁移环境（异步）。"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# 确保所有模型被导入，autogenerate 才能发现表
import app.db.models  # noqa: F401
from app.core.config import settings
from app.db.base import Base
from app.db.migrations.filters import include_object as _include_object

config = context.config
config.set_main_option("sqlalchemy.url", settings.alembic_url)

# 只在命令行执行迁移时接管日志配置。
# 应用内或测试中调用 alembic（如集成测试）时，fileConfig 会清空并重置
# root logger 的 handler，导致后续用例的 caplog 失效。
# 约定：调用方传入 `configure_logger=False` 即跳过。
if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata




def run_migrations_offline() -> None:
    context.configure(
        url=settings.alembic_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: object) -> None:
    context.configure(
        connection=connection,  # type: ignore[arg-type]
        target_metadata=target_metadata,
        compare_type=True,
        include_schemas=False,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
