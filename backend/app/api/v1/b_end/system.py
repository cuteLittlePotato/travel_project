"""B 端系统管理路由（API §14.1 ~ §14.5）。

全部需 B 端 Token（``require_admin``）。权限项校验在 M15-T05 接入。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.middleware.admin_auth import CurrentAdmin
from app.api.middleware.permission import require_permission
from app.core.deps import DBSession
from app.core.response import success
from app.modules.system import role_service, service
from app.modules.system.schemas import (
    AdminCreate,
    AdminPasswordReset,
    AdminUpdate,
    RoleCreate,
    RolePermissionSet,
    RoleUpdate,
    SiteSettingUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ---- 权限依赖别名 ----
# 用模块级 Annotated 别名而不是内联 Annotated[...]，
# 因为本模块有 `from __future__ import annotations`，
# 内联写法会被字符串化，FastAPI 无法在字符串里求值函数调用。
AdminSystemAdminCreate = Annotated[CurrentAdmin, Depends(require_permission("system.admin.create"))]
AdminSystemAdminDelete = Annotated[CurrentAdmin, Depends(require_permission("system.admin.delete"))]
AdminSystemAdminManage = Annotated[CurrentAdmin, Depends(require_permission("system.admin.manage"))]
AdminSystemAdminRead = Annotated[CurrentAdmin, Depends(require_permission("system.admin.read"))]
AdminSystemAdminUpdate = Annotated[CurrentAdmin, Depends(require_permission("system.admin.update"))]
AdminSystemRoleCreate = Annotated[CurrentAdmin, Depends(require_permission("system.role.create"))]
AdminSystemRoleDelete = Annotated[CurrentAdmin, Depends(require_permission("system.role.delete"))]
AdminSystemRoleRead = Annotated[CurrentAdmin, Depends(require_permission("system.role.read"))]
AdminSystemRoleUpdate = Annotated[CurrentAdmin, Depends(require_permission("system.role.update"))]


# ============================================================
# 管理员
# ============================================================


@router.get("/system/admins", summary="管理员列表", response_model=None)
async def list_admins(
    _: AdminSystemAdminRead,
    session: DBSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: Annotated[str | None, Query(max_length=50)] = None,
    admin_status: Annotated[
        str | None, Query(alias="status", pattern="^(active|disabled)$")
    ] = None,
) -> dict[str, object]:
    """管理员列表（API §14.1）。含每个管理员的角色。

    ``admin_status`` 的变量名避开 ``status``——后者与 ``fastapi.status``
    模块名冲突，容易在函数体内误用。
    """
    return success(
        await service.list_admins(
            session,
            keyword=keyword,
            status=admin_status,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/system/admins/{admin_id}", summary="管理员详情", response_model=None)
async def get_admin(
    admin_id: uuid.UUID,
    _: AdminSystemAdminRead,
    session: DBSession,
) -> dict[str, object]:
    return success(await service.get_admin(session, admin_id))


@router.post(
    "/system/admins",
    summary="创建管理员",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def create_admin(
    payload: AdminCreate,
    _: AdminSystemAdminCreate,
    session: DBSession,
) -> dict[str, object]:
    """创建管理员（API §14.2）。用户名重复返回 25002（409）。"""
    return success(await service.create_admin(session, payload=payload))


@router.patch(
    "/system/admins/{admin_id}",
    summary="更新管理员",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_admin(
    admin_id: uuid.UUID,
    payload: AdminUpdate,
    current: AdminSystemAdminUpdate,
    session: DBSession,
) -> Response:
    """更新管理员（API §14.3，PATCH 语义）。"""
    await service.update_admin(
        session,
        admin_id=admin_id,
        payload=payload,
        current_admin_id=current.admin_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/system/admins/{admin_id}/password",
    summary="重置管理员密码",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reset_password(
    admin_id: uuid.UUID,
    payload: AdminPasswordReset,
    _: AdminSystemAdminManage,
    session: DBSession,
) -> Response:
    """重置管理员密码（API §14.4）。

    重置后目标管理员的所有已签发 Token 立即失效。
    """
    await service.reset_password(
        session, admin_id=admin_id, new_password=payload.new_password
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/system/admins/{admin_id}",
    summary="删除管理员",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_admin(
    admin_id: uuid.UUID,
    current: AdminSystemAdminDelete,
    session: DBSession,
) -> Response:
    """删除管理员（API §14.5）。

    - 不能删除自己 → 25004（400）
    - 仅存的超级管理员 → 25003（409）
    """
    await service.delete_admin(
        session, admin_id=admin_id, current_admin_id=current.admin_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================
# 角色
# ============================================================


@router.get("/system/roles", summary="角色列表", response_model=None)
async def list_roles(_: AdminSystemRoleRead, session: DBSession) -> dict[str, object]:
    """角色列表（API §14.6）。含管理员数与权限项数。"""
    return success(await role_service.list_roles(session))


@router.get("/system/roles/{role_id}", summary="角色详情", response_model=None)
async def get_role(
    role_id: uuid.UUID,
    _: AdminSystemRoleRead,
    session: DBSession,
) -> dict[str, object]:
    """角色详情，含权限项明细。"""
    return success(await role_service.get_role(session, role_id))


@router.post(
    "/system/roles",
    summary="创建角色",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def create_role(
    payload: RoleCreate,
    _: AdminSystemRoleCreate,
    session: DBSession,
) -> dict[str, object]:
    """创建角色（API §14.7）。编码重复返回 25014（409）。"""
    return success(await role_service.create_role(session, payload=payload))


@router.patch(
    "/system/roles/{role_id}",
    summary="更新角色",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_role(
    role_id: uuid.UUID,
    payload: RoleUpdate,
    _: AdminSystemRoleUpdate,
    session: DBSession,
) -> Response:
    """更新角色（API §14.8）。``code`` 与 ``is_builtin`` 不可改。"""
    await role_service.update_role(session, role_id=role_id, payload=payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/system/roles/{role_id}/permissions",
    summary="设置角色权限",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def set_role_permissions(
    role_id: uuid.UUID,
    payload: RolePermissionSet,
    _: AdminSystemRoleUpdate,
    session: DBSession,
) -> Response:
    """设置角色权限（整体替换语义）。"""
    await role_service.set_role_permissions(
        session, role_id=role_id, permission_ids=payload.permission_ids
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/system/roles/{role_id}",
    summary="删除角色",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_role(
    role_id: uuid.UUID,
    _: AdminSystemRoleDelete,
    session: DBSession,
) -> Response:
    """删除角色（API §14.9）。

    - 内置角色不可删 → 25006（400）
    - 已分配给管理员 → 25005（409）
    """
    await role_service.delete_role(session, role_id=role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================
# 权限项
# ============================================================


@router.get("/system/permissions", summary="权限项列表", response_model=None)
async def list_permissions(_: AdminSystemRoleRead, session: DBSession) -> dict[str, object]:
    """权限项列表（API §14.10）。

    除扁平 ``items`` 外，还返回按 ``module`` 分组的 ``groups``，
    供前端直接渲染权限勾选树。
    """
    return success(await role_service.list_permissions(session))


# ============================================================
# 操作日志（API §14.11）
# ============================================================


@router.get(
    "/system/operation-logs",
    summary="操作日志列表",
    response_model=None,
)
async def list_operation_logs(
    _: Annotated[CurrentAdmin, Depends(require_permission("system.log.read"))],
    session: DBSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    admin_user_id: Annotated[uuid.UUID | None, Query()] = None,
    module: Annotated[str | None, Query(max_length=50)] = None,
    action: Annotated[
        str | None,
        Query(pattern="^(create|update|delete|export|login|logout)$"),
    ] = None,
    start_date: Annotated[datetime | None, Query()] = None,
    end_date: Annotated[datetime | None, Query()] = None,
) -> dict[str, object]:
    """操作日志列表（API §14.11）。

    只记录增删改与登录登出，**不记录查询**（评审 §Q13）。
    """
    return success(
        await role_service.list_operation_logs(
            session,
            admin_user_id=admin_user_id,
            module=module,
            action=action,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )
    )


# ============================================================
# 站点配置（API §14.12 / §14.13）
# ============================================================


@router.get("/system/settings", summary="站点配置查询", response_model=None)
async def get_settings(
    _: Annotated[CurrentAdmin, Depends(require_permission("system.setting.read"))],
    session: DBSession,
) -> dict[str, object]:
    """站点配置查询（API §14.12）。

    固定返回全部四个配置项——库里缺哪个就用默认值补哪个，
    前端不必处理「字段可能不存在」。
    """
    from app.modules.system import setting_service

    return success(await setting_service.get_settings(session))


@router.put(
    "/system/settings",
    summary="更新站点配置",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_settings(
    payload: SiteSettingUpdate,
    current: Annotated[
        CurrentAdmin, Depends(require_permission("system.setting.update"))
    ],
    session: DBSession,
) -> Response:
    """更新站点配置（API §14.13）。

    全部字段可选，只改传入的项。更新后缓存自动失效。
    """
    from app.modules.system import setting_service

    # exclude_unset：区分「没传」与「显式传 null」
    fields = payload.model_dump(exclude_unset=True)
    await setting_service.update_settings(
        session, payload=fields, updated_by=current.admin_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
