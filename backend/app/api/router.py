"""总路由注册。

C 端：``/api/v1/*``
B 端：``/api/v1/admin/*``

新模块完成路由后在此登记，保持单一入口。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import health

api_router = APIRouter()

# ---------- 系统 ----------
api_router.include_router(health.router, tags=["系统"])

# ---------- C 端（M01~M05 完成后在此登记） ----------
c_end_router = APIRouter(prefix="/v1")
# c_end_router.include_router(auth.router, prefix="/auth", tags=["认证"])

# ---------- B 端（M09~M16 完成后在此登记） ----------
b_end_router = APIRouter(prefix="/v1/admin")
# b_end_router.include_router(admin_auth.router, prefix="/auth", tags=["B端认证"])

api_router.include_router(c_end_router)
api_router.include_router(b_end_router)
