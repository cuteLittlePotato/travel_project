"""M04 旅游计划

Revision ID: 0009_m04_plan
Revises: 0008_m07_memory
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

revision: str = "0009_m04_plan"
down_revision: str | None = "0008_m07_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trip_plan",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("destination_city_id", postgresql.UUID(as_uuid=True)),
        sa.Column("destination_text", sa.String(200), nullable=False),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date()),
        sa.Column("day_count", sa.Integer()),
        sa.Column("budget_per_person", sa.Numeric(12, 2)),
        sa.Column("people_count", sa.Integer(), nullable=False, server_default='1'),
        sa.Column("status", sa.String(20), nullable=False, server_default='planning'),
        sa.Column("selected_candidate_id", postgresql.UUID(as_uuid=True)),
        sa.Column("edit_lock_user", postgresql.UUID(as_uuid=True)),
        sa.Column("edit_lock_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('planning', 'pending', 'ongoing', 'completed', 'cancelled')", name="ck_trip_plan_status"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "trip_plan" IS \'旅游计划\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "trip_plan"."destination_text" IS \'目的地文本，支持「北京+天津」这类多目的地\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "trip_plan"."status" IS \'状态：planning=规划中，pending=待进行，ongoing=进行中，completed=已完成，cancelled=已取消\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "trip_plan"."edit_lock_user" IS \'编辑锁持有者，同一行程同时只允许一个会话编辑\'')
    op.create_table(
        "plan_candidate",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_type", sa.String(20), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("total_budget", sa.Numeric(12, 2), nullable=False),
        sa.Column("attraction_count", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("accommodation_level", sa.String(50)),
        sa.Column("transport_level", sa.String(50)),
        sa.Column("dining_level", sa.String(50)),
        sa.Column("recommend_score", sa.Numeric(4, 2)),
        sa.Column("is_selected", sa.Boolean(), nullable=False, server_default='false'),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default='true'),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("generated_by_session", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("candidate_type IN ('economy', 'standard', 'comfort', 'custom')", name="ck_plan_candidate_candidate_type"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "plan_candidate" IS \'方案候选（未选中方案保留为备选）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "plan_candidate"."candidate_type" IS \'方案类型：economy=经济型，standard=标准型，comfort=舒适型，custom=自定义\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "plan_candidate"."content" IS \'方案完整 JSON 快照，用于精确回放\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "plan_candidate"."is_active" IS \'是否为当前生效方案，false 表示备选\'')
    op.create_table(
        "plan_day",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date()),
        sa.Column("budget_breakdown", postgresql.JSONB()),
        sa.Column("summary", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "plan_day" IS \'计划日程（挂在方案下，因不同方案天数安排可能不同）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "plan_day"."budget_breakdown" IS \'当日预算明细，如 {"ticket":420,"dining":850}\'')
    op.create_table(
        "plan_activity",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_day_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_type", sa.String(20), nullable=False),
        sa.Column("start_time", sa.Time()),
        sa.Column("end_time", sa.Time()),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("attraction_id", postgresql.UUID(as_uuid=True)),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True)),
        sa.Column("hotel_id", postgresql.UUID(as_uuid=True)),
        sa.Column("cost", sa.Numeric(10, 2)),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("activity_type IN ('attraction', 'dining', 'transport', 'accommodation', 'rest')", name="ck_plan_activity_activity_type"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "plan_activity" IS \'行程活动\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "plan_activity"."activity_type" IS \'活动类型：attraction=景点，dining=餐饮，transport=交通，accommodation=住宿，rest=休息\'')
    op.execute('CREATE INDEX idx_tripplan_user_status ON "trip_plan" (user_id, status, created_at DESC)')
    op.create_index("idx_tripplan_status_dates", "trip_plan", ['status', 'start_date', 'end_date'])
    op.create_index("idx_tripplan_destination", "trip_plan", ['destination_city_id'])
    op.execute('CREATE INDEX idx_plancand_plan ON "plan_candidate" (plan_id, is_active, created_at DESC)')
    op.create_index("idx_plancand_selected", "plan_candidate", ['plan_id', 'is_selected'])
    op.create_index("uk_planday_cand_day", "plan_day", ['candidate_id', 'day_number'], unique=True)
    op.create_index("idx_planday_plan", "plan_day", ['plan_id'])
    op.create_index("idx_planact_day", "plan_activity", ['plan_day_id', 'sort_order'])
    op.create_index("idx_planact_attraction", "plan_activity", ['attraction_id'])
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_trip_plan_updated_at BEFORE UPDATE ON "trip_plan" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_plan_candidate_updated_at BEFORE UPDATE ON "plan_candidate" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_plan_day_updated_at BEFORE UPDATE ON "plan_day" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_plan_activity_updated_at BEFORE UPDATE ON "plan_activity" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS "plan_activity" CASCADE')
    op.execute('DROP TABLE IF EXISTS "plan_day" CASCADE')
    op.execute('DROP TABLE IF EXISTS "plan_candidate" CASCADE')
    op.execute('DROP TABLE IF EXISTS "trip_plan" CASCADE')
