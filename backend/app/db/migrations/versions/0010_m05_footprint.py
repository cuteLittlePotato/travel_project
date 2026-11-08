"""M05 足迹

Revision ID: 0010_m05_footprint
Revises: 0009_m04_plan
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

revision: str = "0010_m05_footprint"
down_revision: str | None = "0009_m04_plan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "footprint",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attraction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visit_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("trip_plan_id", postgresql.UUID(as_uuid=True)),
        sa.Column("rating", sa.SmallInteger()),
        sa.Column("review", sa.Text()),
        sa.Column("image_urls", postgresql.JSONB()),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default='true'),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("source IN ('auto_from_plan', 'manual')", name="ck_footprint_source"),
        sa.CheckConstraint('rating BETWEEN 1 AND 5', name="ck_footprint_rating"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "footprint" IS \'用户足迹\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "footprint"."source" IS \'来源：auto_from_plan=计划完成自动生成，manual=手动添加\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "footprint"."is_public" IS \'是否公开，供发现页精选游记使用\'')
    op.execute('CREATE INDEX idx_footprint_user ON "footprint" (user_id, visit_date DESC)')
    op.create_index("idx_footprint_attraction", "footprint", ['attraction_id'])
    op.execute('CREATE INDEX idx_footprint_public ON "footprint" (is_public, created_at DESC)')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_footprint_updated_at BEFORE UPDATE ON "footprint" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS "footprint" CASCADE')
