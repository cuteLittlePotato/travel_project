"""全局异常处理器（API 设计 §1.3）。

所有异常在此转换为 ``{code, message, data}``，业务代码不重复捕获。

处理顺序说明：Starlette 按注册顺序反向匹配，``Exception`` 必须最后兜底，
否则会吞掉更具体的处理器。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import BusinessError, ErrorCode
from app.core.response import error, validation_error

logger = logging.getLogger(__name__)

#: 请求体位置前缀，格式化字段名时剔除
_LOCATION_PREFIXES = frozenset({"body", "query", "path", "header", "cookie"})

#: Starlette 自带的英文 detail，前端展示不合适，替换为中文
_FRAMEWORK_DEFAULT_DETAILS = frozenset(
    {
        "Not Found",
        "Method Not Allowed",
        "Internal Server Error",
        "Bad Request",
        "Unauthorized",
        "Forbidden",
        "Too Many Requests",
    }
)

#: Pydantic 英文错误类型 -> 中文原因。命中则用中文，否则保留原始信息
_VALIDATION_MESSAGES: dict[str, str] = {
    "missing": "该字段为必填项",
    "string_type": "应为字符串",
    "int_parsing": "应为整数",
    "int_type": "应为整数",
    "float_parsing": "应为数字",
    "float_type": "应为数字",
    "bool_parsing": "应为布尔值",
    "bool_type": "应为布尔值",
    "greater_than": "取值过小",
    "greater_than_equal": "取值过小",
    "less_than": "取值过大",
    "less_than_equal": "取值过大",
    "string_too_short": "长度不足",
    "string_too_long": "长度超出限制",
    "string_pattern_mismatch": "格式不正确",
    "list_type": "应为数组",
    "dict_type": "应为对象",
    "enum": "取值不在允许范围内",
    "literal_error": "取值不在允许范围内",
    "value_error": "取值不合法",
    "json_invalid": "请求体不是合法的 JSON",
    "extra_forbidden": "不支持该字段",
}


def _format_field(loc: tuple[Any, ...]) -> str:
    """把 Pydantic 的 ``loc`` 元组转成业务字段名。

    ``("body", "address", "city")`` -> ``"address.city"``；
    纯 ``("body",)``（整体校验失败）-> ``"__root__"``。
    """
    parts = [str(item) for item in loc if item not in _LOCATION_PREFIXES]
    return ".".join(parts) or "__root__"


#: 自定义校验（field_validator / model_validator）抛出的错误类型。
#: 这类错误的 message 由我们自己写，已经是中文，**不能**被类型映射覆盖。
_CUSTOM_ERROR_TYPES = frozenset({"value_error", "assertion_error"})


def _format_reason(item: dict[str, Any]) -> str:
    """把 Pydantic 的英文错误信息转成中文。

    ``value_error`` 是自定义校验抛出的——message 由业务代码写的
    （如「结束时间必须晚于开始时间」），必须原样透传；
    用类型映射覆盖成「取值不合法」会把有用的信息抹掉。

    其余类型（``string_too_short`` / ``missing`` 等）是 Pydantic
    内置的，message 是英文，走类型映射。
    """
    error_type = str(item.get("type", ""))
    message = str(item.get("msg", "参数不合法"))

    # Pydantic 会给自定义错误加 "Value error, " 前缀，去掉更友好
    message = message.removeprefix("Value error, ")

    if error_type in _CUSTOM_ERROR_TYPES:
        return message

    # extra_forbidden 等没有中文映射的，也用原始 message（已是可读英文）
    return _VALIDATION_MESSAGES.get(error_type, message)


def format_validation_errors(exc: RequestValidationError) -> list[dict[str, str]]:
    """把 Pydantic v2 的错误列表压平成 ``[{field, reason}]``。"""
    return [
        {"field": _format_field(tuple(item.get("loc", ()))), "reason": _format_reason(item)}
        for item in exc.errors()
    ]


def _json(payload: dict[str, Any], status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=payload)


def register_exception_handlers(app: FastAPI) -> None:
    """注册全部异常处理器。在 ``create_app()`` 中调用一次。"""

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # FastAPI 的参数校验失败统一映射为 10001 / HTTP 400
        payload = validation_error(format_validation_errors(exc))
        logger.info(
            "参数校验失败 path=%s errors=%s", request.url.path, payload["data"]["errors"]
        )
        return _json(payload, 400)

    @app.exception_handler(BusinessError)
    async def _business_handler(request: Request, exc: BusinessError) -> JSONResponse:
        if exc.http_status >= 500:
            logger.exception("业务异常（服务端错误）: %s", exc.message)
        else:
            logger.info(
                "业务异常 code=%s message=%s path=%s",
                exc.code,
                exc.message,
                request.url.path,
            )
        return _json(error(exc.code, exc.message, exc.data), exc.http_status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """框架层抛出的 HTTPException（路由不存在、方法不允许等）。

        这些不是业务异常，但也要包成统一结构，避免前端拿到裸 detail。
        """
        status = exc.status_code
        if status == 404:
            code, default_message = ErrorCode.ROUTE_NOT_FOUND, "接口不存在"
        elif status == 405:
            code, default_message = ErrorCode.VALIDATION_FAILED, "请求方法不允许"
        elif status == 429:
            code, default_message = ErrorCode.RATE_LIMITED, "请求过于频繁"
        elif status >= 500:
            code, default_message = ErrorCode.INTERNAL_ERROR, "服务端内部错误"
        else:
            code, default_message = ErrorCode.VALIDATION_FAILED, "请求无法处理"

        # 业务侧显式传入的 detail 优先；框架默认的英文短语用中文兜底
        detail = exc.detail if isinstance(exc.detail, str) else ""
        if not detail or detail in _FRAMEWORK_DEFAULT_DETAILS:
            detail = default_message

        return _json(error(code, detail), status)

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        """兜底。完整堆栈只进服务端日志，响应体不含任何内部细节。"""
        logger.exception("未捕获异常: %s %s", request.method, request.url.path)
        return _json(error(ErrorCode.INTERNAL_ERROR, "服务端内部错误"), 500)
