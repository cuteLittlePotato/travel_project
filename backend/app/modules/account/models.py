"""M01 用户与账户的 ORM 模型。

对应 ``scripts/sql/schema.sql`` 的五张表：
    user / oauth_binding / user_profile / user_setting / notification

规范（docs/rules/database-rules.md）：
    - 主键 UUID，命名 ``id``
    - 时间统一 TIMESTAMPTZ
    - **禁止物理外键**：表间关系用逻辑关联字段（``user_id``）表达，
      完整性由应用层维护，因此本文件不出现任何关系声明

注意 ``user_profile`` / ``user_setting`` 没有 ``created_at``，
数据库设计只定义了 ``updated_at``，故继承 ``UpdatedAtMixin`` 而非 ``BaseModel``。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    BaseModel,
    CreatedAtMixin,
    UpdatedAtMixin,
    UUIDPrimaryKeyMixin,
)
from app.modules.account.constants import (
    BindingProvider,
    BudgetLevel,
    CompanionType,
    Gender,
    NotificationType,
    UserStatus,
    Visibility,
)


def _in_clause(column: str, values: type[Any]) -> str:
    """生成 ``CHECK (col IN ('a','b'))`` 的表达式文本。

    直接写死字符串容易与 constants.py 不同步，这里从枚举生成。
    """
    quoted = ", ".join(f"'{v.value}'" for v in values)  # type: ignore[attr-defined]
    return f"{column} IN ({quoted})"


# ============================================================
# user
# ============================================================


class User(BaseModel):
    """用户主表。

    账号由三种方式产生：手机号/邮箱注册、验证码登录自动注册、第三方登录。
    同一个用户可绑定多种登录方式（见 ``OAuthBinding``）。
    """

    __tablename__ = "user"
    __table_args__ = (
        Index("uk_user_username", "username", unique=True),
        CheckConstraint(_in_clause("gender", Gender), name="ck_user_gender"),
        CheckConstraint(_in_clause("status", UserStatus), name="ck_user_status"),
        Index("idx_user_status", "status"),
        Index("idx_user_created_at", text("created_at DESC")),
            {"comment": "用户主表"},
    )

    username: Mapped[str] = mapped_column(String(50), nullable=False)
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    gender: Mapped[str | None] = mapped_column(String(10))
    #: 常驻地区行政区划编码（GB/T 2260），用于推荐与地区筛选
    region_code: Mapped[str | None] = mapped_column(
        String(20), comment="常驻地区行政区划编码"
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=UserStatus.ACTIVE.value,
        comment="账号状态：active=正常，banned=封禁，deleted=已注销",
    )
    #: Token 版本号。登出/改密/封禁时自增，使所有已签发 Token 失效（全端登出）
    token_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="Token 版本号，登出/改密/封禁时自增，使所有已签发 Token 失效（全端登出）",
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    def __repr__(self) -> str:
        return f"<User {self.id} {self.username}>"


# ============================================================
# oauth_binding
# ============================================================


class OAuthBinding(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """登录方式绑定。

    一个用户可以绑定手机号、邮箱、微信等多个方式，其中至多一个为主方式
    （``is_primary``）。``credential`` 存放密码哈希或第三方凭据，
    **绝不可出现在任何对外响应中**。

    注意：本表只有 ``created_at``，没有 ``updated_at``——绑定关系创建后
    不会原地修改（换绑即删除重建）。
    """

    __tablename__ = "oauth_binding"
    __table_args__ = (
        # 同一提供商的同一账号只能绑定一次（DoD 要求）
        Index("uk_oauth_provider_uid", "provider", "provider_uid", unique=True),
        CheckConstraint(_in_clause("provider", BindingProvider), name="ck_oauth_binding_provider"),
        Index("idx_oauth_user_id", "user_id"),
            {"comment": "登录方式绑定表"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    #: 手机号、邮箱地址、或第三方 openid
    provider_uid: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="第三方唯一标识：手机号、邮箱、openid 等"
    )
    #: 密码哈希（bcrypt）或第三方 access_token。**敏感字段，禁止对外序列化**
    credential: Mapped[str | None] = mapped_column(
        String(255), comment="密码哈希，仅 phone/email 方式使用（bcrypt）"
    )
    extra_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    def __repr__(self) -> str:
        return f"<OAuthBinding {self.provider}:{self.provider_uid[:8]}…>"


# ============================================================
# user_profile
# ============================================================


class UserProfile(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    """用户旅游偏好（与 user 一对一）。

    与 ``user_setting`` 一样没有 ``created_at``——记录随注册自动创建，
    创建时间即注册时间，无独立语义。
    """

    __tablename__ = "user_profile"
    __table_args__ = (
        Index("uk_user_profile_user_id", "user_id", unique=True),
        CheckConstraint(_in_clause("budget_level", BudgetLevel), name="ck_user_profile_budget_level"),
        CheckConstraint(
            _in_clause("companion_type", CompanionType), name="ck_user_profile_companion_type"
        ),
            {"comment": "用户偏好档案（用户显式设置）"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    #: 旅游类型偏好，如 ["历史文化", "自然风光"]。最多 10 项
    travel_types: Mapped[list[str] | None] = mapped_column(
        JSONB, comment='旅游类型偏好数组，如 ["历史人文","自然风光"]'
    )
    #: 旅游风格，如 ["深度游", "休闲"]。最多 10 项
    travel_styles: Mapped[list[str] | None] = mapped_column(JSONB)
    budget_level: Mapped[str | None] = mapped_column(
        String(20), comment="预算等级：economy=经济，moderate=中等，comfortable=舒适，luxury=豪华"
    )
    companion_type: Mapped[str | None] = mapped_column(String(20))
    #: 偏好季节，如 ["spring", "autumn"]
    preferred_seasons: Mapped[list[str] | None] = mapped_column(JSONB)
    #: 默认出发城市**编码**（GB/T 2260），用于交通与周边推荐
    #:
    #: 存编码而非城市名：名称会因运营在 B 端「省市管理」中改名而失效，
    #: 编码是稳定标识。与 ``user.region_code`` 保持同一套格式。
    departure_city_code: Mapped[str | None] = mapped_column(
        String(20),
        comment="默认出发城市编码（GB/T 2260），与 user.region_code 同一套格式",
    )

    def __repr__(self) -> str:
        return f"<UserProfile user={self.user_id}>"


# ============================================================
# user_setting
# ============================================================


class UserSetting(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    """用户隐私与通知设置（与 user 一对一）。"""

    __tablename__ = "user_setting"
    __table_args__ = (
        Index("uk_user_setting_user_id", "user_id", unique=True),
        CheckConstraint(
            _in_clause("profile_visibility", Visibility), name="ck_user_setting_profile_visibility"
        ),
        CheckConstraint(
            _in_clause("footprint_visibility", Visibility), name="ck_user_setting_footprint_visibility"
        ),
        CheckConstraint(
            _in_clause("plan_visibility", Visibility), name="ck_user_setting_plan_visibility"
        ),
            {"comment": "用户隐私与通知设置"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    profile_visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=Visibility.PUBLIC.value
    )
    footprint_visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=Visibility.PUBLIC.value
    )
    plan_visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=Visibility.PUBLIC.value
    )
    allow_recommendation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    allow_notification: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    def __repr__(self) -> str:
        return f"<UserSetting user={self.user_id}>"


# ============================================================
# notification
# ============================================================


class Notification(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """站内通知。

    三类来源：计划即将开始、计划已结束、系统通知。
    ``related_type`` + ``related_id`` 指向关联资源（如 ``trip_plan``），
    点击通知时前端据此跳转。

    本表有 ``created_at`` 但没有 ``updated_at``（已读状态用 ``read_at`` 表达）。
    """

    __tablename__ = "notification"
    __table_args__ = (
        CheckConstraint(
            _in_clause("notification_type", NotificationType), name="ck_notification_notification_type"
        ),
        Index("idx_notification_user", "user_id", text("created_at DESC")),
        # 未读查询走部分索引，只索引 is_read = FALSE 的行，体积小
        Index(
            "idx_notification_unread",
            "user_id",
            "is_read",
            postgresql_where=text("is_read = FALSE"),
        ),
        Index("idx_notification_type", "notification_type", text("created_at DESC")),
            {"comment": "站内通知"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    notification_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="通知类型：plan_starting=计划即将开始，plan_ended=计划已结束（提醒确认完成），system=系统通知",
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    #: 关联资源类型，如 "trip_plan"、"footprint"
    related_type: Mapped[str | None] = mapped_column(
        String(50), comment="关联对象类型：plan / footprint / system"
    )
    related_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), comment="关联对象 ID，点击通知可跳转到对应页面"
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def mark_read(self) -> None:
        """标记为已读。重复调用不改变 ``read_at``（幂等）。

        注意 ``is_read`` 的默认值来自数据库 ``server_default``，
        新建对象在 flush 前该属性为 ``None``，因此用真值判断而非 ``is True``。
        """
        if not self.is_read:
            self.is_read = True
            self.read_at = datetime.now(UTC)

    def __repr__(self) -> str:
        return f"<Notification {self.id} {self.notification_type}>"


__all__ = [
    "Notification",
    "OAuthBinding",
    "User",
    "UserProfile",
    "UserSetting",
]
