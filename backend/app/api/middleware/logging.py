"""请求日志与追踪中间件。

职责：
    - 为每个请求分配 ``request_id``（可由上游通过 ``X-Request-ID`` 传入）
    - 记录方法、路径、状态码、耗时
    - **不打印请求体全文**（可能含密码、大文件），只记录长度
    - 响应头回写 ``X-Request-ID``，便于前端与服务端日志对齐

与 ``core/logging.py`` 的分工：那里定义格式器与脱敏规则，
这里只负责「在请求边界上采集什么信息」。
"""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.context import new_request_id, reset_request_id, set_request_id

logger = logging.getLogger("app.access")

#: 超过该耗时视为慢请求，日志级别升为 WARNING 以便告警
SLOW_REQUEST_THRESHOLD_MS = 1000.0

#: 这些路径不记访问日志（探针高频调用，日志噪音大）
SKIP_PATHS = frozenset({"/api/health", "/health", "/metrics", "/favicon.ico"})

#: 请求体中超过该长度不记录（只记长度）
MAX_BODY_LOG_BYTES = 1024


def _client_ip(request: Request) -> str:
    """取真实客户端 IP。

    经过 Nginx 时 ``request.client.host`` 是反代地址，
    优先使用 ``X-Forwarded-For`` 的第一段。
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "-"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """请求追踪与访问日志。"""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        token = set_request_id(request_id)
        started = time.perf_counter()

        status_code = 500
        error: Exception | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            error = exc
            raise
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            reset_request_id(token)

            if request.url.path not in SKIP_PATHS:
                self._log_request(request, request_id, status_code, elapsed_ms, error)

        response.headers["X-Request-ID"] = request_id
        return response

    @staticmethod
    def _log_request(
        request: Request,
        request_id: str,
        status_code: int,
        elapsed_ms: float,
        error: Exception | None,
    ) -> None:
        fields = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query": request.url.query or None,
            "status": status_code,
            "elapsed_ms": elapsed_ms,
            "client_ip": _client_ip(request),
            # 只记长度，不记内容——请求体可能含密码或大文件
            "content_length": request.headers.get("content-length"),
            "user_agent": request.headers.get("user-agent"),
        }

        if error is not None or status_code >= 500:
            logger.error(
                "%s %s -> %s (%.2fms)",
                request.method,
                request.url.path,
                status_code,
                elapsed_ms,
                extra={"extra_fields": fields},
                exc_info=error,
            )
        elif elapsed_ms >= SLOW_REQUEST_THRESHOLD_MS:
            logger.warning(
                "慢请求 %s %s -> %s (%.2fms)",
                request.method,
                request.url.path,
                status_code,
                elapsed_ms,
                extra={"extra_fields": fields},
            )
        else:
            logger.info(
                "%s %s -> %s (%.2fms)",
                request.method,
                request.url.path,
                status_code,
                elapsed_ms,
                extra={"extra_fields": fields},
            )
