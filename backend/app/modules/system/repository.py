"""M15 系统管理的数据访问层。

Repository **不 commit**，只 flush——事务边界在 service 层。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.system.constants import ROLE_SUPER_ADMIN
from app.modules.system.models import (
    AdminUser,
    AdminUserRole,
    OperationLog,
    Permission,
    Role,
    RolePermission,
    SiteSetting,
)


class AdminUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, admin_id: uuid.UUID) -> AdminUser | None:
        return await self.session.get(AdminUser, admin_id)

    async def get_by_username(self, username: str) -> AdminUser | None:
        result = await self.session.execute(
            select(AdminUser).where(AdminUser.username == username)
        )
        return result.scalar_one_or_none()

    async def exists_username(
        self, username: str, exclude_id: uuid.UUID | None = None
    ) -> bool:
        stmt = (
            select(func.count())
            .select_from(AdminUser)
            .where(AdminUser.username == username)
        )
        if exclude_id is not None:
            stmt = stmt.where(AdminUser.id != exclude_id)
        return (await self.session.execute(stmt)).scalar_one() > 0

    async def list(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[AdminUser], int]:
        conditions = []
        if keyword:
            conditions.append(
                AdminUser.username.ilike(f"%{keyword}%")
                | AdminUser.real_name.ilike(f"%{keyword}%")
            )
        if status is not None:
            conditions.append(AdminUser.status == status)

        stmt = select(AdminUser).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        stmt = (
            stmt.order_by(AdminUser.created_at.desc(), AdminUser.username)
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all()), total

    def add(self, admin: AdminUser) -> AdminUser:
        self.session.add(admin)
        return admin

    async def delete(self, admin: AdminUser) -> None:
        await self.session.delete(admin)

    async def increment_token_version(self, admin_id: uuid.UUID) -> int | None:
        """原子自增 ``token_version``，使该管理员所有已签发 Token 失效。

        与 M01 的 ``UserRepository.increment_token_version`` 同一套做法：
        用 ``UPDATE ... SET x = x + 1`` 而非读改写，避免并发丢失更新。
        """
        result = await self.session.execute(
            update(AdminUser)
            .where(AdminUser.id == admin_id)
            .values(token_version=AdminUser.token_version + 1)
            .returning(AdminUser.token_version)
        )
        return result.scalar_one_or_none()

    async def flush(self) -> None:
        await self.session.flush()


class AdminRoleRepository:
    """管理员-角色关联。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_roles_of(self, admin_id: uuid.UUID) -> list[Role]:
        result = await self.session.execute(
            select(Role)
            .join(AdminUserRole, AdminUserRole.role_id == Role.id)
            .where(AdminUserRole.admin_user_id == admin_id)
            .order_by(Role.code)
        )
        return list(result.scalars().all())

    async def list_roles_bulk(
        self, admin_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[Role]]:
        """批量取管理员角色，避免列表页 N+1。"""
        if not admin_ids:
            return {}
        result = await self.session.execute(
            select(AdminUserRole.admin_user_id, Role)
            .join(Role, Role.id == AdminUserRole.role_id)
            .where(AdminUserRole.admin_user_id.in_(set(admin_ids)))
            .order_by(Role.code)
        )
        mapping: dict[uuid.UUID, list[Role]] = {}
        for admin_id, role in result.all():
            mapping.setdefault(admin_id, []).append(role)
        return mapping

    async def replace_roles(self, admin_id: uuid.UUID, role_ids: list[uuid.UUID]) -> None:
        """整体替换管理员的角色。

        先删后插——角色变更即重建关联，比逐条比对简单且不会漏。
        """
        await self.session.execute(
            delete(AdminUserRole).where(AdminUserRole.admin_user_id == admin_id)
        )
        for role_id in set(role_ids):
            self.session.add(
                AdminUserRole(
                    id=uuid.uuid4(),
                    admin_user_id=admin_id,
                    role_id=role_id,
                )
            )

    async def list_admin_ids_with_role(self, role_id: uuid.UUID) -> list[uuid.UUID]:
        """列出持有该角色的管理员 ID。

        角色删除前用它记录受影响的人，删完关联就查不到了。
        """
        result = await self.session.execute(
            select(AdminUserRole.admin_user_id).where(
                AdminUserRole.role_id == role_id
            )
        )
        return [row[0] for row in result.all()]

    async def count_admins_with_role(self, role_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(AdminUserRole)
            .where(AdminUserRole.role_id == role_id)
        )
        return result.scalar_one()

    async def count_by_role_bulk(self) -> dict[uuid.UUID, int]:
        result = await self.session.execute(
            select(AdminUserRole.role_id, func.count()).group_by(AdminUserRole.role_id)
        )
        return {row[0]: row[1] for row in result.all()}

    async def count_super_admins(self) -> int:
        """统计持有超级管理员角色的管理员数量。

        用于「不能删除仅存的超级管理员」检查（API §14.5）。
        """
        result = await self.session.execute(
            select(func.count(func.distinct(AdminUserRole.admin_user_id)))
            .select_from(AdminUserRole)
            .join(Role, Role.id == AdminUserRole.role_id)
            .where(Role.code == ROLE_SUPER_ADMIN)
        )
        return result.scalar_one()

    async def is_super_admin(self, admin_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            select(func.count())
            .select_from(AdminUserRole)
            .join(Role, Role.id == AdminUserRole.role_id)
            .where(
                AdminUserRole.admin_user_id == admin_id,
                Role.code == ROLE_SUPER_ADMIN,
            )
        )
        return result.scalar_one() > 0

    async def flush(self) -> None:
        await self.session.flush()


class RoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, role_id: uuid.UUID) -> Role | None:
        return await self.session.get(Role, role_id)

    async def get_by_code(self, code: str) -> Role | None:
        result = await self.session.execute(select(Role).where(Role.code == code))
        return result.scalar_one_or_none()

    async def exists_code(self, code: str, exclude_id: uuid.UUID | None = None) -> bool:
        stmt = select(func.count()).select_from(Role).where(Role.code == code)
        if exclude_id is not None:
            stmt = stmt.where(Role.id != exclude_id)
        return (await self.session.execute(stmt)).scalar_one() > 0

    async def list_all(self) -> list[Role]:
        result = await self.session.execute(
            select(Role).order_by(Role.is_builtin.desc(), Role.code)
        )
        return list(result.scalars().all())

    async def get_by_ids(self, role_ids: list[uuid.UUID]) -> list[Role]:
        if not role_ids:
            return []
        result = await self.session.execute(
            select(Role).where(Role.id.in_(set(role_ids)))
        )
        return list(result.scalars().all())

    def add(self, role: Role) -> Role:
        self.session.add(role)
        return role

    async def delete(self, role: Role) -> None:
        await self.session.delete(role)

    async def flush(self) -> None:
        await self.session.flush()


class PermissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> list[Permission]:
        result = await self.session.execute(
            select(Permission).order_by(Permission.module, Permission.action, Permission.code)
        )
        return list(result.scalars().all())

    async def get_by_ids(self, permission_ids: list[uuid.UUID]) -> list[Permission]:
        if not permission_ids:
            return []
        result = await self.session.execute(
            select(Permission).where(Permission.id.in_(set(permission_ids)))
        )
        return list(result.scalars().all())

    async def list_by_role(self, role_id: uuid.UUID) -> list[Permission]:
        result = await self.session.execute(
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
            .order_by(Permission.module, Permission.action)
        )
        return list(result.scalars().all())

    async def count_by_role_bulk(self) -> dict[uuid.UUID, int]:
        result = await self.session.execute(
            select(RolePermission.role_id, func.count()).group_by(RolePermission.role_id)
        )
        return {row[0]: row[1] for row in result.all()}


class RolePermissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def replace(
        self, role_id: uuid.UUID, permission_ids: list[uuid.UUID]
    ) -> None:
        await self.session.execute(
            delete(RolePermission).where(RolePermission.role_id == role_id)
        )
        for permission_id in set(permission_ids):
            self.session.add(
                RolePermission(
                    id=uuid.uuid4(),
                    role_id=role_id,
                    permission_id=permission_id,
                )
            )

    async def list_codes_of_admin(self, admin_id: uuid.UUID) -> list[str]:
        """管理员拥有的**全部权限编码**（多个角色取并集）。

        这是权限中间件（M15-T05）的查询入口。
        """
        result = await self.session.execute(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(AdminUserRole, AdminUserRole.role_id == RolePermission.role_id)
            .where(AdminUserRole.admin_user_id == admin_id)
            .distinct()
        )
        return list(result.scalars().all())

    async def admin_has_permission(self, admin_id: uuid.UUID, code: str) -> bool:
        result = await self.session.execute(
            select(func.count())
            .select_from(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(AdminUserRole, AdminUserRole.role_id == RolePermission.role_id)
            .where(AdminUserRole.admin_user_id == admin_id, Permission.code == code)
        )
        return result.scalar_one() > 0


class OperationLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, log: OperationLog) -> OperationLog:
        self.session.add(log)
        return log

    async def list(
        self,
        *,
        admin_user_id: uuid.UUID | None = None,
        module: str | None = None,
        action: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[OperationLog], int]:
        conditions = []
        if admin_user_id is not None:
            conditions.append(OperationLog.admin_user_id == admin_user_id)
        if module is not None:
            conditions.append(OperationLog.module == module)
        if action is not None:
            conditions.append(OperationLog.action == action)
        # 用 Python datetime 而非原样传字符串——字符串比较会按字典序，
        # 且无法利用索引
        if start_date is not None:
            conditions.append(OperationLog.created_at >= start_date)
        if end_date is not None:
            conditions.append(OperationLog.created_at <= end_date)

        stmt = select(OperationLog).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        stmt = (
            stmt.order_by(OperationLog.created_at.desc()).offset(offset).limit(limit)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, total


class SiteSettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_key(self, key: str) -> SiteSetting | None:
        result = await self.session.execute(
            select(SiteSetting).where(SiteSetting.setting_key == key)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[SiteSetting]:
        result = await self.session.execute(select(SiteSetting).order_by(SiteSetting.setting_key))
        return list(result.scalars().all())

    def add(self, setting: SiteSetting) -> SiteSetting:
        self.session.add(setting)
        return setting

    async def flush(self) -> None:
        await self.session.flush()
