"""M01 用户与账户的数据访问层。

只做数据操作，不含业务规则（架构 §4.3）。业务判断在 service.py。

约定（M0-T02 确认的事务边界）：
    Repository **不 commit**，只 flush 拿到自增/默认值。
    事务提交由 service 层负责——这样一次业务操作里的多次写入
    要么全成功、要么全回滚。
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.account.constants import BindingProvider, UserStatus
from app.modules.account.models import (
    Notification,
    OAuthBinding,
    User,
    UserProfile,
    UserSetting,
)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------------- 查询 ----------------

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_username(self, username: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def exists_by_username(self, username: str) -> bool:
        result = await self.session.execute(
            select(func.count()).select_from(User).where(User.username == username)
        )
        return result.scalar_one() > 0

    # ---------------- 写入 ----------------

    def add(self, user: User) -> User:
        self.session.add(user)
        return user

    async def increment_token_version(self, user_id: uuid.UUID) -> int | None:
        """原子自增 token_version，返回新值。

        用 ``UPDATE ... SET token_version = token_version + 1`` 而非
        「读出来 +1 再写回」——后者在并发下会丢失更新
        （两个请求都读到 0，都写 1，实际应该变成 2）。
        """
        from sqlalchemy import update

        result = await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(token_version=User.token_version + 1)
            .returning(User.token_version)
        )
        return result.scalar_one_or_none()

    async def flush(self) -> None:
        await self.session.flush()


class OAuthBindingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_provider(
        self, provider: BindingProvider | str, provider_uid: str
    ) -> OAuthBinding | None:
        """按 (provider, provider_uid) 查绑定。命中唯一索引。"""
        value = provider.value if isinstance(provider, BindingProvider) else provider
        result = await self.session.execute(
            select(OAuthBinding).where(
                OAuthBinding.provider == value,
                OAuthBinding.provider_uid == provider_uid,
            )
        )
        return result.scalar_one_or_none()

    async def exists_by_provider(
        self, provider: BindingProvider | str, provider_uid: str
    ) -> bool:
        """注册前检查 target 是否已被占用。

        用 count 而非取对象，避免把敏感字段（credential）读进内存。
        """
        value = provider.value if isinstance(provider, BindingProvider) else provider
        result = await self.session.execute(
            select(func.count())
            .select_from(OAuthBinding)
            .where(
                OAuthBinding.provider == value,
                OAuthBinding.provider_uid == provider_uid,
            )
        )
        return result.scalar_one() > 0

    async def list_by_user(self, user_id: uuid.UUID) -> list[OAuthBinding]:
        result = await self.session.execute(
            select(OAuthBinding)
            .where(OAuthBinding.user_id == user_id)
            .order_by(OAuthBinding.created_at)
        )
        return list(result.scalars().all())

    def add(self, binding: OAuthBinding) -> OAuthBinding:
        self.session.add(binding)
        return binding


class UserProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user_id(self, user_id: uuid.UUID) -> UserProfile | None:
        result = await self.session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    def add(self, profile: UserProfile) -> UserProfile:
        self.session.add(profile)
        return profile

    async def upsert_default(self, user_id: uuid.UUID) -> UserProfile:
        """不存在则创建空档案。注册时调用。"""
        existing = await self.get_by_user_id(user_id)
        if existing is not None:
            return existing
        profile = UserProfile(user_id=user_id)
        self.session.add(profile)
        return profile


class UserSettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user_id(self, user_id: uuid.UUID) -> UserSetting | None:
        result = await self.session.execute(
            select(UserSetting).where(UserSetting.user_id == user_id)
        )
        return result.scalar_one_or_none()

    def add(self, setting: UserSetting) -> UserSetting:
        self.session.add(setting)
        return setting

    async def upsert_default(self, user_id: uuid.UUID) -> UserSetting:
        """不存在则创建默认设置（全部 public / 允许推荐与通知）。"""
        existing = await self.get_by_user_id(user_id)
        if existing is not None:
            return existing
        setting = UserSetting(user_id=user_id)
        self.session.add(setting)
        return setting


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 20,
        is_read: bool | None = None,
        notification_type: str | None = None,
    ) -> tuple[list[Notification], int]:
        """分页查询，返回 (列表, 总数)。

        :param is_read: None 表示不筛选；True 只查已读；False 只查未读
        """
        conditions = [Notification.user_id == user_id]
        if is_read is not None:
            conditions.append(Notification.is_read.is_(is_read))  # type: ignore[attr-defined]
        if notification_type:
            conditions.append(Notification.notification_type == notification_type)

        total = (
            await self.session.execute(
                select(func.count()).select_from(Notification).where(*conditions)
            )
        ).scalar_one()

        result = await self.session.execute(
            select(Notification)
            .where(*conditions)
            .order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def count_unread(self, user_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),  # type: ignore[attr-defined]
            )
        )
        return result.scalar_one()

    async def get_by_id(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification | None:
        """按 ID + user_id 查，防止越权读取他人通知。"""
        result = await self.session.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    def add(self, notification: Notification) -> Notification:
        self.session.add(notification)
        return notification

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        """全部标记已读，返回受影响行数。"""
        from datetime import UTC, datetime

        from sqlalchemy import update

        result = await self.session.execute(
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),  # type: ignore[attr-defined]
            )
            .values(is_read=True, read_at=datetime.now(UTC))
        )
        return result.rowcount or 0


class AccountRepository:
    """M01 各实体的聚合入口，供 service 层一次性拿到。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.bindings = OAuthBindingRepository(session)
        self.profiles = UserProfileRepository(session)
        self.settings = UserSettingRepository(session)
        self.notifications = NotificationRepository(session)

    async def get_active_user(self, user_id: uuid.UUID) -> User | None:
        """取未被封禁/注销的用户。鉴权场景使用。"""
        user = await self.users.get_by_id(user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            return None
        return user

    async def resolve_region(self, code: str) -> dict[str, str] | None:
        """把行政区划编码还原成层级名称。

        返回 ``{"code", "province", "city", "display"}``；
        编码在字典中不存在时返回 ``None``（用户资料仍可展示）。

        **用原生 SQL 而非 ORM**：``region`` 属于 M11 catalog 模块，
        在 account 内导入其模型会形成跨模块耦合（与 catalog 查
        ``footprint`` 等表同一套做法）。
        """
        from sqlalchemy import text

        result = await self.session.execute(
            text(
                """
                SELECT self.name, self.level, parent.name
                FROM region self
                LEFT JOIN region parent ON parent.id = self.parent_id
                WHERE self.code = :code
                """
            ),
            {"code": code},
        )
        row = result.one_or_none()
        if row is None:
            return None

        name, level, parent_name = row

        if level == 1:
            province, city = name, None
            display = name
        else:
            province, city = parent_name, name
            display = f"{parent_name} {name}" if parent_name else name

        return {
            "code": code,
            "province": province or "",
            "city": city or "",
            "display": display,
        }

    async def get_token_version(self, user_id: uuid.UUID) -> int | None:
        """供 ``api/middleware/auth.py`` 的 ``token_version`` 比对使用。"""
        result = await self.session.execute(
            select(User.token_version).where(
                User.id == user_id,
                User.status != UserStatus.DELETED,
            )
        )
        return result.scalar_one_or_none()

    async def get_admin_token_version(self, admin_id: uuid.UUID) -> int | None:
        """管理员版本查询。admin_user 表在 M15 定义，此处用原生 SQL 避免耦合。"""
        from sqlalchemy import text

        result = await self.session.execute(
            text(
                "SELECT token_version FROM admin_user "
                "WHERE id = :admin_id AND status = 'active'"
            ),
            {"admin_id": admin_id},
        )
        return result.scalar_one_or_none()

    def __repr__(self) -> str:
        return f"<AccountRepository session={id(self.session)}>"


__all__: list[str] = [
    "AccountRepository",
    "NotificationRepository",
    "OAuthBindingRepository",
    "UserProfileRepository",
    "UserRepository",
    "UserSettingRepository",
]
