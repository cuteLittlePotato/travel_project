"""C 端用户资料路由（API §3.8 ~ §3.14）。

所有端点需登录，从 ``CurrentUserDep`` 取 user_id。
路由层只做参数绑定与响应组织。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status

from app.api.middleware.auth import CurrentUserDep
from app.core.config import settings
from app.core.deps import DBSession
from app.core.response import success
from app.modules.account import service
from app.modules.account.schemas import (
    ChangePasswordRequest,
    DeactivateAccountRequest,
    UpdateProfileRequest,
    UpdateTravelProfileRequest,
    UpdateUserSettingRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/me", summary="获取当前用户资料", response_model=None)
async def get_me(current: CurrentUserDep, session: DBSession) -> dict[str, object]:
    """获取当前用户资料（API §3.8）。

    返回 ``bindings`` 时 ``provider_uid`` 已脱敏（手机号中间四位、邮箱部分打码）。
    **不返回** ``credential``（密码哈希）与 ``token_version``（内部状态）。
    """
    data = await service.get_me(session, user_id=current.user_id)
    return success(data)


@router.patch("/me", summary="更新当前用户资料", response_model=None)
async def update_me(
    payload: UpdateProfileRequest,
    current: CurrentUserDep,
    session: DBSession,
) -> dict[str, object]:
    """更新当前用户资料（API §3.9）。

    部分更新语义：只更新请求体中出现的字段。
    用 ``model_fields_set`` 区分「未传」与「传了 null」——
    后者表示要清空该字段（如清空头像）。
    """
    data = await service.update_me(
        session,
        user_id=current.user_id,
        nickname=payload.nickname,
        avatar_url=payload.avatar_url,
        gender=payload.gender.value if payload.gender else None,
        region_code=payload.region_code,
        fields_set=payload.model_fields_set,
    )
    return success(data)


@router.put(
    "/me/password",
    summary="修改密码",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def change_password(
    payload: ChangePasswordRequest,
    current: CurrentUserDep,
    session: DBSession,
) -> Response:
    """修改密码（API §3.10）。

    成功后 ``token_version`` 自增，所有已签发的 Token 失效，需重新登录。

    **无密码账号的例外**：自动注册/第三方登录创建的账号首次设置密码时，
    ``old_password`` 可不传（2026-11-08 确认）。
    """
    await service.change_password(
        session,
        user_id=current.user_id,
        old_password=payload.old_password,
        new_password=payload.new_password,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/profile", summary="获取旅游偏好", response_model=None)
async def get_travel_profile(
    current: CurrentUserDep, session: DBSession
) -> dict[str, object]:
    """查询旅游偏好（API §3.11）。"""
    data = await service.get_profile(session, user_id=current.user_id)
    return success(data)


@router.put(
    "/me/profile",
    summary="更新旅游偏好",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_travel_profile(
    payload: UpdateTravelProfileRequest,
    current: CurrentUserDep,
    session: DBSession,
) -> Response:
    """更新旅游偏好（API §3.12）。

    **整体替换语义**：未传的字段会被重置为 null。
    前端应以表单整体提交的方式使用。
    """
    await service.update_profile(
        session,
        user_id=current.user_id,
        travel_types=payload.travel_types,
        travel_styles=payload.travel_styles,
        budget_level=payload.budget_level.value if payload.budget_level else None,
        companion_type=payload.companion_type.value if payload.companion_type else None,
        preferred_seasons=payload.preferred_seasons,
        departure_city=payload.departure_city,
        fields_set=payload.model_fields_set,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/settings", summary="获取隐私设置", response_model=None)
async def get_user_settings(
    current: CurrentUserDep, session: DBSession
) -> dict[str, object]:
    """查询隐私与通知设置（API §3.13）。"""
    data = await service.get_settings(session, user_id=current.user_id)
    return success(data)


@router.patch(
    "/me/settings",
    summary="更新隐私设置",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_user_settings(
    payload: UpdateUserSettingRequest,
    current: CurrentUserDep,
    session: DBSession,
) -> Response:
    """更新隐私设置（API §3.14）。

    **部分更新语义**：只更新请求体中出现的字段。

    布尔字段用 ``model_fields_set`` 区分「未传」与「传 false」——
    传 ``allow_recommendation: false`` 必须生效，不能被当成未传。
    """
    await service.update_settings(
        session,
        user_id=current.user_id,
        profile_visibility=(
            payload.profile_visibility.value if payload.profile_visibility else None
        ),
        footprint_visibility=(
            payload.footprint_visibility.value if payload.footprint_visibility else None
        ),
        plan_visibility=(
            payload.plan_visibility.value if payload.plan_visibility else None
        ),
        allow_recommendation=payload.allow_recommendation,
        allow_notification=payload.allow_notification,
        fields_set=payload.model_fields_set,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


#: 用 POST 而非 DELETE：注销需要在请求体里带密码与确认文字，
#: 而 DELETE 携带请求体在部分 HTTP 客户端与代理上支持不佳。
#: 语义上这是「发起注销动作」而非「删除某个子资源」，POST 更贴切。
@router.post(
    "/me/deactivate",
    summary="注销账号",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def deactivate_account(
    payload: DeactivateAccountRequest,
    current: CurrentUserDep,
    session: DBSession,
) -> Response:
    """注销账号（API §3.19）。

    **不可逆**：账号进入 ``deleted`` 状态，会话、记忆、额度记录被清理，
    足迹匿名化保留。

    要求提供密码验证身份，并手动输入「注销」二字二次确认。
    注销后所有设备立即掉线。
    """
    await service.deactivate_account(
        session, user_id=current.user_id, password=payload.password
    )

    # 在要返回的对象上删 Cookie——注入的 response 参数会被新对象丢弃
    result = Response(status_code=status.HTTP_204_NO_CONTENT)
    result.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
    )
    return result
