"""热度统计

Revision ID: 0004_popularity
Revises: 0003_m11_catalog
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

revision: str = "0004_popularity"
down_revision: str | None = "0003_m11_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "popularity_stat",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("attraction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("view_count", sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column("click_count", sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column("plan_count", sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column("rating_sum", sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("behavior_score", sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column("final_popularity", sa.Numeric(10, 2), nullable=False, server_default='50'),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "popularity_stat" IS \'景点热度统计\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "popularity_stat"."behavior_score" IS \'用户行为得分（0-100）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "popularity_stat"."final_popularity" IS \'最终热度 = base_popularity * 0.6 + behavior_score * 0.4\'')
    op.create_index("uk_popularity_attraction", "popularity_stat", ['attraction_id'], unique=True)
    op.execute('CREATE INDEX idx_popularity_final ON "popularity_stat" (final_popularity DESC)')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_popularity_stat_updated_at BEFORE UPDATE ON "popularity_stat" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS "popularity_stat" CASCADE')
