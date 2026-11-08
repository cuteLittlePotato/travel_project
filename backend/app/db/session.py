"""数据库会话管理（SQLAlchemy 2.x + asyncpg）。

**事务边界（2026-11-07 与用户确认）**：
    - 一个请求一个会话，``get_db`` 负责请求结束或异常时回收
    - **不在依赖层自动 commit**，写操作由 service 层显式 ``await session.commit()``
    - 只读请求不提交，会话关闭时自动回滚

选择显式提交的理由：可控且便于定位问题。若依赖层自动提交，
「业务校验失败但数据已落库」这类缺陷很难通过日志复现；
代价是写接口必须记得提交，因此各模块的写操作统一收敛在 service 层完成。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,  # 连接被中间件掐断后自动重连，避免 "server closed the connection"
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每个请求一个会话，异常回滚后重新抛出。"""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def check_database() -> bool:
    """健康检查：能执行 ``SELECT 1`` 即视为可用。"""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True


async def dispose_engine() -> None:
    """应用关闭时释放连接池。"""
    await engine.dispose()
