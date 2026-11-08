"""Redis 客户端封装。

部署约束（架构 §1.6 决策 3）：
    - **DB 0 供业务使用，DB 1 被 Langfuse 占用**，业务代码只允许访问 DB 0
    - Redis 仅为加速层，PG 才是权威源。Redis 不可用时业务应降级为直读 PG，
      **服务不中断**，因此本模块不向上抛连接异常，而是提供 ``is_available()``
      供调用方决定是否降级

降级用法：
    if not await redis.is_available():
        return await repository.get_from_pg(...)
    try:
        cached = await redis.get(key)
    except RedisUnavailableError:
        return await repository.get_from_pg(...)
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.exceptions import BusinessError

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: 业务逻辑库，禁止改动
BUSINESS_DB = settings.redis_db_business
#: Langfuse 占用，仅用于说明，业务代码不可访问
LANGFUSE_DB = settings.redis_db_langfuse

#: 允许业务访问的库。当前只有 DB 0
_ALLOWED_DBS = frozenset({BUSINESS_DB})

_client: aioredis.Redis | None = None


class RedisUnavailableError(BusinessError):
    """Redis 连接或命令失败。

    调用方捕获后应降级读 PG（架构 §1.6 决策 3），而不是把错误暴露给用户。
    """

    default_http_status = 503

    def __init__(self, message: str = "缓存服务暂不可用") -> None:
        super().__init__(10002, message, http_status=503)


def _assert_db_allowed(db: int) -> None:
    """校验目标逻辑库。DB 1 被 Langfuse 占用，业务代码不得访问。"""
    if db == LANGFUSE_DB:
        raise BusinessError(
            10002,
            f"业务代码禁止访问 Redis DB {LANGFUSE_DB}（被 Langfuse 占用），"
            f"业务数据请使用 DB {BUSINESS_DB}",
        )
    if db not in _ALLOWED_DBS:
        raise BusinessError(10002, f"未授权的 Redis 逻辑库: {db}")


def create_client(db: int = BUSINESS_DB) -> aioredis.Redis:
    """创建客户端实例。

    参数全部来自配置，禁止硬编码连接串（DoD 规范检查项）。
    """
    _assert_db_allowed(db)

    return aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password or None,
        db=db,
        max_connections=settings.redis_max_connections,
        decode_responses=True,
        socket_connect_timeout=settings.redis_connect_timeout,
        socket_timeout=settings.redis_socket_timeout,
        health_check_interval=settings.redis_health_check_interval,
        retry_on_error=[ConnectionError, TimeoutError],
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
    """健康检查：PING 通即视为可用。不抛异常。"""
    try:
        return bool(await get_client().ping())
    except (RedisError, OSError):
        logger.warning("Redis 健康检查失败", exc_info=True)
        return False


async def is_available() -> bool:
    """降级判定入口。业务代码据此决定走缓存还是直读 PG。"""
    return await check_redis()


async def execute(command: Any, *args: Any, **kwargs: Any) -> Any:
    """执行一次 Redis 命令，带指数退避重试。

    仅对连接类错误重试；键不存在等业务语义错误直接返回。
    重试耗尽后抛 ``RedisUnavailableError``，由调用方降级。
    """
    last_error: Exception | None = None

    for attempt in range(settings.redis_retry_attempts):
        try:
            return await command(*args, **kwargs)
        except (ConnectionError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < settings.redis_retry_attempts - 1:
                # 指数退避 + 抖动，避免重试风暴
                delay = settings.redis_retry_backoff_base * (2**attempt)
                delay += random.uniform(0, settings.redis_retry_backoff_base)
                logger.warning("Redis 命令失败，第 %s 次重试，%.3fs 后继续", attempt + 1, delay)
                await asyncio.sleep(delay)
        except RedisError as exc:
            # 命令本身的问题（类型错误、脚本错误等），重试无意义
            logger.error("Redis 命令执行失败: %s", exc)
            raise RedisUnavailableError(str(exc)) from exc

    logger.error("Redis 重试耗尽: %s", last_error)
    raise RedisUnavailableError() from last_error


def make_key(*parts: str | int) -> str:
    """构造带项目前缀的 key，避免与其他共用实例的系统冲突。

    例：``make_key("quota", user_id, "2026-11-07")`` -> ``travel:quota:<uid>:2026-11-07``
    """
    suffix = ":".join(str(part) for part in parts)
    return f"{settings.redis_key_prefix}:{suffix}"


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
