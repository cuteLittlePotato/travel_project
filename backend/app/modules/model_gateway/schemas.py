"""M12 模型管理的请求/响应模型（API §10.1 ~ §10.4）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ModelCategoryLiteral = Literal["chat", "vision", "embedding", "rerank", "ocr"]

#: 需要填写 ``max_context_tokens`` 的类别（文本类）
TEXT_CATEGORIES: frozenset[str] = frozenset({"chat", "vision"})


class ModelResponse(BaseModel):
    """模型列表项 / 详情（API §10.1 / §10.3）。

    **不包含 ``api_key_encrypted``**——DoD 要求列表与详情都不返回密钥，
    哪怕已加密。前端只需要知道「有没有配密钥」，用
    ``has_api_key`` 一个布尔表达即可。
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str
    model_code: str
    base_url: str
    max_context_tokens: int | None
    max_output_tokens: int | None
    timeout_seconds: int
    concurrency_limit: int | None
    price_input: Decimal | None
    price_output: Decimal | None
    description: str | None
    is_enabled: bool
    is_default: bool
    last_test_at: datetime | None
    last_test_ok: bool | None
    created_at: datetime
    updated_at: datetime

    #: 是否已配置 API Key（不回显任何密钥内容）
    has_api_key: bool = False


class ModelCreate(BaseModel):
    """创建模型（API §10.2）。"""

    name: str = Field(min_length=1, max_length=100)
    category: ModelCategoryLiteral
    model_code: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=500)
    #: 明文传入，服务端加密存储
    api_key: str | None = Field(default=None, max_length=500)
    max_context_tokens: Annotated[int | None, Field(gt=0)] = None
    max_output_tokens: Annotated[int | None, Field(gt=0)] = None
    timeout_seconds: Annotated[int, Field(ge=1, le=300)] = 60
    concurrency_limit: Annotated[int | None, Field(ge=1, le=1000)] = None
    price_input: Annotated[Decimal | None, Field(ge=0)] = None
    price_output: Annotated[Decimal | None, Field(ge=0)] = None
    description: str | None = Field(default=None, max_length=500)
    is_default: bool = False

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("接口地址必须以 http:// 或 https:// 开头")
        return value.rstrip("/")

    @model_validator(mode="after")
    def _check_text_category_context(self) -> ModelCreate:
        """文本类模型必须填 ``max_context_tokens``（API §10.2）。

        embedding / rerank / ocr 没有「上下文长度」的概念，
        强制要求只会让填表的人随便填个数。
        """
        if self.category in TEXT_CATEGORIES and self.max_context_tokens is None:
            raise ValueError("文本类模型必须填写最大上下文长度")
        return self


class ModelUpdate(BaseModel):
    """更新模型（API §10.4）。

    ``category`` **不可修改**——改类别会让该模型已有的调用日志、
    默认模型配置、调用方代码全部失去意义。尝试修改由 service 层
    返回 ``22002``。
    """

    name: str = Field(min_length=1, max_length=100)
    #: 传入且与原值不同时报 22002；不传视为不修改
    category: ModelCategoryLiteral | None = None
    model_code: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=500)
    #: 不传保持原值；传空字符串清空（API §10.4）
    api_key: str | None = Field(default=None, max_length=500)
    max_context_tokens: Annotated[int | None, Field(gt=0)] = None
    max_output_tokens: Annotated[int | None, Field(gt=0)] = None
    timeout_seconds: Annotated[int, Field(ge=1, le=300)] = 60
    concurrency_limit: Annotated[int | None, Field(ge=1, le=1000)] = None
    price_input: Annotated[Decimal | None, Field(ge=0)] = None
    price_output: Annotated[Decimal | None, Field(ge=0)] = None
    description: str | None = Field(default=None, max_length=500)
    is_default: bool = False

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("接口地址必须以 http:// 或 https:// 开头")
        return value.rstrip("/")


class ModelStatusRequest(BaseModel):
    """启用/禁用请求（API §10.5）。"""

    is_enabled: bool


class ModelTestResult(BaseModel):
    """连通性测试结果（API §10.5，M12-T05 实现）。"""

    is_ok: bool
    latency_ms: int | None = None
    message: str | None = None
    tested_at: datetime
