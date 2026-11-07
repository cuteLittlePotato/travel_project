"""Redis 客户端封装。

部署约束：**DB 0 供业务使用，DB 1 被 Langfuse 占用**，业务代码只允许访问 DB 0。
Redis 仅为加速层，不可用时业务应降级直读 PostgreSQL，而非整体崩溃。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.exceptions import BusinessError

#: 业务逻辑库，禁止改动
BUSINESS_DB = settings.redis_db_business
#: Langfuse 占用，仅用于说明，业务代码不可访问
LANGFUSE_DB = settings.redis_db_langfuse

_client: aioredis.Redis | None = None


def create_client(db: int = BUSINESS_DB) -> aioredis.Redis:
    if db == LANGFUSE_DB:
        raise BusinessError(
            10002,
            f"业务代码禁止访问 Redis DB {LANGFUSE_DB}（被 Langfuse 占用）",
        )
    return aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password or None,
        db=db,
        max_connections=settings.redis_max_connections,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
        health_check_interval=30,
    )


def get_client() -> aioredis.Redis:
    """进程内单例。"""
    global _client
    if _client is None:
        _client = create_client()
    return _client


async def get_redis() -> AsyncIterator[aioredis.Redis]:
    """FastAPI 依赖。"""
    yield get_client()


async def check_redis() -> bool:
    return bool(await get_client().ping())


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
