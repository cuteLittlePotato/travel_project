"""ORM 基类与通用字段约定。

规范（docs/rules/database-rules.md）：
- 主键统一 ``id``，UUID 类型
- 时间统一 TIMESTAMPTZ
- **禁止物理外键**，表间关系由应用层维护
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: 约束命名规则。
#:
#: **刻意不使用 naming_convention**（2026-11-08 修正）：
#: 初始迁移由 ``scripts/generate_migrations.py`` 从 ``schema.sql`` 生成，
#: 所有约束名都已按设计文档显式写死（``ck_user_gender``、``uk_user_username`` 等）。
#: 若再启用 ``ck_%(table_name)s_%(constraint_name)s`` 之类的模板，
#: SQLAlchemy 会二次加前缀，产生 ``ck_user_ck_user_status`` 这类重复名——
#: M0-T13 曾因此产生 39 个错误命名的约束。
#:
#: 约定：**约束名一律在模型/迁移中显式指定**，不依赖自动推导。
NAMING_CONVENTION: dict[str, str] = {}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """UUID 主键。

    业务侧使用 UUIDv7 生成（时间有序，索引友好），
    数据库层不加 ``gen_random_uuid()`` 默认值，由应用负责赋值。
    """

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CreatedAtMixin:
    """仅含 ``created_at``。

    用于「只追加、不修改」的表——如 ``oauth_binding``、``notification``：
    绑定关系换绑即删重建，通知已读用 ``read_at`` 表达，
    这类表没有 ``updated_at`` 的语义。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UpdatedAtMixin:
    """仅含 ``updated_at``。

    用于「一对一扩展表」——如 ``user_profile``、``user_setting``：
    记录随主表创建而生成，本身没有独立的创建时间语义，
    数据库设计也只定义了 ``updated_at``。
    """

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class BaseModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """业务表通用基类：UUID 主键 + 创建/更新时间。

    Mixin 必须排在 ``Base`` 之前，否则 SQLAlchemy 收集列时的解析顺序不符合
    MRO 约定，多个 Mixin 叠加时容易出现列覆盖问题。
    """

    __abstract__ = True
