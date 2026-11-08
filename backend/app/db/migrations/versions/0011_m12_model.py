"""M12 模型管理

Revision ID: 0011_m12_model
Revises: 0010_m05_footprint
Create Date: 2026-11-08

由 scripts/generate_migrations.py 从 scripts/sql/schema.sql 自动生成。
手工修改需同步更新 schema.sql，否则重新生成会被覆盖。

规范（docs/rules/database-rules.md）：
    - 主键 UUID，无 SERIAL/BIGSERIAL
    - 禁止物理外键，表间关系由应用层维护
    - 时间字段统一 TIMESTAMPTZ
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_m12_model"
down_revision: str | None = "0010_m05_footprint"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("model_code", sa.String(100), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("api_key_encrypted", sa.Text()),
        sa.Column("max_context_tokens", sa.Integer()),
        sa.Column("max_output_tokens", sa.Integer()),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default='60'),
        sa.Column("concurrency_limit", sa.Integer()),
        sa.Column("price_input", sa.Numeric(12, 6)),
        sa.Column("price_output", sa.Numeric(12, 6)),
        sa.Column("description", sa.Text()),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default='true'),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default='false'),
        sa.Column("last_test_at", sa.DateTime(timezone=True)),
        sa.Column("last_test_ok", sa.Boolean()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("category IN ('chat', 'vision', 'embedding', 'rerank', 'ocr')", name="ck_model_category"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "model" IS \'注意：无 vector_dim 字段，向量维度由配置文件控制\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "model"."category" IS \'类别：chat=文本对话，vision=图片理解，embedding=向量化，rerank=重排序，ocr=OCR解析\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "model"."model_code" IS \'调用模型 ID，如 deepseek-chat\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "model"."api_key_encrypted" IS \'加密后的 API Key，应用层解密使用\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "model"."is_default" IS \'每类别最多一个默认模型（部分唯一索引保证）\'')
    op.create_table(
        "model_call_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("caller_type", sa.String(20), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("session_id", postgresql.UUID(as_uuid=True)),
        sa.Column("document_id", postgresql.UUID(as_uuid=True)),
        sa.Column("token_input", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("token_output", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("is_success", sa.Boolean(), nullable=False),
        sa.Column("error_type", sa.String(50)),
        sa.Column("error_message", sa.Text()),
        sa.Column("cost_estimate", sa.Numeric(12, 6)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("caller_type IN ('user_chat', 'system_document')", name="ck_model_call_log_caller_type"),
        postgresql_partition_by="RANGE (created_at)",
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "model_call_log" IS \'模型调用日志（按月分区）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "model_call_log"."caller_type" IS \'调用来源：user_chat=C端对话（计入额度），system_document=B端文档处理（不计入额度）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "model_call_log"."error_type" IS \'失败类型：timeout/auth/rate_limit/server_error/format_invalid\'')
    op.create_index("uk_model_category_code", "model", ['category', 'model_code', 'base_url'], unique=True)
    op.create_index("idx_model_category", "model", ['category', 'is_enabled'])
    op.create_index("idx_model_default", "model", ['category'], unique=True)
    op.execute('CREATE INDEX idx_mcalllog_model_time ON "model_call_log" (model_id, created_at DESC)')
    op.execute('CREATE INDEX idx_mcalllog_user_time ON "model_call_log" (user_id, created_at DESC)')
    op.execute('CREATE INDEX idx_mcalllog_caller ON "model_call_log" (caller_type, created_at DESC)')
    op.execute('CREATE INDEX idx_mcalllog_success ON "model_call_log" (is_success, created_at DESC)')
    op.get_bind().exec_driver_sql("CREATE TABLE model_call_log_p2026_11 PARTITION OF model_call_log FOR VALUES FROM ('2026-11-01') TO ('2026-12-01')")
    op.get_bind().exec_driver_sql("CREATE TABLE model_call_log_p2026_12 PARTITION OF model_call_log FOR VALUES FROM ('2026-12-01') TO ('2027-01-01')")
    op.get_bind().exec_driver_sql('CREATE TABLE model_call_log_default PARTITION OF model_call_log DEFAULT')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_model_updated_at BEFORE UPDATE ON "model" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS model_call_log_p2026_11")
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS model_call_log_p2026_12")
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS model_call_log_default")
    op.execute('DROP TABLE IF EXISTS "model_call_log" CASCADE')
    op.execute('DROP TABLE IF EXISTS "model" CASCADE')
