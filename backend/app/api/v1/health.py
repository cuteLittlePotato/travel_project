"""健康检查端点。Nginx 与容器编排依赖它判断存活。

设计要点：
- ``/api/health`` 只判断进程存活，不探测外部依赖，避免级联失败。
- ``/api/health/ready`` 探测全部依赖，**任一不可达都返回 degraded 而非抛异常**，
  因为探针的价值就在于依赖故障时仍能给出可读的诊断信息。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from fastapi import APIRouter

from app.core.response import success
from app.db.session import check_database
from app.infra.clients import check_all
from app.infra.redis import check_redis

logger = logging.getLogger(__name__)

router = APIRouter()

#: 单个依赖的探测超时，避免探针被慢依赖拖死
PROBE_TIMEOUT_SECONDS = 5.0


async def _probe(name: str, check: Callable[[], Awaitable[bool]]) -> tuple[str, bool]:
    """执行单项探测。异常与超时统一记为不可用，不向上抛出。"""
    try:
        return name, bool(await asyncio.wait_for(check(), timeout=PROBE_TIMEOUT_SECONDS))
    except TimeoutError:
        logger.warning("依赖探测超时: %s", name)
        return name, False
    except Exception:
        logger.warning("依赖探测失败: %s", name, exc_info=True)
        return name, False


@router.get("/health", summary="存活探针")
async def health() -> dict[str, object]:
    """仅判断进程存活，不探测外部依赖。"""
    return success({"status": "ok"})


@router.get("/health/ready", summary="就绪探针")
async def readiness() -> dict[str, object]:
    """探测全部依赖，任一不可用则标记 degraded，但始终返回 200。"""
    results = await asyncio.gather(
        _probe("postgres", check_database),
        _probe("redis", check_redis),
        _probe_external(),
    )

    dependencies: dict[str, bool] = {}
    for item in results:
        if isinstance(item, tuple):
            name, ok = item
            dependencies[name] = ok
        else:
            dependencies.update(item)

    healthy = all(dependencies.values())

    return success({"status": "ready" if healthy else "degraded", "dependencies": dependencies})


async def _probe_external() -> dict[str, bool]:
    """Milvus / Neo4j / ES / MinIO。``check_all`` 内部已吞掉异常。"""
    try:
        return await asyncio.wait_for(check_all(), timeout=PROBE_TIMEOUT_SECONDS * 2)
    except Exception:
        logger.warning("外部服务批量探测失败", exc_info=True)
        return {"milvus": False, "neo4j": False, "elasticsearch": False, "minio": False}
