"""C 端认证依赖。

双端隔离：C 端 Token 的 ``user_type`` 必须为 ``user``，
B 端 Token 访问 C 端接口一律 403。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import PermissionDeniedError, UnauthorizedError
from app.core.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user_id: uuid.UUID
    token_version: int


async def require_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> CurrentUser:
    """校验 C 端 Access Token，返回当前用户。

    ``token_version`` 与数据库的一致性校验由具体业务依赖补充查询完成，
    此层只做 Token 自校验，避免给每个请求都增加一次 DB 查询。
    """
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError()

    payload = decode_token(credentials.credentials, expected_type="access")

    if payload.get("user_type") != "user":
        raise PermissionDeniedError("该 Token 不可访问 C 端接口")

    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (ValueError, KeyError) as exc:
        raise UnauthorizedError("Token 载荷不合法") from exc

    return CurrentUser(user_id=user_id, token_version=int(payload["token_version"]))


CurrentUserDep = Annotated[CurrentUser, Depends(require_user)]
