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

#: 统一约束命名规则，保证 Alembic 自动生成的约束名可预测
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "pk": "pk_%(table_name)s",
}


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


class BaseModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """业务表通用基类：UUID 主键 + 创建/更新时间。"""

    __abstract__ = True
