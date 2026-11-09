"""FastAPI 应用入口。

分层：core（基础设施）/ api（路由）/ modules（业务）/ db / infra / tasks。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware.audit import OperationLogMiddleware
from app.api.middleware.logging import RequestContextMiddleware
from app.api.router import api_router
from app.core.config import settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import setup_logging
from app.db.session import dispose_engine
from app.infra.clients import close_all
from app.infra.redis import close_redis


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 生产环境强制不低于 INFO：DEBUG 会打印 SQL 参数与请求细节
    setup_logging(
        settings.log_level,
        settings.log_json,
        force_info=settings.app_env == "production",
    )
    yield
    await close_redis()
    await close_all()
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="1.0.0",
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url="/redoc" if settings.app_env != "production" else None,
        openapi_url="/openapi.json" if settings.app_env != "production" else None,
        lifespan=lifespan,
    )

    # 中间件注册顺序与执行顺序相反：后注册的先执行。
    # OperationLogMiddleware 需要在 require_admin 写入 admin_id 之后
    # 才能记录日志，而 admin_id 是由路由依赖写入的，因此它应
    # 在请求处理链的外层（即先注册）。
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(OperationLogMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)
    # api_prefix 已含 /api 与版本段，此处不能再加前缀，否则会拼成 /api/api/v1
    app.include_router(api_router)

    return app


app = create_app()
