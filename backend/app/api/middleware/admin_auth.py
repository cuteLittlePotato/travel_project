"""B 端认证依赖。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import PermissionDeniedError, UnauthorizedError
from app.core.security import decode_token

admin_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class CurrentAdmin:
    admin_id: uuid.UUID
    token_version: int


async def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(admin_bearer)] = None,
) -> CurrentAdmin:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError()

    payload = decode_token(credentials.credentials, expected_type="access")

    if payload.get("user_type") != "admin":
        raise PermissionDeniedError("该 Token 不可访问 B 端接口")

    try:
        admin_id = uuid.UUID(str(payload["sub"]))
    except (ValueError, KeyError) as exc:
        raise UnauthorizedError("Token 载荷不合法") from exc

    return CurrentAdmin(admin_id=admin_id, token_version=int(payload["token_version"]))


CurrentAdminDep = Annotated[CurrentAdmin, Depends(require_admin)]
