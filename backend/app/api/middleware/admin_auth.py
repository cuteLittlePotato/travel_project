"""B 端认证依赖。

与 C 端对称：B 端 Token 的 ``user_type`` 必须为 ``admin``，
C 端 Token 访问 B 端接口一律 403。

B 端还需要权限项校验（API §16.3），由后续 M15 的角色权限体系补充。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import DBSession
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token, verify_token_version

admin_bearer = HTTPBearer(auto_error=False)

#: 解析管理员当前 token_version
AdminTokenVersionResolver = Callable[[AsyncSession, uuid.UUID], Awaitable[int | None]]


@dataclass(frozen=True, slots=True)
class CurrentAdmin:
    admin_id: uuid.UUID
    token_version: int


async def resolve_admin_token_version(
    session: AsyncSession, admin_id: uuid.UUID
) -> int | None:
    """查询 ``admin_user`` 表的 token_version。禁用（``status='disabled'``）视为不存在。"""
    result = await session.execute(
        text(
            'SELECT token_version FROM admin_user '
            "WHERE id = :admin_id AND status = 'active'"
        ),
        {"admin_id": admin_id},
    )
    return result.scalar_one_or_none()


def get_admin_token_version_resolver() -> AdminTokenVersionResolver:
    return resolve_admin_token_version


async def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(admin_bearer)],
    session: DBSession,
    resolve_version: Annotated[
        AdminTokenVersionResolver, Depends(get_admin_token_version_resolver)
    ],
) -> CurrentAdmin:
    """校验 B 端 Access Token，返回当前管理员。"""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError()

    payload = decode_token(credentials.credentials, expected_type="access")

    if payload.user_type != "admin":
        raise ForbiddenError("该 Token 不可访问 B 端接口")

    current_version = await resolve_version(session, payload.subject_id)
    verify_token_version(payload, current_version)

    return CurrentAdmin(admin_id=payload.subject_id, token_version=payload.token_version)


CurrentAdminDep = Annotated[CurrentAdmin, Depends(require_admin)]
