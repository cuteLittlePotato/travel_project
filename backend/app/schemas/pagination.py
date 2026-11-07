"""统一分页与查询参数（API §1.4 / §1.5）。"""

from __future__ import annotations

from typing import Annotated, Literal, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class PageQuery(BaseModel):
    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PageMeta(BaseModel):
    total: int = 0
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    @property
    def total_pages(self) -> int:
        # total=0 时返回 0，与前端空态判断保持一致
        if self.total <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size


class PageData[T](BaseModel):
    items: list[T] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    total_pages: int = 0


class SortQuery(BaseModel):
    sort_by: str | None = None
    sort_order: Literal["asc", "desc"] = "desc"


def page_params(
    page: Annotated[int, Query(ge=1, description="页码，从 1 开始")] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description="每页条数")] = DEFAULT_PAGE_SIZE,
) -> PageQuery:
    """FastAPI 依赖：从查询参数解析分页。"""
    return PageQuery(page=page, page_size=page_size)


def build_page[T](
    items: list[T],
    total: int,
    page: int,
    page_size: int,
) -> dict[str, object]:
    """构造分页响应体。"""
    total_pages = 0 if total <= 0 else (total + page_size - 1) // page_size
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
