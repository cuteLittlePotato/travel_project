"""M15 角色与权限的业务逻辑（API §14.6 ~ §14.10）。

从 ``service.py`` 拆出，避免单文件过长。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError
from app.modules.system.constants import (
    ERROR_ROLE_BUILTIN,
    ERROR_ROLE_CODE_DUPLICATE,
    ERROR_ROLE_IN_USE,
    ERROR_ROLE_NOT_FOUND,
)
from app.modules.system.models import Role
from app.modules.system.repository import (
    AdminRoleRepository,
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
)
from app.modules.system.schemas import (
    PermissionBrief,
    RoleCreate,
    RoleDetail,
    RoleResponse,
    RoleUpdate,
)
from app.utils.ids import uuid7

logger = logging.getLogger(__name__)


# ============================================================
# 异常
# ============================================================


class RoleNotFoundError(BusinessError):
    def __init__(self) -> None:
        super().__init__(ERROR_ROLE_NOT_FOUND, "角色不存在", http_status=404)


class RoleCodeDuplicateError(BusinessError):
    def __init__(self) -> None:
        super().__init__(ERROR_ROLE_CODE_DUPLICATE, "该角色编码已存在", http_status=409)


class RoleInUseError(BusinessError):
    """角色已分配给管理员，不能删除（API §14.8，25005 / HTTP 409）。

    删掉角色会让持有它的管理员瞬间失去这些权限，而管理员本身
    看不出任何变化——这种「静默降权」比直接报错更难排查。
    """

    def __init__(self) -> None:
        super().__init__(
            ERROR_ROLE_IN_USE, "该角色已分配给管理员，请先解除分配", http_status=409
        )


class RoleBuiltinError(BusinessError):
    """内置角色不可删除（API §14.8，25006 / HTTP 400）。

    内置角色被代码直接引用（``ROLE_SUPER_ADMIN``），删除会让
    「谁有全部权限」这个判断失去依据。
    """

    def __init__(self) -> None:
        super().__init__(ERROR_ROLE_BUILTIN, "内置角色不可删除", http_status=400)


class PermissionNotFoundError(BusinessError):
    def __init__(self) -> None:
        super().__init__(25015, "权限项不存在", http_status=404)


# ============================================================
# 序列化
# ============================================================


def serialize_role(
    role: Role,
    *,
    admin_count: int = 0,
    permission_count: int = 0,
    permissions: list[Any] | None = None,
) -> dict[str, Any]:
    """转成响应字典。

    ``permissions`` 为 ``None`` 时返回 `RoleResponse`（不含权限明细），
    否则返回 `RoleDetail`（含明细）——列表页与详情页的字段不同。
    """
    if permissions is None:
        payload = RoleResponse.model_validate(role)
    else:
        payload = RoleDetail.model_validate(role)
        payload.permissions = permissions

    payload.admin_count = admin_count
    payload.permission_count = permission_count
    return payload.model_dump(mode="json")


# ============================================================
# 查询
# ============================================================


async def list_roles(session: AsyncSession) -> dict[str, Any]:
    """角色列表（API §14.6）。

    带 ``admin_count`` 与 ``permission_count``，供前端展示与
    删除前的引用提示。两者都是批量查询，避免 N+1。
    """
    role_repo = RoleRepository(session)
    admin_role_repo = AdminRoleRepository(session)
    permission_repo = PermissionRepository(session)

    roles = await role_repo.list_all()
    admin_counts = await admin_role_repo.count_by_role_bulk()
    permission_counts = await permission_repo.count_by_role_bulk()

    return {
        "items": [
            serialize_role(
                role,
                admin_count=admin_counts.get(role.id, 0),
                permission_count=permission_counts.get(role.id, 0),
            )
            for role in roles
        ]
    }


async def get_role(session: AsyncSession, role_id: uuid.UUID) -> dict[str, Any]:
    """角色详情，含权限项明细。"""
    role_repo = RoleRepository(session)
    admin_role_repo = AdminRoleRepository(session)
    permission_repo = PermissionRepository(session)

    role = await role_repo.get_by_id(role_id)
    if role is None:
        raise RoleNotFoundError()

    permissions = await permission_repo.list_by_role(role_id)
    admin_count = await admin_role_repo.count_admins_with_role(role_id)

    return serialize_role(
        role,
        admin_count=admin_count,
        permission_count=len(permissions),
        permissions=permissions,
    )


# ============================================================
# 写入
# ============================================================


async def _validate_permission_ids(
    session: AsyncSession, permission_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """校验权限项都存在，返回去重后的列表。"""
    if not permission_ids:
        return []

    permission_repo = PermissionRepository(session)
    perms = await permission_repo.get_by_ids(permission_ids)
    if len(perms) != len(set(permission_ids)):
        raise PermissionNotFoundError()
    return list(dict.fromkeys(permission_ids))


async def create_role(session: AsyncSession, *, payload: RoleCreate) -> dict[str, Any]:
    """创建角色（API §14.7）。"""
    role_repo = RoleRepository(session)
    permission_repo = PermissionRepository(session)
    rp_repo = RolePermissionRepository(session)

    if await role_repo.exists_code(payload.code):
        raise RoleCodeDuplicateError()

    permission_ids = await _validate_permission_ids(session, payload.permission_ids or [])

    role = Role(
        id=uuid7(),
        code=payload.code,
        name=payload.name,
        description=payload.description,
        # 通过接口创建的一定不是内置角色——内置角色由迁移写入
        is_builtin=False,
    )
    role_repo.add(role)
    await role_repo.flush()

    if permission_ids:
        await rp_repo.replace(role.id, permission_ids)

    await session.commit()
    await session.refresh(role)

    logger.info("创建角色 id=%s code=%s", role.id, role.code)
    return serialize_role(
        role,
        permission_count=len(permission_ids),
        permissions=await permission_repo.list_by_role(role.id),
    )


async def update_role(
    session: AsyncSession, *, role_id: uuid.UUID, payload: RoleUpdate
) -> None:
    """更新角色（API §14.8）。

    ``code`` 与 ``is_builtin`` 都不可改：
        - ``code`` 被代码直接引用，改了会让引用失效
        - ``is_builtin`` 由系统判定，不应通过接口设置
    """
    role_repo = RoleRepository(session)

    role = await role_repo.get_by_id(role_id)
    if role is None:
        raise RoleNotFoundError()

    if payload.name is not None:
        role.name = payload.name
    if payload.description is not None:
        role.description = payload.description

    await role_repo.flush()
    await session.commit()
    logger.info("更新角色 id=%s", role_id)


async def set_role_permissions(
    session: AsyncSession, *, role_id: uuid.UUID, permission_ids: list[uuid.UUID]
) -> None:
    """设置角色权限（整体替换语义）。

    替换而非增量：前端提交的是一棵勾选树，用户看到的就是
    「这个角色有哪些权限」，提交的应是完整状态而不是差异。
    """
    role_repo = RoleRepository(session)
    rp_repo = RolePermissionRepository(session)

    role = await role_repo.get_by_id(role_id)
    if role is None:
        raise RoleNotFoundError()

    validated = await _validate_permission_ids(session, permission_ids)

    await rp_repo.replace(role_id, validated)
    await session.commit()

    # 权限变更后必须失效缓存——否则持有该角色的管理员
    # 在 TTL 到期前仍按旧权限校验（可能多给，也可能少给）
    from app.api.middleware.permission import invalidate_role_permissions

    await invalidate_role_permissions(session, role_id)

    logger.info("设置角色权限 role_id=%s count=%s", role_id, len(validated))


async def delete_role(session: AsyncSession, *, role_id: uuid.UUID) -> None:
    """删除角色（API §14.9）。

    两条保护，顺序有讲究：
        1. 内置角色不可删（25006 / 400）——请求本身就不合法，
           与「当前有没有人用」无关，先判这个。
        2. 已分配给管理员（25005 / 409）——取决于运行时状态。
    """
    role_repo = RoleRepository(session)
    admin_role_repo = AdminRoleRepository(session)
    rp_repo = RolePermissionRepository(session)

    role = await role_repo.get_by_id(role_id)
    if role is None:
        raise RoleNotFoundError()

    if role.is_builtin:
        raise RoleBuiltinError()

    if await admin_role_repo.count_admins_with_role(role_id) > 0:
        raise RoleInUseError()

    # 删除前记录受影响的管理员——关联删掉后就查不到了
    affected = await admin_role_repo.list_admin_ids_with_role(role_id)

    # 先删权限关联，再删角色
    await rp_repo.replace(role_id, [])
    await role_repo.delete(role)
    await session.commit()

    from app.api.middleware.permission import invalidate_admin_permissions

    for admin_id in affected:
        await invalidate_admin_permissions(admin_id)

    logger.info("删除角色 id=%s code=%s", role_id, role.code)


# ============================================================
# 权限项
# ============================================================


async def list_permissions(session: AsyncSession) -> dict[str, Any]:
    """权限项列表（API §14.10）。

    DoD 要求「按 module + action 分组返回」——返回 ``groups``
    结构，每项是 ``{module, permissions: [...]}``，前端渲染
    权限勾选树时不必自己分组。

    同时保留扁平的 ``items``，便于需要平铺列表的场景。
    """
    permission_repo = PermissionRepository(session)
    permissions = await permission_repo.list_all()

    items = [PermissionBrief.model_validate(p) for p in permissions]

    grouped: dict[str, list[PermissionBrief]] = {}
    for item in items:
        grouped.setdefault(item.module, []).append(item)

    return {
        "items": [item.model_dump(mode="json") for item in items],
        "groups": [
            {
                "module": module,
                "permissions": [p.model_dump(mode="json") for p in perms],
            }
            for module, perms in grouped.items()
        ],
        "total": len(items),
    }


# ============================================================
# 操作日志查询（API §14.11）
# ============================================================


async def list_operation_logs(
    session: AsyncSession,
    *,
    admin_user_id: uuid.UUID | None = None,
    module: str | None = None,
    action: str | None = None,
    start_date: Any = None,
    end_date: Any = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """操作日志列表（API §14.11）。

    只读——**查询操作本身不记日志**（评审 §Q13），否则看日志这个
    动作会把日志表填满。
    """
    from sqlalchemy import text as sa_text

    from app.modules.system.repository import OperationLogRepository
    from app.modules.system.schemas import OperationLogResponse

    repo = OperationLogRepository(session)
    logs, total = await repo.list(
        admin_user_id=admin_user_id,
        module=module,
        action=action,
        start_date=start_date,
        end_date=end_date,
        offset=(page - 1) * page_size,
        limit=page_size,
    )

    # 批量补管理员用户名，避免 N+1
    admin_ids = {log.admin_user_id for log in logs}
    usernames: dict[uuid.UUID, str] = {}
    if admin_ids:
        result = await session.execute(
            sa_text("SELECT id, username FROM admin_user WHERE id = ANY(:ids)"),
            {"ids": list(admin_ids)},
        )
        usernames = {row[0]: row[1] for row in result.all()}

    items = []
    for log in logs:
        payload = OperationLogResponse.model_validate(log)
        payload.admin_username = usernames.get(log.admin_user_id)
        items.append(payload.model_dump(mode="json"))

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }
