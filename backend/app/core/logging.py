"""结构化日志与请求追踪。"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

#: 贯穿一次请求的追踪 ID，日志格式器会读取它
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_SENSITIVE_KEYS = ("password", "token", "secret", "api_key", "credential", "authorization")
_REDACTED = "***"


class JsonFormatter(logging.Formatter):
    """输出单行 JSON，便于日志采集。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_ctx.get(),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = _redact(key, value)
        return json.dumps(payload, ensure_ascii=False)


def _redact(key: str, value: Any) -> Any:
    if any(token in key.lower() for token in _SENSITIVE_KEYS):
        return _REDACTED
    return value


def setup_logging(level: str = "INFO", as_json: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if as_json
        else logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn 自带 handler 会造成重复输出，统一交给 root
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True


class RequestContextMiddleware(BaseHTTPMiddleware):
    """为每个请求分配 ``request_id`` 并记录耗时。"""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            request_id_ctx.reset(token)

        response.headers["X-Request-ID"] = request_id
        logging.getLogger("app.access").info(
            "%s %s -> %s",
            request.method,
            request.url.path,
            response.status_code,
            extra={
                "extra_fields": {
                    "elapsed_ms": elapsed_ms,
                    "request_id": request_id,
                }
            },
        )
        return response
