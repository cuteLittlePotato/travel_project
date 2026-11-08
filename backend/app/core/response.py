"""统一响应构造函数（API 设计 §1.3）。

路由层直接 ``return success(data)``，返回的是普通 dict，由 FastAPI 序列化。
响应**模型**定义在 ``app/schemas/common.py``，供 ``response_model`` 与
OpenAPI 文档使用。
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import ErrorCode


def success(data: Any = None, message: str = "ok") -> dict[str, Any]:
    """构造成功响应体。``code=0``。"""
    return {"code": ErrorCode.SUCCESS, "message": message, "data": data}


def error(code: int, message: str, data: Any = None) -> dict[str, Any]:
    """构造失败响应体。``code`` 为业务错误码。"""
    return {"code": code, "message": message, "data": data}


def validation_error(errors: list[dict[str, str]]) -> dict[str, Any]:
    """构造参数校验失败响应体，``data.errors`` 为字段级详情。"""
    return error(ErrorCode.VALIDATION_FAILED, "参数校验失败", {"errors": errors})
