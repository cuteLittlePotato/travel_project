"""M12 模型管理的业务逻辑（API §10.1 ~ §10.4）。

职责边界：
    - 业务校验（重复、类别不可改、默认模型切换）在此
    - ``api_key`` 的加解密在此，Repository 只存密文
    - 事务提交在此（Repository 只 flush）
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError
from app.modules.model_gateway.constants import (
    ERROR_MODEL_CATEGORY_IMMUTABLE,
    ERROR_MODEL_DUPLICATE,
    ERROR_MODEL_IS_DEFAULT,
    ERROR_MODEL_NOT_ENABLED,
    ERROR_MODEL_NOT_FOUND,
    ERROR_MODEL_REFERENCED_DELETE,
    ERROR_MODEL_REFERENCED_DISABLE,
)
from app.modules.model_gateway.crypto import encrypt_api_key
from app.modules.model_gateway.models import Model
from app.modules.model_gateway.repository import ModelRepository
from app.modules.model_gateway.schemas import ModelCreate, ModelResponse, ModelUpdate
from app.utils.ids import uuid7

logger = logging.getLogger(__name__)


class ModelNotFoundError(BusinessError):
    def __init__(self) -> None:
        super().__init__(ERROR_MODEL_NOT_FOUND, "模型不存在", http_status=404)


class ModelDuplicateError(BusinessError):
    def __init__(self) -> None:
        super().__init__(
            ERROR_MODEL_DUPLICATE,
            "同类别下已存在相同的模型（model_code + base_url）",
            http_status=409,
        )


class ModelCategoryImmutableError(BusinessError):
    """``category`` 不可修改（API §10.4，22002 / HTTP 400）。"""

    def __init__(self) -> None:
        super().__init__(ERROR_MODEL_CATEGORY_IMMUTABLE, "模型类别不可修改", http_status=400)


class ModelIsDefaultError(BusinessError):
    """默认模型不能禁用/删除（API §10.5 / §10.7，22003 / HTTP 409）。"""

    def __init__(self) -> None:
        super().__init__(
            ERROR_MODEL_IS_DEFAULT,
            "该模型是当前类别的默认模型，请先更换默认",
            http_status=409,
        )


class ModelReferencedDisableError(BusinessError):
    """被知识库引用，不能禁用（API §10.5，22004 / HTTP 409）。

    禁用后知识库的检索/向量化会立刻失效，且引用关系还挂着，
    因此必须在禁用前先解除引用。
    """

    def __init__(self) -> None:
        super().__init__(
            ERROR_MODEL_REFERENCED_DISABLE,
            "该模型正被知识库引用，请先解除引用后再禁用",
            http_status=409,
        )


class ModelNotEnabledError(BusinessError):
    """模型未启用，不能设为默认（API §10.6，22005）。"""

    def __init__(self) -> None:
        super().__init__(
            ERROR_MODEL_NOT_ENABLED,
            "模型未启用，不能设为默认",
            http_status=400,
        )


class ModelReferencedDeleteError(BusinessError):
    """被知识库引用，不能删除（API §10.7，22006 / HTTP 409）。"""

    def __init__(self) -> None:
        super().__init__(
            ERROR_MODEL_REFERENCED_DELETE,
            "该模型正被知识库引用，无法删除",
            http_status=409,
        )


# ============================================================
# 序列化
# ============================================================


def serialize_model(model: Model) -> dict[str, Any]:
    """转成响应字典。

    用 ``ModelResponse`` 校验字段集——这样「不返回 api_key_encrypted」
    这件事由 schema 定义保证，而不是靠每个调用点记得删字段。
    """
    payload = ModelResponse.model_validate(model)
    payload.has_api_key = bool(model.api_key_encrypted)
    return payload.model_dump(mode="json")


# ============================================================
# 查询
# ============================================================


async def get_model(session: AsyncSession, model_id: uuid.UUID) -> dict[str, Any]:
    repo = ModelRepository(session)
    model = await repo.get_by_id(model_id)
    if model is None:
        raise ModelNotFoundError()
    return serialize_model(model)


async def list_models(
    session: AsyncSession,
    *,
    category: str | None = None,
    is_enabled: bool | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    repo = ModelRepository(session)
    items, total = await repo.list(
        category=category,
        is_enabled=is_enabled,
        keyword=keyword,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return {
        "items": [serialize_model(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


# ============================================================
# 写入
# ============================================================


async def create_model(session: AsyncSession, *, payload: ModelCreate) -> dict[str, Any]:
    """创建模型（API §10.2）。

    ``is_default=True`` 时先取消同类别原默认——顺��必须是「先清后设」，
    否则会撞部分唯一索引。
    """
    repo = ModelRepository(session)

    if await repo.exists_same(
        category=payload.category,
        model_code=payload.model_code,
        base_url=payload.base_url,
    ):
        raise ModelDuplicateError()

    if payload.is_default:
        await repo.clear_default(payload.category)

    model = Model(
        id=uuid7(),
        name=payload.name,
        category=payload.category,
        model_code=payload.model_code,
        base_url=payload.base_url,
        api_key_encrypted=encrypt_api_key(payload.api_key or ""),
        max_context_tokens=payload.max_context_tokens,
        max_output_tokens=payload.max_output_tokens,
        timeout_seconds=payload.timeout_seconds,
        concurrency_limit=payload.concurrency_limit,
        price_input=payload.price_input,
        price_output=payload.price_output,
        description=payload.description,
        is_default=payload.is_default,
    )
    repo.add(model)
    await repo.flush()
    await session.commit()
    await session.refresh(model)

    logger.info("创建模型 id=%s category=%s", model.id, model.category)
    return serialize_model(model)


async def update_model(
    session: AsyncSession, *, model_id: uuid.UUID, payload: ModelUpdate
) -> None:
    """更新模型（API §10.4）。

    ``api_key`` 的三态语义：
        - 不传（``None``）→ 保持原值
        - 传空字符串 → 清空
        - 传非空 → 加密后替换
    """
    repo = ModelRepository(session)
    model = await repo.get_by_id(model_id)
    if model is None:
        raise ModelNotFoundError()

    # 类别不可改
    if payload.category is not None and payload.category != model.category:
        raise ModelCategoryImmutableError()

    if await repo.exists_same(
        category=model.category,
        model_code=payload.model_code,
        base_url=payload.base_url,
        exclude_id=model_id,
    ):
        raise ModelDuplicateError()

    if payload.is_default and not model.is_default:
        await repo.clear_default(model.category, exclude_id=model_id)

    model.name = payload.name
    model.model_code = payload.model_code
    model.base_url = payload.base_url
    model.max_context_tokens = payload.max_context_tokens
    model.max_output_tokens = payload.max_output_tokens
    model.timeout_seconds = payload.timeout_seconds
    model.concurrency_limit = payload.concurrency_limit
    model.price_input = payload.price_input
    model.price_output = payload.price_output
    model.description = payload.description
    model.is_default = payload.is_default

    # api_key：None 保持，空串清空，非空替换
    if payload.api_key is not None:
        model.api_key_encrypted = encrypt_api_key(payload.api_key)

    await repo.flush()
    await session.commit()
    logger.info("更新模型 id=%s", model_id)


async def delete_model(session: AsyncSession, *, model_id: uuid.UUID) -> None:
    """删除模型（API §10.7）。

    两条保护（顺序有讲究）：
        1. 是该类别默认 → 22003。先查这个：默认标记是模型自身的
           状态，比「被谁引用」更直接，用户也更容易先理解。
        2. 被知识库引用（embedding / rerank）→ 22006。

    ``model_call_log`` 不做级联删除——日志是审计数据，
    模型被删后历史调用记录仍需可查（数据库设计 §4.2「保留不删」）。
    """
    repo = ModelRepository(session)
    model = await repo.get_by_id(model_id)
    if model is None:
        raise ModelNotFoundError()

    if model.is_default:
        raise ModelIsDefaultError()

    if await repo.count_knowledge_base_refs(model_id) > 0:
        raise ModelReferencedDeleteError()

    await repo.delete(model)
    await session.commit()
    logger.info("删除模型 id=%s category=%s", model_id, model.category)


# ============================================================
# 启用 / 禁用 / 默认（API §10.5 / §10.6）
# ============================================================


async def update_status(
    session: AsyncSession, *, model_id: uuid.UUID, is_enabled: bool
) -> None:
    """启用或禁用模型（API §10.5）。

    禁用时两条保护：
        - 是类别默认 → 22003。默认模型被禁用后，该类别就没有可用的
          默认目标了，必须先换默认。
        - 被知识库引用 → 22004。禁用会让知识库的向量化/检索立刻失效。

    **启用不设限制**——启用只会让模型可用，不会破坏任何既有关系。
    """
    repo = ModelRepository(session)
    model = await repo.get_by_id(model_id)
    if model is None:
        raise ModelNotFoundError()

    if not is_enabled:
        if model.is_default:
            raise ModelIsDefaultError()
        if await repo.count_knowledge_base_refs(model_id) > 0:
            raise ModelReferencedDisableError()

    model.is_enabled = is_enabled
    await repo.flush()
    await session.commit()
    logger.info("模型 %s 状态改为 is_enabled=%s", model_id, is_enabled)


async def set_default(session: AsyncSession, *, model_id: uuid.UUID) -> None:
    """设为该类别的默认模型（API §10.6）。

    顺序必须是「先清后设」：``idx_model_default`` 是 ``WHERE is_default
    = TRUE`` 的部分唯一索引，先设再清会在 UPDATE 瞬间撞约束。

    并发设置默认时，部分唯一索引是最后一道防线——两个请求都清完
    再都设，第二个会因唯一索引冲突被拒。这是正确行为：
    同一类别不可能同时有两个默认。
    """
    repo = ModelRepository(session)
    model = await repo.get_by_id(model_id)
    if model is None:
        raise ModelNotFoundError()

    if not model.is_enabled:
        raise ModelNotEnabledError()

    if model.is_default:
        # 已经是默认，幂等返回
        return

    await repo.clear_default(model.category, exclude_id=model_id)
    model.is_default = True
    await repo.flush()
    await session.commit()
    logger.info("模型 %s 设为类别 %s 的默认", model_id, model.category)
