"""统一响应封装。"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse[T](BaseModel):
    """统一响应结构：``{code, message, data}``。"""

    code: int = 0
    message: str = "ok"
    data: T | None = None


def success(data: Any = None, message: str = "ok") -> dict[str, Any]:
    """构造成功响应体。路由层直接返回该 dict，由 FastAPI 序列化。"""
    return {"code": 0, "message": message, "data": data}


def error(code: int, message: str, data: Any = None) -> dict[str, Any]:
    """构造失败响应体。"""
    return {"code": code, "message": message, "data": data}


class PageResult[T](BaseModel):
    """分页响应体，字段顺序与 API 设计 §1.4 一致。"""

    items: list[T] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 0
