"""健康检查端点。Nginx 与容器编排依赖它判断存活。"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.response import success
from app.db.session import check_database
from app.infra.clients import check_all
from app.infra.redis import check_redis

router = APIRouter()


@router.get("/health", summary="存活探针")
async def health() -> dict[str, object]:
    """仅判断进程存活，不探测外部依赖，避免级联失败。"""
    return success({"status": "ok"})


@router.get("/health/ready", summary="就绪探针")
async def readiness() -> dict[str, object]:
    """探测全部依赖，任一不可用则返回 degraded。"""
    db_ok = await check_database()
    redis_ok = await check_redis()
    external = await check_all()

    dependencies = {"postgres": db_ok, "redis": redis_ok, **external}
    healthy = all(dependencies.values())

    return success({"status": "ready" if healthy else "degraded", "dependencies": dependencies})
