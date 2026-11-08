"""通用响应模型（API 设计 §1.3）。

放置约定：
- **模型**（``ApiResponse`` / ``PageData``）放 ``schemas/``，供路由的 ``response_model`` 与
  OpenAPI 生成使用，也是前端类型生成链路（M0-T10）的输入。
- **构造函数**（``success`` / ``error``）放 ``core/response.py``，供路由直接返回 dict。

两者分开的原因：``core`` 是基础设施层，不应被 ``schemas`` 反向依赖；
模型收敛到 ``schemas`` 后，类型生成与文档展示才有单一来源。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.exceptions import ErrorCode


class ApiResponse[T](BaseModel):
    """统一响应外壳：``{code, message, data}``。

    ``code`` 为 0 表示成功，非 0 为业务错误码（见 API §1.7 分段）。
    """

    code: int = Field(default=ErrorCode.SUCCESS, description="业务码，0 表示成功")
    message: str = Field(default="ok", description="提示信息")
    data: T | None = Field(default=None, description="业务数据")


class ValidationErrorItem(BaseModel):
    """参数校验失败的字段级详情。"""

    field: str = Field(description="出错字段，嵌套时用点号连接，如 address.city")
    reason: str = Field(description="中文原因描述")


class ValidationErrorData(BaseModel):
    """``code=10001`` 时的 ``data`` 结构。"""

    errors: list[ValidationErrorItem] = Field(default_factory=list)


class PageData[T](BaseModel):
    """分页响应体（API 设计 §1.4）。

    注意 ``total=0`` 时 ``total_pages`` 为 0，前端据此判断空态。
    """

    items: list[T] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1)
    total_pages: int = Field(default=0, ge=0)


class PageApiResponse[T](ApiResponse[PageData[T]]):
    """分页接口的完整响应类型，供 ``response_model`` 使用。"""
