"""总路由注册。

路径结构与 API 设计 §1.1 一致：
    C 端：``/api/v1/*``        例：/api/v1/attractions
    B 端：``/api/v1/admin/*``  例：/api/v1/admin/attractions
    运维：``/api/health``      不随 API 版本变化，供容器与 Nginx 探针使用

版本前缀统一来自 ``settings.api_prefix``，禁止在路由层硬编码。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import health
from app.core.config import settings

#: 运维探针的固定前缀，与 API 版本解耦
OPS_PREFIX = "/api"

#: 运维探针（/api/health、/api/health/ready）
ops_router = APIRouter()
ops_router.include_router(health.router, tags=["系统"])

#: C 端路由组（挂载到 /api/v1）
c_end_router = APIRouter()

#: B 端路由组（挂载到 /api/v1/admin）
b_end_router = APIRouter()

# ---------- C 端业务（M01~M05 完成后在此登记） ----------
# c_end_router.include_router(auth.router, prefix="/auth", tags=["认证"])

# ---------- B 端业务（M09~M16 完成后在此登记） ----------
# b_end_router.include_router(admin_auth.router, prefix="/auth", tags=["B端认证"])

api_router = APIRouter()
api_router.include_router(ops_router, prefix=OPS_PREFIX)
api_router.include_router(c_end_router, prefix=settings.api_prefix)
api_router.include_router(b_end_router, prefix=f"{settings.api_prefix}/admin")
