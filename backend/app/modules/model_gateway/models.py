"""M12 模型管理的 ORM 模型。

对应 ``scripts/sql/schema.sql`` 的两张表：
    model / model_call_log

规范（docs/rules/database-rules.md）：
    - 主键 UUID，命名 ``id``
    - 时间统一 TIMESTAMPTZ
    - **禁止物理外键**：``model_call_log.model_id`` 是逻辑关联，
      模型被删除后日志仍保留（数据库设计 §4.2「保留不删」）

基类选择依据：
    | 表 | 时间字段 | 基类 |
    |---|---|---|
    | model | created_at + updated_at | ``BaseModel`` |
    | model_call_log | 仅 created_at | ``UUIDPrimaryKeyMixin + CreatedAtMixin + Base`` |

**关于 ``model_call_log`` 的分区**：
    该表在 PostgreSQL 中是 ``PARTITION BY RANGE (created_at)`` 的分区表，
    主键为复合主键 ``(id, created_at)``。SQLAlchemy 的 ORM 模型只需映射
    父表的逻辑结构——分区是物理存储细节，ORM 读写分区表与普通表无异
    （PostgreSQL 会按 ``created_at`` 自动路由到对应分区）。

    这里**不声明** ``postgresql_partition_by``：那是 Alembic 建表用的参数，
    已在迁移 ``0011_m12_model.py`` 中体现。ORM 模型加了这个参数会让
    ``Base.metadata.create_all()`` 尝试重建分区表，与迁移冲突。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BaseModel
from app.modules.model_gateway.constants import DEFAULT_TIMEOUT_SECONDS

# ============================================================
# model
# ============================================================


class Model(BaseModel):
    """模型注册（统一 OpenAI 兼容接口）。

    ``api_key_encrypted`` 存密文，加密/解密在应用层完成——
    密钥不能以明文入库，也不能出现在日志里。

    ``is_default`` 的「每类别最多一个」由**部分唯一索引**
    ``idx_model_default (category) WHERE is_default = TRUE`` 保证。
    应用层切换默认模型时必须先关闭旧的再打开新的，
    否则会撞唯一索引（这也是并发下的最后一道防线）。
    """

    __tablename__ = "model"
    __table_args__ = (
        Index("uk_model_category_code", "category", "model_code", "base_url", unique=True),
        Index("idx_model_category", "category", "is_enabled"),
        Index(
            "idx_model_default",
            "category",
            unique=True,
            postgresql_where=text("is_default = TRUE"),
        ),
        CheckConstraint(
            "category IN ('chat', 'vision', 'embedding', 'rerank', 'ocr')",
            name="ck_model_category",
        ),
        {
            "comment": "注意：无 vector_dim 字段，向量维度由配置文件控制",
        },
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="类别：chat=文本对话，vision=图片理解，embedding=向量化，rerank=重排序，ocr=OCR解析",
    )
    #: 调用模型 ID，如 ``deepseek-chat``
    model_code: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="调用模型 ID，如 deepseek-chat"
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    #: 加密后的 API Key，应用层解密使用
    api_key_encrypted: Mapped[str | None] = mapped_column(
        Text, comment="加密后的 API Key，应用层解密使用"
    )
    max_context_tokens: Mapped[int | None] = mapped_column(Integer)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer)
    timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=str(DEFAULT_TIMEOUT_SECONDS)
    )
    concurrency_limit: Mapped[int | None] = mapped_column(Integer)
    #: 输入单价（元 / 千 token）
    price_input: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    #: 输出单价（元 / 千 token）
    price_output: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    description: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    #: 每类别最多一个默认模型（部分唯一索引保证）
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        comment="每类别最多一个默认模型（部分唯一索引保证）",
    )
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)

    def __repr__(self) -> str:
        return f"<Model {self.category}:{self.model_code} enabled={self.is_enabled}>"


# ============================================================
# model_call_log
# ============================================================


class ModelCallLog(Base):
    """模型调用日志（按月分区）。

    没有 ``updated_at``——日志写入后不再修改，这是审计数据的基本要求。

    复合主键 ``(id, created_at)``：PostgreSQL 要求分区键必须包含在主键中，
    因此本表**不能用** ``UUIDPrimaryKeyMixin``（它把 ``id`` 单独设为主键）。
    两列都在类里显式声明。

    这意味着本表的 ``id`` 本身不唯一，唯一的是 ``(id, created_at)``——
    实际使用中 id 是 UUIDv7，重复概率可忽略。

    索引在迁移中按分区建立；模型这里同时声明，供 ``check_model_drift``
    与 DDL 比对（分区子表的索引由 ``include_object`` 过滤掉）。
    """

    __tablename__ = "model_call_log"
    __table_args__ = (
        Index("idx_mcalllog_model_time", "model_id", text("created_at DESC")),
        Index("idx_mcalllog_user_time", "user_id", text("created_at DESC")),
        Index("idx_mcalllog_caller", "caller_type", text("created_at DESC")),
        Index("idx_mcalllog_success", "is_success", text("created_at DESC")),
        {
            "comment": "模型调用日志（按月分区）",
        },
    )

    #: 与 ``created_at`` 组成复合主键（分区表要求）
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        nullable=False,
        server_default=func.now(),
    )

    model_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    #: user_chat=C端对话（计入额度），system_document=B端文档处理（不计入额度）
    caller_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="调用来源：user_chat=C端对话（计入额度），system_document=B端文档处理（不计入额度）",
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    session_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    document_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    token_input: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    token_output: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    is_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: 失败类型：timeout/auth/rate_limit/server_error/format_invalid
    error_type: Mapped[str | None] = mapped_column(
        String(50),
        comment="失败类型：timeout/auth/rate_limit/server_error/format_invalid",
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))

    def __repr__(self) -> str:
        return f"<ModelCallLog model={self.model_id} success={self.is_success}>"


__all__ = ["Model", "ModelCallLog"]
