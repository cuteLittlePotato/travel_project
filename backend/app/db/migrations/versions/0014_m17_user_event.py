"""M17 埋点

Revision ID: 0014_m17_user_event
Revises: 0013_m15_system
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

revision: str = "0014_m17_user_event"
down_revision: str | None = "0013_m15_system"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("target_type", sa.String(50)),
        sa.Column("target_id", postgresql.UUID(as_uuid=True)),
        sa.Column("session_id", postgresql.UUID(as_uuid=True)),
        sa.Column("metadata", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        postgresql_partition_by="RANGE (created_at)",
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "user_event" IS \'用户行为埋点（按月分区）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "user_event"."event_type" IS \'事件类型：view/click/share/create_plan/complete_plan/chat_send/graph_view\'')
    op.execute('CREATE INDEX idx_uevent_user_time ON "user_event" (user_id, created_at DESC)')
    op.execute('CREATE INDEX idx_uevent_type_time ON "user_event" (event_type, created_at DESC)')
    op.create_index("idx_uevent_target", "user_event", ['target_type', 'target_id'])
    op.get_bind().exec_driver_sql("CREATE TABLE user_event_p2026_11 PARTITION OF user_event FOR VALUES FROM ('2026-11-01') TO ('2026-12-01')")
    op.get_bind().exec_driver_sql("CREATE TABLE user_event_p2026_12 PARTITION OF user_event FOR VALUES FROM ('2026-12-01') TO ('2027-01-01')")
    op.get_bind().exec_driver_sql('CREATE TABLE user_event_default PARTITION OF user_event DEFAULT')


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS user_event_p2026_11")
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS user_event_p2026_12")
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS user_event_default")
    op.execute('DROP TABLE IF EXISTS "user_event" CASCADE')
