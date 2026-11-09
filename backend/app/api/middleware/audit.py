"""操作日志的自动记录中间件（M15-T06）。

**为什么用中间件而不是每个路由手动调用**：
    56 个写接口，逐个加 `await write_operation_log(...)` 既容易漏，
    也会让路由函数淹没在日志代码里。中间件统一处理，
    新增接口自动获得审计能力。

**为什么不用 BackgroundTask**：
    FastAPI 的 ``BackgroundTask`` 在响应发送后执行，但它依附于
    请求作用域，一旦依赖的 session 关闭就拿不到数据库连接。
    这里改用「中间件内独立 session + 忽略异常」，效果等价且更可控。
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.api.middleware.operation_log import (
    build_log_entity,
    should_log,
)

logger = logging.getLogger(__name__)

#: 不记录日志的路径前缀（认证接口单独处理登录/登出事件）
SKIP_PREFIXES = (
    "/api/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)

#: B 端后台路径前缀
ADMIN_PREFIX = "/api/v1/admin"


class OperationLogMiddleware(BaseHTTPMiddleware):
    """自动记录 B 端写操作。

    只处理 ``/api/v1/admin/*`` 下的 POST/PUT/PATCH/DELETE。
    管理员身份从 ``request.state.current_admin_id`` 取——由
    ``require_admin`` 依赖写入。取不到说明未通过认证，
    此时请求会被拒，也不需要记日志。
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        if not self._should_record(request):
            return response

        # 优先用 require_admin 写入的值（真实运行时一定有）；
        # 测试里 require_admin 常被 dependency_overrides 替换，
        # 此时回退到直接从 Authorization 头解析，保证中间件自给自足。
        admin_id = getattr(request.state, "current_admin_id", None)
        if admin_id is None:
            admin_id = self._admin_id_from_token(request)
        if admin_id is None:
            return response

        await self._record(request, admin_id, is_success=response.status_code < 400)
        return response

    @staticmethod
    def _admin_id_from_token(request: Request) -> object | None:
        """从 Authorization 头解析管理员 ID。

        只用于补位——正常情况下 ``require_admin`` 已写入 state。
        解析失败返回 ``None``，不记日志（未认证请求本就不该有审计记录）。
        """
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return None

        try:
            from app.core.security import decode_token

            payload = decode_token(header[7:], expected_type="access")
            if payload.user_type != "admin":
                return None
            return payload.subject_id
        except Exception:
            return None

    @staticmethod
    def _should_record(request: Request) -> bool:
        path = request.url.path

        if any(path.startswith(prefix) for prefix in SKIP_PREFIXES):
            return False
        if not path.startswith(ADMIN_PREFIX):
            return False
        # 登录/登出由 M15-T08 单独记录（动作是 login/logout，非 CRUD）
        if "/auth/" in path:
            return False

        return should_log(request.method)

    @staticmethod
    async def _record(request: Request, admin_id, *, is_success: bool) -> None:
        """独立 session 写日志，失败不影响响应。"""
        from app.db.session import SessionLocal

        log = build_log_entity(
            admin_id=admin_id, request=request, is_success=is_success
        )

        try:
            async with SessionLocal() as session:
                session.add(log)
                await session.commit()
        except Exception:
            logger.warning(
                "操作日志写入失败 path=%s method=%s",
                request.url.path,
                request.method,
                exc_info=True,
            )


__all__ = ["ADMIN_PREFIX", "SKIP_PREFIXES", "OperationLogMiddleware"]
