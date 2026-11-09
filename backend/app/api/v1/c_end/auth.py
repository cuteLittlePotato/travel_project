"""C 端认证路由（API §3.1 ~ §3.7）。

路由层只做：参数绑定 + 调用 service + 设置 Cookie + 组织响应。
业务规则全在 ``modules/account/service.py``，不含逻辑判断。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Cookie, Response, status

from app.api.middleware.auth import CurrentUserDep
from app.core.config import settings
from app.core.deps import DBSession
from app.core.response import success
from app.modules.account import service, token_service
from app.modules.account.schemas import (
    AuthTokenResponse,
    CodeLoginRequest,
    CodeLoginResponse,
    LoginRequest,
    OAuthLoginRequest,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    SendCodeRequest,
    SendCodeResponse,
)
from app.modules.account.token_service import RefreshTokenRevokedError
from app.modules.account.verification import send_verify_code

logger = logging.getLogger(__name__)

router = APIRouter()


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """写入 Refresh Token 的 httpOnly Cookie（评审 §Q1）。

    安全属性：
        - ``httpOnly``：JS 不可读，防 XSS 窃取
        - ``Secure``：仅 HTTPS 传输（本地开发通过配置关闭）
        - ``SameSite=Lax``：防 CSRF，同时不阻断站内跳转
        - ``path=/api/v1/auth``：只在认证接口上发送，减少暴露面
    """
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        path=settings.refresh_cookie_path,
    )


@router.post(
    "/verification-codes",
    summary="发送验证码",
    response_model=None,
)
async def send_code(payload: SendCodeRequest) -> dict[str, object]:
    """发送验证码（API §3.1）。

    业务规则由 ``verification.send_verify_code`` 执行：
    60 秒间隔、每日 5 次、5 分钟有效。
    """
    result = await send_verify_code(payload.scene, payload.target)

    body = SendCodeResponse(expires_in=result.expires_in, debug_code=result.debug_code)
    return success(body.model_dump(exclude_none=True))


@router.post(
    "/register",
    summary="用户注册",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def register(
    payload: RegisterRequest,
    session: DBSession,
    response: Response,
) -> dict[str, object]:
    """用户注册（API §3.2）。

    成功返回 201 + 用户 ID + 双 Token，同时把 Refresh Token 写入 httpOnly Cookie。
    """
    result = await service.register(
        session,
        target=payload.target,
        verify_code_str=payload.verify_code,
        password=payload.password,
        nickname=payload.nickname,
    )

    _set_refresh_cookie(response, result.refresh_token)

    body = AuthTokenResponse(
        user_id=result.user_id,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
    )
    return success(body.model_dump(mode="json"))


@router.post("/login", summary="密码登录", response_model=None)
async def login(
    payload: LoginRequest,
    session: DBSession,
    response: Response,
) -> dict[str, object]:
    """密码登录（API §3.3）。

    安全约定（2026-11-08 确认）：「账号不存在」与「密码错误」返回相同的
    message 与 HTTP 401，只有业务码不同（11005 / 11006），避免账号枚举。
    """
    result = await service.authenticate(
        session, target=payload.target, password=payload.password
    )

    _set_refresh_cookie(response, result.refresh_token)

    body = AuthTokenResponse(
        user_id=result.user_id,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
    )
    return success(body.model_dump(mode="json"))


@router.post("/login-by-code", summary="验证码登录（自动注册）", response_model=None)
async def login_by_code(
    payload: CodeLoginRequest,
    session: DBSession,
    response: Response,
) -> dict[str, object]:
    """验证码登录（API §3.4）。

    未注册的 target 自动创建账号并登录，响应 ``is_new_user=true``。
    自动注册的账号无密码，用户可通过「修改密码」接口设置。
    """
    result = await service.login_or_register_by_code(
        session, target=payload.target, verify_code_str=payload.verify_code
    )

    _set_refresh_cookie(response, result.refresh_token)

    body = CodeLoginResponse(
        user_id=result.user_id,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        is_new_user=result.is_new_user,
    )
    return success(body.model_dump(mode="json"))


@router.post("/oauth-login", summary="第三方登录", response_model=None)
async def oauth_login(
    payload: OAuthLoginRequest,
    session: DBSession,
    response: Response,
) -> dict[str, object]:
    """第三方登录（API §3.5）。

    首次登录自动建号并绑定；已绑定账号直接登录。

    ``state`` 由前端校验（2026-11-08 确认），后端只接收回调结果，
    保持无状态。
    """
    result = await service.login_by_oauth(
        session, provider=payload.provider, code=payload.code
    )

    _set_refresh_cookie(response, result.refresh_token)

    body = CodeLoginResponse(
        user_id=result.user_id,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        is_new_user=result.is_new_user,
    )
    return success(body.model_dump(mode="json"))


@router.post("/refresh", summary="刷新 Token", response_model=None)
async def refresh_token(
    session: DBSession,
    response: Response,
    payload: RefreshRequest | None = None,
    request_cookie: str | None = Cookie(default=None, alias=settings.refresh_cookie_name),
) -> dict[str, object]:
    """刷新双 Token（API §3.6）。

    Commit Token 来源（2026-11-08）：
        1. 优先用请求体 ``refresh_token``（非浏览器客户端）
        2. 为空时回退到 httpOnly Cookie（浏览器，评审 §Q1）

    轮换机制：旧 Refresh Token 立即失效（Redis 记 jti 黑名单）。
    """
    token = (payload.refresh_token if payload else None) or request_cookie
    if not token:
        raise RefreshTokenRevokedError("缺少刷新令牌")

    result = await token_service.refresh_tokens(session, refresh_token=token)

    _set_refresh_cookie(response, result.refresh_token)

    body = RefreshResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
    )
    return success(body.model_dump())


@router.post("/logout", summary="登出（全端）", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current: CurrentUserDep,
    session: DBSession,
) -> Response:
    """登出（API §3.7）。

    **全端登出**：``token_version`` 自增，使所有设备上已签发的 Token 立即失效。
    这是评审 §17.4 的决策——不支持单端登出。

    返回 HTTP 204（无响应体）。
    """
    await service.invalidate_all_tokens(session, user_id=current.user_id)

    # 必须在「要返回的那个 Response 对象」上删 Cookie。
    # 若用注入的 response 参数，它会被这里新建的 Response 丢弃。
    result = Response(status_code=status.HTTP_204_NO_CONTENT)
    result.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
    )
    return result
