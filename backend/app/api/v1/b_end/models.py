"""B 端模型管理路由（API §10.1 ~ §10.4）。

全部需 B 端 Token（``require_admin``）。
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.middleware.admin_auth import CurrentAdmin
from app.api.middleware.permission import require_permission
from app.core.deps import DBSession
from app.core.response import success
from app.modules.model_gateway import service
from app.modules.model_gateway.constants import MODEL_CATEGORY_LABELS
from app.modules.model_gateway.schemas import (
    ModelCreate,
    ModelStatusRequest,
    ModelUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ---- 权限依赖别名 ----
# 用模块级 Annotated 别名而不是内联 Annotated[...]，
# 因为本模块有 `from __future__ import annotations`，
# 内联写法会被字符串化，FastAPI 无法在字符串里求值函数调用。
AdminModelModelCreate = Annotated[CurrentAdmin, Depends(require_permission("model.model.create"))]
AdminModelModelDelete = Annotated[CurrentAdmin, Depends(require_permission("model.model.delete"))]
AdminModelModelManage = Annotated[CurrentAdmin, Depends(require_permission("model.model.manage"))]
AdminModelModelRead = Annotated[CurrentAdmin, Depends(require_permission("model.model.read"))]
AdminModelModelUpdate = Annotated[CurrentAdmin, Depends(require_permission("model.model.update"))]


@router.get("/models", summary="模型列表", response_model=None)
async def list_models(
    _: AdminModelModelRead,
    session: DBSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    category: Annotated[
        str | None, Query(pattern="^(chat|vision|embedding|rerank|ocr)$")
    ] = None,
    is_enabled: Annotated[bool | None, Query()] = None,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
) -> dict[str, object]:
    """模型列表（API §10.1）。**不返回 api_key**。"""
    return success(
        await service.list_models(
            session,
            category=category,
            is_enabled=is_enabled,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/models/categories", summary="模型类别列表", response_model=None)
async def list_categories(
    _: AdminModelModelRead,
) -> dict[str, object]:
    """模型类别列表（API §10.11）。

    类别是**固定枚举**，不可由 API 新增（评审 §Q6）——
    每新增一类都要改调用方代码，属于产品能力扩展而非运营配置。

    路径必须注册在 ``/models/{model_id}`` **之前**，否则
    ``categories`` 会被当成 ``model_id`` 去解析 UUID 而报 400。
    """
    return success(
        {
            "items": [
                {"code": code, "name": name}
                for code, name in MODEL_CATEGORY_LABELS.items()
            ]
        }
    )


@router.get("/models/{model_id}", summary="模型详情", response_model=None)
async def get_model(
    model_id: uuid.UUID,
    _: AdminModelModelRead,
    session: DBSession,
) -> dict[str, object]:
    """模型详情（API §10.3）。**不返回 api_key**。"""
    return success(await service.get_model(session, model_id))


@router.post(
    "/models",
    summary="创建模型",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def create_model(
    payload: ModelCreate,
    _: AdminModelModelCreate,
    session: DBSession,
) -> dict[str, object]:
    """创建模型（API §10.2）。

    - ``api_key`` 明文传入，服务端加密后存储
    - 同类别重复返回 22001（409）
    - ``is_default=true`` 自动取消同类别原默认
    """
    return success(await service.create_model(session, payload=payload))


@router.put(
    "/models/{model_id}",
    summary="更新模型",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_model(
    model_id: uuid.UUID,
    payload: ModelUpdate,
    _: AdminModelModelUpdate,
    session: DBSession,
) -> Response:
    """更新模型（API §10.4）。

    - ``category`` 修改返回 22002（400）
    - ``api_key`` 不传保持原值，传空串清空
    """
    await service.update_model(session, model_id=model_id, payload=payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/models/{model_id}",
    summary="删除模型",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_model(
    model_id: uuid.UUID,
    _: AdminModelModelDelete,
    session: DBSession,
) -> Response:
    """删除模型（API §10.7）。

    - 是类别默认 → 22003（409）
    - 被知识库引用 → 22006（409）
    - ``model_call_log`` 记录保留，不级联
    """
    await service.delete_model(session, model_id=model_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/models/{model_id}/status",
    summary="启用/禁用模型",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_status(
    model_id: uuid.UUID,
    payload: ModelStatusRequest,
    _: AdminModelModelManage,
    session: DBSession,
) -> Response:
    """启用/禁用模型（API §10.5）。

    - 禁用默认模型 → 22003（409）
    - 禁用被知识库引用的模型 → 22004（409）
    """
    await service.update_status(
        session, model_id=model_id, is_enabled=payload.is_enabled
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/models/{model_id}/default",
    summary="设为默认模型",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def set_default(
    model_id: uuid.UUID,
    _: AdminModelModelManage,
    session: DBSession,
) -> Response:
    """设为该类别的默认模型（API §10.6）。

    - 模型未启用 → 22005（400）
    - 自动取消同类别原默认
    """
    await service.set_default(session, model_id=model_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
