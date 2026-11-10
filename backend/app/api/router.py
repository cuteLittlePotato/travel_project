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
from app.api.v1.b_end import auth as b_end_auth
from app.api.v1.b_end import catalog as b_end_catalog
from app.api.v1.b_end import models as b_end_models
from app.api.v1.b_end import system as b_end_system
from app.api.v1.c_end import attractions as c_end_attractions
from app.api.v1.c_end import auth as c_end_auth
from app.api.v1.c_end import notifications as c_end_notifications
from app.api.v1.c_end import regions as c_end_regions
from app.api.v1.c_end import users as c_end_users
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

# ---------- C 端业务 ----------
# M01 认证：§3.1 发送验证码、§3.2 注册
c_end_router.include_router(c_end_auth.router, prefix="/auth", tags=["认证"])
c_end_router.include_router(c_end_users.router, prefix="/users", tags=["用户资料"])
c_end_router.include_router(
    c_end_notifications.router, prefix="/notifications", tags=["通知"]
)
# 地区字典：公开数据，筛选与个人资料共用
c_end_router.include_router(c_end_regions.router, tags=["地区"])
# M02 景点内容：列表 / 详情 / 分类 / 搜索建议
c_end_router.include_router(c_end_attractions.router, tags=["景点"])

# ---------- B 端业务 ----------
# M11 基础数据：省市、分类、景点、餐厅、酒店、活动
b_end_router.include_router(b_end_catalog.router, tags=["B端基础数据"])
# M12 模型管理：模型 CRUD
b_end_router.include_router(b_end_models.router, tags=["B端模型管理"])
# M15 系统管理：管理员 CRUD + 角色权限
b_end_router.include_router(b_end_system.router, tags=["B端系统管理"])
# M15 管理员认证：登录 / 登出 / 改密
b_end_router.include_router(b_end_auth.router, tags=["B端认证"])

api_router = APIRouter()
api_router.include_router(ops_router, prefix=OPS_PREFIX)
api_router.include_router(c_end_router, prefix=settings.api_prefix)
api_router.include_router(b_end_router, prefix=f"{settings.api_prefix}/admin")
