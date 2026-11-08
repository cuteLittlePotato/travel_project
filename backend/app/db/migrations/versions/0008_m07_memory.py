"""M07 记忆

Revision ID: 0008_m07_memory
Revises: 0007_m03_chat
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

revision: str = "0008_m07_memory"
down_revision: str | None = "0007_m03_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_long_term",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_type", sa.String(50), nullable=False),
        sa.Column("memory_key", sa.String(100), nullable=False),
        sa.Column("memory_value", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default='1.000'),
        sa.Column("source", sa.String(50)),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("memory_type IN ('preference', 'behavior', 'context')", name="ck_memory_long_term_memory_type"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "memory_long_term" IS \'长期记忆（系统学习的用户偏好，区别于 user_profile 的显式设置）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "memory_long_term"."confidence" IS \'置信度（0-1），与 last_active_at 共同参与衰减计算\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "memory_long_term"."source" IS \'来源：conversation/footprint/plan/rating\'')
    op.create_index("uk_memory_user_key", "memory_long_term", ['user_id', 'memory_type', 'memory_key'], unique=True)
    op.create_index("idx_memory_user", "memory_long_term", ['user_id'])
    op.execute('CREATE INDEX idx_memory_active ON "memory_long_term" (last_active_at DESC)')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_memory_long_term_updated_at BEFORE UPDATE ON "memory_long_term" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS "memory_long_term" CASCADE')
