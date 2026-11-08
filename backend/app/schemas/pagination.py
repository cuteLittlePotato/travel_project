"""分页与查询参数（API 设计 §1.4 / §1.5）。

职责划分：
    - **本文件**：请求侧参数模型（`PageQuery` / `SortQuery` / `CommonQuery`）与分页响应构造
    - `app.schemas.common`：响应侧 Pydantic 模型（`PageData[T]`），供 ``response_model`` 使用
    - `app.utils.query`：排序字段白名单校验与 SQL 排序构造

约束（API §1.4）：
    - 页码从 1 开始
    - ``page_size`` 默认 20，上限 100
    - ``total=0`` 时 ``total_pages`` 返回 **0**（前端据此判断空态）
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import Query
from pydantic import BaseModel, Field

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

#: 深分页阈值。超过此页数时 PostgreSQL 的 OFFSET 会扫描并丢弃大量行，
#: 建议业务侧改用游标分页或增加过滤条件缩小范围。
DEEP_PAGE_THRESHOLD = 100


class PageQuery(BaseModel):
    """分页请求参数。"""

    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=f"每页条数，1-{MAX_PAGE_SIZE}",
    )

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def is_deep_page(self) -> bool:
        """是否为深分页，供业务层决定是否拒绝或告警。"""
        return self.page > DEEP_PAGE_THRESHOLD


class SortQuery(BaseModel):
    """排序参数。``sort_by`` 需经白名单校验，见 ``utils/query.py``。"""

    sort_by: str | None = Field(default=None, description="排序字段，需在白名单内")
    sort_order: Literal["asc", "desc"] = Field(default="desc", description="排序方向")


class CommonQuery(PageQuery, SortQuery):
    """分页 + 排序 + 关键词，B 端列表接口的通用入参（API §1.5）。"""

    keyword: str | None = Field(default=None, max_length=100, description="关键词模糊搜索")
    status: str | None = Field(default=None, max_length=50, description="状态筛选")


def page_params(
    page: Annotated[int, Query(ge=1, description="页码，从 1 开始")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description=f"每页条数，1-{MAX_PAGE_SIZE}")
    ] = DEFAULT_PAGE_SIZE,
) -> PageQuery:
    """FastAPI 依赖：解析分页参数。

    校验失败由全局异常处理器转成 ``400 + code=10001``，与 API §1.3 一致。
    """
    return PageQuery(page=page, page_size=page_size)


def sort_params(
    sort_by: Annotated[str | None, Query(description="排序字段")] = None,
    sort_order: Annotated[
        Literal["asc", "desc"], Query(description="排序方向")
    ] = "desc",
) -> SortQuery:
    """FastAPI 依赖：解析排序参数。字段合法性由 ``apply_sort`` 校验。"""
    return SortQuery(sort_by=sort_by, sort_order=sort_order)


def build_page[T](
    items: list[T],
    total: int,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """构造分页响应体，字段与 API 设计 §1.4 一致。

    ``total=0`` 时 ``total_pages`` 返回 0（而非 1），前端据此显示空态。
    """
    total_pages = 0 if total <= 0 else (total + page_size - 1) // page_size
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
