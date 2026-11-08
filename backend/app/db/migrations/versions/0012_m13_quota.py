"""M13 额度

Revision ID: 0012_m13_quota
Revises: 0011_m12_model
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

revision: str = "0012_m13_quota"
down_revision: str | None = "0011_m12_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_quota",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quota_date", sa.Date(), nullable=False),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("token_used", sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "user_quota" IS \'用户额度（按用户×日期一行，自然日重置）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "user_quota"."call_count" IS \'当日已调用次数（Redis 实时计数，异步同步到此）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "user_quota"."token_used" IS \'当日已用 token\'')
    op.create_index("uk_quota_user_date", "user_quota", ['user_id', 'quota_date'], unique=True)
    op.create_index("idx_quota_date", "user_quota", ['quota_date'])
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_user_quota_updated_at BEFORE UPDATE ON "user_quota" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS "user_quota" CASCADE')
