"""M15 系统管理的业务逻辑（API §14.1 ~ §14.5）。

职责边界：
    - 业务校验（用户名重复、超管保护、自操作保护）在此
    - 密码哈希在此，Repository 只存 hash
    - 事务提交在此（Repository 只 flush）
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError
from app.core.security import hash_password
from app.modules.system.constants import (
    ERROR_ADMIN_LAST_SUPER,
    ERROR_ADMIN_NOT_FOUND,
    ERROR_ADMIN_SELF_DELETE,
    ERROR_ADMIN_SELF_DISABLE,
    ERROR_ADMIN_USERNAME_DUPLICATE,
    ERROR_ROLE_NOT_FOUND,
)
from app.modules.system.models import AdminUser
from app.modules.system.repository import (
    AdminRoleRepository,
    AdminUserRepository,
    RoleRepository,
)
from app.modules.system.schemas import AdminCreate, AdminResponse, AdminUpdate
from app.utils.ids import uuid7

logger = logging.getLogger(__name__)


# ============================================================
# 异常
# ============================================================


class AdminNotFoundError(BusinessError):
    def __init__(self) -> None:
        super().__init__(ERROR_ADMIN_NOT_FOUND, "管理员不存在", http_status=404)


class AdminUsernameDuplicateError(BusinessError):
    """用户名重复（API §14.2，25002 / HTTP 409）。"""

    def __init__(self) -> None:
        super().__init__(
            ERROR_ADMIN_USERNAME_DUPLICATE, "该用户名已存在", http_status=409
        )


class AdminLastSuperError(BusinessError):
    """仅存的超级管理员不能删除（API §14.5，25003 / HTTP 409）。

    删掉最后一个超管意味着再没人能管理系统——没有超管就没有人
    能分配角色，这个系统就永久锁死了，只能改库恢复。
    """

    def __init__(self) -> None:
        super().__init__(
            ERROR_ADMIN_LAST_SUPER,
            "系统必须保留至少一个超级管理员，无法删除",
            http_status=409,
        )


class AdminSelfDeleteError(BusinessError):
    """不能删除自己（API §14.5，25004 / HTTP 400）。"""

    def __init__(self) -> None:
        super().__init__(ERROR_ADMIN_SELF_DELETE, "不能删除自己", http_status=400)


class AdminSelfDisableError(BusinessError):
    """不能禁用自己——禁用后自己就登不上来了。"""

    def __init__(self) -> None:
        super().__init__(ERROR_ADMIN_SELF_DISABLE, "不能禁用自己", http_status=400)


class RoleNotFoundError(BusinessError):
    def __init__(self) -> None:
        super().__init__(ERROR_ROLE_NOT_FOUND, "角色不存在", http_status=404)


# ============================================================
# 序列化
# ============================================================


def serialize_admin(admin: AdminUser, roles: list[Any]) -> dict[str, Any]:
    """转成响应字典。

    用 ``AdminResponse`` 校验字段集——「不返回 ``password_hash`` 与
    ``token_version``」由 schema 定义保证，不靠调用点记得删字段。
    """
    payload = AdminResponse.model_validate(admin)
    payload.roles = roles
    return payload.model_dump(mode="json")


async def _load_roles_for(
    repo: AdminRoleRepository, admin_id: uuid.UUID
) -> list[Any]:
    return await repo.list_roles_of(admin_id)


# ============================================================
# 查询
# ============================================================


async def list_admins(
    session: AsyncSession,
    *,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    repo = AdminUserRepository(session)
    role_repo = AdminRoleRepository(session)

    admins, total = await repo.list(
        keyword=keyword,
        status=status,
        offset=(page - 1) * page_size,
        limit=page_size,
    )

    # 批量取角色，避免 N+1
    roles_map = await role_repo.list_roles_bulk([admin.id for admin in admins])

    return {
        "items": [
            serialize_admin(admin, roles_map.get(admin.id, [])) for admin in admins
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


async def get_admin(session: AsyncSession, admin_id: uuid.UUID) -> dict[str, Any]:
    repo = AdminUserRepository(session)
    role_repo = AdminRoleRepository(session)

    admin = await repo.get_by_id(admin_id)
    if admin is None:
        raise AdminNotFoundError()

    return serialize_admin(admin, await _load_roles_for(role_repo, admin_id))


# ============================================================
# 写入
# ============================================================


async def _validate_roles(
    session: AsyncSession, role_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """校验角色都存在，返回去重后的 ID 列表。"""
    role_repo = RoleRepository(session)
    roles = await role_repo.get_by_ids(role_ids)
    if len(roles) != len(set(role_ids)):
        raise RoleNotFoundError()
    return list(dict.fromkeys(role_ids))


async def create_admin(session: AsyncSession, *, payload: AdminCreate) -> dict[str, Any]:
    """创建管理员（API §14.2）。"""
    repo = AdminUserRepository(session)
    role_repo = AdminRoleRepository(session)

    if await repo.exists_username(payload.username):
        raise AdminUsernameDuplicateError()

    role_ids = await _validate_roles(session, payload.role_ids)

    admin = AdminUser(
        id=uuid7(),
        username=payload.username,
        password_hash=hash_password(payload.password),
        real_name=payload.real_name,
        email=payload.email,
        status="active",
        token_version=0,
    )
    repo.add(admin)
    await repo.flush()

    await role_repo.replace_roles(admin.id, role_ids)
    await session.commit()
    await session.refresh(admin)

    logger.info("创建管理员 id=%s username=%s", admin.id, admin.username)
    return serialize_admin(admin, await _load_roles_for(role_repo, admin.id))


async def update_admin(
    session: AsyncSession,
    *,
    admin_id: uuid.UUID,
    payload: AdminUpdate,
    current_admin_id: uuid.UUID,
) -> None:
    """更新管理员（API §14.3，PATCH 语义）。

    只改传入的字段。禁用自己会被拒绝——禁用后自己立即失去登录能力，
    这是一个不可逆的误操作。
    """
    repo = AdminUserRepository(session)
    role_repo = AdminRoleRepository(session)

    admin = await repo.get_by_id(admin_id)
    if admin is None:
        raise AdminNotFoundError()

    fields = payload.model_fields_set

    if "real_name" in fields:
        admin.real_name = payload.real_name
    if "email" in fields:
        admin.email = payload.email

    if payload.status is not None:
        if payload.status == "disabled" and admin_id == current_admin_id:
            raise AdminSelfDisableError()
        if payload.status != admin.status:
            admin.status = payload.status
            # 状态变更使该管理员所有已签发 Token 失效
            await repo.increment_token_version(admin_id)

    if payload.role_ids is not None:
        role_ids = await _validate_roles(session, payload.role_ids)
        await role_repo.replace_roles(admin_id, role_ids)

    await repo.flush()
    await session.commit()

    # 管理员角色变更后失效其权限缓存
    from app.api.middleware.permission import invalidate_admin_permissions

    await invalidate_admin_permissions(admin_id)

    logger.info("更新管理员 id=%s", admin_id)


async def reset_password(
    session: AsyncSession, *, admin_id: uuid.UUID, new_password: str
) -> None:
    """重置管理员密码（API §14.4）。

    重置后**必须**自增 ``token_version``（任务卡边界要求）：
    密码是账号的最后一道防线，改了密码就应假设旧凭据已泄露，
    让所有已签发的 Token 立即失效。

    注意这是「超管重置他人密码」，不校验原密码；校验原密码的
    「修改自己密码」在 API §14.16（M15-T08）。
    """
    repo = AdminUserRepository(session)

    admin = await repo.get_by_id(admin_id)
    if admin is None:
        raise AdminNotFoundError()

    admin.password_hash = hash_password(new_password)
    await repo.increment_token_version(admin_id)

    await repo.flush()
    await session.commit()

    # 重置密码后该管理员会重新登录，权限缓存一并清掉更干净
    from app.api.middleware.permission import invalidate_admin_permissions

    await invalidate_admin_permissions(admin_id)

    logger.info("重置管理员密码 id=%s", admin_id)


async def delete_admin(
    session: AsyncSession, *, admin_id: uuid.UUID, current_admin_id: uuid.UUID
) -> None:
    """删除管理员（API §14.5）。

    两条保护，顺序有讲究：
        1. 不能删除自己（25004）——先查这个，是纯粹的操作失误。
        2. 仅存的超级管理员不能删（25003）——删了系统就锁死了。
    """
    repo = AdminUserRepository(session)
    role_repo = AdminRoleRepository(session)

    admin = await repo.get_by_id(admin_id)
    if admin is None:
        raise AdminNotFoundError()

    if admin_id == current_admin_id:
        raise AdminSelfDeleteError()

    is_super = await role_repo.is_super_admin(admin_id)
    if is_super and await role_repo.count_super_admins() <= 1:
        raise AdminLastSuperError()

    # 先删角色关联，再删管理员
    await role_repo.replace_roles(admin_id, [])
    await repo.delete(admin)
    await session.commit()
    logger.info("删除管理员 id=%s username=%s", admin_id, admin.username)
