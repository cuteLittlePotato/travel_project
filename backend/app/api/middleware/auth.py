"""C 端认证依赖。

双端隔离（API §16.3）：C 端 Token 的 ``user_type`` 必须为 ``user``，
B 端 Token 访问 C 端接口一律 403。

``token_version`` 每次请求都会与数据库比对（2026-11-07 确认）：
登出、改密、封禁后 ``user.token_version`` 自增，旧 Token 立即失效。

性能说明：该查询走 ``user.id`` 主键索引，单次约 0.1ms，且复用本请求已有的
数据库会话（``get_db`` 依赖），不额外建连。选此方案而非 Redis 缓存的原因是
缓存会让封禁/登出延迟生效，与 M01-T09「登出后原 Token 均返回 401」的 DoD 冲突。
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

bearer_scheme = HTTPBearer(auto_error=False)

#: 解析账号当前 token_version。返回 None 表示账号不存在或已注销。
TokenVersionResolver = Callable[[AsyncSession, uuid.UUID], Awaitable[int | None]]


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user_id: uuid.UUID
    token_version: int


async def resolve_user_token_version(
    session: AsyncSession, user_id: uuid.UUID
) -> int | None:
    """查询 ``user`` 表的 token_version。

    已注销（``status='deleted'``）的账号返回 None，其 Token 一并失效。
    表由 M01-T01 创建；本模块在其之前完成，测试通过依赖覆盖注入替身。
    """
    result = await session.execute(
        text('SELECT token_version FROM "user" WHERE id = :user_id AND status != :deleted'),
        {"user_id": user_id, "deleted": "deleted"},
    )
    return result.scalar_one_or_none()


def get_token_version_resolver() -> TokenVersionResolver:
    """依赖提供者。测试可用 ``app.dependency_overrides`` 替换。"""
    return resolve_user_token_version


async def require_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: DBSession,
    resolve_version: Annotated[
        TokenVersionResolver, Depends(get_token_version_resolver)
    ],
) -> CurrentUser:
    """校验 C 端 Access Token，返回当前用户。"""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError()

    payload = decode_token(credentials.credentials, expected_type="access")

    if payload.user_type != "user":
        raise ForbiddenError("该 Token 不可访问 C 端接口")

    current_version = await resolve_version(session, payload.subject_id)
    verify_token_version(payload, current_version)

    return CurrentUser(user_id=payload.subject_id, token_version=payload.token_version)


CurrentUserDep = Annotated[CurrentUser, Depends(require_user)]
