"""C 端通知路由（API §3.15 ~ §3.18）。

四个端点：
    GET    /notifications                    列表（分页 + 筛选）
    GET    /notifications/unread-count       未读数
    PATCH  /notifications/{id}/read          单条已读
    POST   /notifications/read-all           全部已读

全部需登录，且只能访问自己的通知。
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.middleware.auth import CurrentUserDep
from app.core.deps import DBSession
from app.core.response import success
from app.modules.account import service
from app.modules.account.constants import NotificationType
from app.schemas.pagination import PageQuery, page_params

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", summary="通知列表", response_model=None)
async def list_notifications(
    current: CurrentUserDep,
    session: DBSession,
    paging: Annotated[PageQuery, Depends(page_params)],
    is_read: Annotated[bool | None, Query(description="筛选已读/未读")] = None,
    notification_type: Annotated[
        NotificationType | None, Query(description="通知类型筛选")
    ] = None,
) -> dict[str, object]:
    """通知列表（API §3.15）。

    按 ``created_at`` 倒序。响应额外含 ``unread_count``，
    **它是整个账号的未读数，不受筛选条件影响**。
    """
    data = await service.list_notifications(
        session,
        user_id=current.user_id,
        page=paging.page,
        page_size=paging.page_size,
        is_read=is_read,
        notification_type=notification_type.value if notification_type else None,
    )
    return success(data)


@router.get("/unread-count", summary="通知未读数", response_model=None)
async def get_unread_count(current: CurrentUserDep, session: DBSession) -> dict[str, object]:
    """未读数（API §3.16）。供前端轮询或角标显示。"""
    count = await service.get_unread_count(session, user_id=current.user_id)
    return success({"count": count})


@router.patch(
    "/{notification_id}/read",
    summary="标记通知已读",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def mark_read(
    notification_id: uuid.UUID,
    current: CurrentUserDep,
    session: DBSession,
) -> Response:
    """标记单条已读（API §3.17）。

    **幂等**：已读的通知再次标记仍返回 204，不更新 ``read_at``。
    他人的通知返回 404（不区分「不存在」与「不属于你」，避免探测）。
    """
    await service.mark_notification_read(
        session, user_id=current.user_id, notification_id=notification_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/read-all", summary="全部标记已读", response_model=None)
async def mark_all_read(current: CurrentUserDep, session: DBSession) -> dict[str, object]:
    """全部标记已读（API §3.18）。返回本次更新条数。"""
    updated = await service.mark_all_notifications_read(
        session, user_id=current.user_id
    )
    return success({"updated_count": updated})
