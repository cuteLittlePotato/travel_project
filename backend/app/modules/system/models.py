"""M15 系统管理的 ORM 模型。

对应 ``scripts/sql/schema.sql`` 的七张表：
    admin_user / role / permission / role_permission / admin_user_role
    operation_log / site_setting

规范（docs/rules/database-rules.md）：
    - 主键 UUID，命名 ``id``
    - **禁止物理外键**：``role_id`` / ``admin_user_id`` 等均为逻辑关联

**B 端管理员与 C 端用户完全分离**（评审 §Q10）：
``admin_user`` 与 ``user`` 是两套独立账号体系，不共用表、不共享 Token。
这是权限隔离的基础——C 端用户的任何操作都不应影响 B 端。

基类选择依据：
    | 表 | 时间字段 | 基类 |
    |---|---|---|
    | admin_user / role | created + updated | ``BaseModel`` |
    | permission / role_permission / admin_user_role / operation_log | 仅 created_at | ``UUIDPrimaryKeyMixin + CreatedAtMixin + Base`` |
    | site_setting | 仅 updated_at | ``UUIDPrimaryKeyMixin + UpdatedAtMixin + Base`` |
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
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

# ============================================================
# admin_user
# ============================================================


class AdminUser(BaseModel):
    """B 端管理员账号。

    ``token_version`` 与 C 端 ``user`` 表同名同义：登出/改密/禁用时自增，
    使所有已签发的 Token 立即失效。M0-T05 的 ``verify_token_version``
    已经读取该字段（``admin_auth.resolve_admin_token_version``）。
    """

    __tablename__ = "admin_user"
    __table_args__ = (
        Index("uk_admin_username", "username", unique=True),
        CheckConstraint("status IN ('active', 'disabled')", name="status"),
        {"comment": "B端管理员账号"},
    )

    username: Mapped[str] = mapped_column(String(50), nullable=False)
    #: bcrypt 哈希，**绝不存明文**
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    real_name: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    token_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="Token 版本号，登出/改密/禁用时自增，使所有已签发 Token 失效",
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<AdminUser {self.username} status={self.status}>"


# ============================================================
# role
# ============================================================


class Role(BaseModel):
    """角色。

    ``is_builtin`` 标记内置角色（超级管理员、普通管理员）。
    内置角色不允许删除或改编码——它们被代码直接引用
    （如 ``ROLE_SUPER_ADMIN`` 用于跳过权限校验）。
    """

    __tablename__ = "role"
    __table_args__ = (
        Index("uk_role_code", "code", unique=True),
        {"comment": "角色（当前内置超级管理员与普通用户，结构支持扩展）"},
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(200))
    is_builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    def __repr__(self) -> str:
        return f"<Role {self.code}>"


# ============================================================
# permission
# ============================================================


class Permission(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """权限项（模块 × 操作）。

    权限项是**静态字典**，由 M15-T02 随迁移初始化，运行时只读。
    新增权限项要改代码（新增接口时同步登记），不能通过 API 创建——
    否则权限体系会失去可审计性。
    """

    __tablename__ = "permission"
    __table_args__ = (
        Index("uk_permission_code", "code", unique=True),
        Index("idx_permission_module", "module", "action"),
        CheckConstraint(
            "action IN ('create', 'read', 'update', 'delete', 'export', 'manage')",
            name="permission_action",
        ),
        {"comment": "权限项（模块 × 操作，细粒度）"},
    )

    #: 权限编码，如 ``catalog.attraction.delete``
    code: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="权限编码，如 catalog.attraction.delete"
    )
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(200))

    def __repr__(self) -> str:
        return f"<Permission {self.code}>"


# ============================================================
# role_permission
# ============================================================


class RolePermission(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """角色权限关联。

    没有 ``updated_at``——关系变更即删除重建。
    """

    __tablename__ = "role_permission"
    __table_args__ = (
        Index("uk_role_perm", "role_id", "permission_id", unique=True),
        Index("idx_roleperm_role", "role_id"),
        {"comment": "角色权限关联"},
    )

    role_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    permission_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )


# ============================================================
# admin_user_role
# ============================================================


class AdminUserRole(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """管理员角色关联。

    一个管理员可以有多个角色，权限取并集。
    """

    __tablename__ = "admin_user_role"
    __table_args__ = (
        Index("uk_admin_role", "admin_user_id", "role_id", unique=True),
        Index("idx_adminrole_admin", "admin_user_id"),
        {"comment": "管理员角色关联"},
    )

    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)


# ============================================================
# operation_log
# ============================================================


class OperationLog(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """操作日志。

    **只记录增删改与登录登出，不记录查询**（DDL 注释的明确取舍）。
    查询量大，记下来会淹没真正需要审计的写操作。

    不分区——B 端管理操作频率远低于 C 端用户行为，
    单表在可预见的数据量下足够。
    """

    __tablename__ = "operation_log"
    __table_args__ = (
        Index("idx_oplog_admin", "admin_user_id", text("created_at DESC")),
        Index("idx_oplog_module", "module", text("created_at DESC")),
        Index("idx_oplog_time", text("created_at DESC")),
        CheckConstraint(
            "action IN ('create', 'update', 'delete', 'export', 'login', 'logout')",
            name="operation_log_action",
        ),
        {"comment": "操作日志（仅记录增删改与登录登出，不记录查询）"},
    )

    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    #: 操作详情（变更前后的关键字段），由业务层决定记录什么
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: IPv6 最长 45 字符
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    is_success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    def __repr__(self) -> str:
        return f"<OperationLog {self.module}.{self.action}>"


# ============================================================
# site_setting
# ============================================================


class SiteSetting(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    """平台级配置（键值对）。

    只有 ``updated_at``——配置项随初始化写入，创建时间无独立语义，
    有意义的「最近一次改动」由 ``updated_at`` 表达。

    ``setting_value`` 是 JSONB 而非 TEXT：配置值可能是字符串、数字、
    数组或对象，JSONB 让它们统一存储且可查询。
    """

    __tablename__ = "site_setting"
    __table_args__ = (
        Index("uk_setting_key", "setting_key", unique=True),
        {"comment": "平台级配置（键值对）"},
    )

    setting_key: Mapped[str] = mapped_column(String(100), nullable=False)
    setting_value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(String(200))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    def __repr__(self) -> str:
        return f"<SiteSetting {self.setting_key}>"


__all__ = [
    "AdminUser",
    "AdminUserRole",
    "OperationLog",
    "Permission",
    "Role",
    "RolePermission",
    "SiteSetting",
]
