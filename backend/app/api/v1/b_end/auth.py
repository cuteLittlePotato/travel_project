"""B 端管理员认证路由（API §14.14 ~ §14.16）。

``/api/v1/admin/auth/*`` 与 ``/api/v1/admin/me/*`` 不需要额外权限项——
登录本身当然不能要求已登录，登出与改密是任何已登录管理员的基本能力。

Token 策略与 C 端一致（评审 §Q1）：
    - Access Token 返回给前端，存内存
    - Refresh Token 写 httpOnly Cookie，JS 不可读
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from app.api.middleware.admin_auth import CurrentAdmin, require_admin
from app.core.config import settings
from app.core.deps import DBSession
from app.core.response import success
from app.modules.system import auth_service
from app.modules.system.schemas import (
    AdminLoginRequest,
    AdminRefreshRequest,
    ChangeOwnPasswordRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()

#: B 端 Refresh Token 的 Cookie 名。与 C 端区分开，
#: 否则同一浏览器同时登录 C 端与 B 端时两个 Cookie 会互相覆盖。
ADMIN_REFRESH_COOKIE_NAME = "travel_admin_refresh_token"

#: 只在 B 端路径上发送，减少暴露面
ADMIN_REFRESH_COOKIE_PATH = "/api/v1/admin"


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """写入 Refresh Token 的 httpOnly Cookie（评审 §Q1）。

    安全属性与 C 端一致：
        - ``httpOnly``：JS 不可读，防 XSS 窃取
        - ``Secure``：仅 HTTPS 传输（本地开发通过配置关闭）
        - ``SameSite=Lax``：防 CSRF，同时不阻断站内跳转
        - ``path=/api/v1/admin``：只在 B 端接口上发送
    """
    response.set_cookie(
        key=ADMIN_REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        path=ADMIN_REFRESH_COOKIE_PATH,
    )


@router.post("/auth/login", summary="管理员登录", response_model=None)
async def login(
    payload: AdminLoginRequest,
    request: Request,
    session: DBSession,
) -> Response:
    """管理员登录（API §14.14）。

    - 用户名或密码错误 → 11006（401），**不区分是哪一项错**
    - 账号已禁用 → 11002（403）
    - 成功返回 ``user_type='admin'`` 的 Access Token，Refresh 写 Cookie
    """
    admin = await auth_service.authenticate_admin(
        session, username=payload.username, password=payload.password
    )
    result = await auth_service.issue_admin_tokens(
        session, admin_id=admin["id"]  # type: ignore[arg-type]
    )
    # API §14.14：响应结构与 C 端登录一致，但标注 user_type
    result["user_type"] = "admin"

    # 用 JSONResponse 承载统一响应结构，同时能设置 Cookie
    from fastapi.responses import JSONResponse

    response = JSONResponse(content=success(result))
    set_refresh_cookie(response, str(result["refresh_token"]))
    logger.info("管理员登录成功 username=%s", payload.username)
    return response


@router.post("/auth/refresh", summary="刷新 Token", response_model=None)
async def refresh(
    session: DBSession,
    payload: AdminRefreshRequest | None = None,
    request_cookie: str | None = Cookie(default=None, alias=ADMIN_REFRESH_COOKIE_NAME),
) -> Response:
    """刷新双 Token。

    Commit Token 来源：
        1. 优先用请求体 ``refresh_token``（非浏览器客户端）
        2. 为空时回退到 httpOnly Cookie（浏览器，评审 §Q1）

    轮换机制：旧 Refresh Token 立即失效（Redis jti 黑名单）。
    """
    token = (payload.refresh_token if payload else None) or request_cookie
    if not token:
        raise auth_service.AdminRefreshRevokedError("缺少刷新令牌")

    result = await auth_service.refresh_admin_tokens(
        session, refresh_token=token
    )

    from fastapi.responses import JSONResponse

    response = JSONResponse(content=success(result))
    set_refresh_cookie(response, str(result["refresh_token"]))
    return response


@router.post(
    "/auth/logout",
    summary="管理员登出",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def logout(
    current: Annotated[CurrentAdmin, Depends(require_admin)],
    session: DBSession,
) -> Response:
    """管理员登出（API §14.15）。全端登出，``token_version`` 自增。

    不要求权限项——登出是任何已登录管理员的基本能力，
    要求额外权限会导致「没有权限的人还登不出去」。
    """
    await auth_service.logout_admin(session, admin_id=current.admin_id)

    # 在**返回的对象**上删 Cookie——对注入的 response 参数操作不生效
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    out.delete_cookie(
        key=ADMIN_REFRESH_COOKIE_NAME,
        path=ADMIN_REFRESH_COOKIE_PATH,
    )
    return out


@router.put(
    "/me/password",
    summary="修改自己的密码",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def change_own_password(
    payload: ChangeOwnPasswordRequest,
    current: Annotated[CurrentAdmin, Depends(require_admin)],
    session: DBSession,
) -> Response:
    """修改自己的密码（API §14.16）。

    - 原密码错误 → 25007（400）
    - 新密码与原密码相同 → 25008（400）
    - 成功后 ``token_version`` 自增，**所有设备需重新登录**
    """
    await auth_service.change_own_password(
        session,
        admin_id=current.admin_id,
        old_password=payload.old_password,
        new_password=payload.new_password,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
