"""全局异常处理器。

所有异常在此转换为 ``{code, message, data}``，业务代码不重复捕获。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import BusinessError, ErrorCode
from app.core.response import error

logger = logging.getLogger(__name__)


def _json(payload: dict[str, Any], status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=payload)


def _format_validation_errors(exc: RequestValidationError) -> list[dict[str, str]]:
    """把 Pydantic v2 的错误结构压平成 ``[{field, reason}]``。

    字段路径去掉 ``body`` / ``query`` 等位置前缀，只保留业务字段名。
    """
    errors: list[dict[str, str]] = []
    for item in exc.errors():
        loc = [str(p) for p in item.get("loc", ()) if p not in ("body", "query", "path", "header")]
        field = ".".join(loc) or "__root__"
        errors.append({"field": field, "reason": item.get("msg", "参数不合法")})
    return errors


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        payload = error(
            ErrorCode.VALIDATION_FAILED,
            "参数校验失败",
            {"errors": _format_validation_errors(exc)},
        )
        return _json(payload, 400)

    @app.exception_handler(BusinessError)
    async def _business_handler(request: Request, exc: BusinessError) -> JSONResponse:
        if exc.http_status >= 500:
            logger.exception("业务异常（服务端错误）: %s", exc.message)
        else:
            logger.info("业务异常: code=%s message=%s path=%s", exc.code, exc.message, request.url.path)
        return _json(error(exc.code, exc.message, exc.data), exc.http_status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # 框架层（路由不存在、405 等）直接抛出的 HTTPException 也包成统一结构
        code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.INTERNAL_ERROR
        if exc.status_code < 500 and exc.status_code != 404:
            code = ErrorCode.VALIDATION_FAILED
        return _json(error(code, str(exc.detail)), exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # 完整堆栈只进服务端日志，响应体不含任何内部细节
        logger.exception("未捕获异常: %s %s", request.method, request.url.path)
        return _json(error(ErrorCode.INTERNAL_ERROR, "服务端内部错误"), 500)
