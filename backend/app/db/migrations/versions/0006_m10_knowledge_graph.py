"""M10 知识图谱

Revision ID: 0006_m10_knowledge_graph
Revises: 0005_m09_knowledge_base
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

revision: str = "0006_m10_knowledge_graph"
down_revision: str | None = "0005_m09_knowledge_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kg_person",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("alias", sa.String(200)),
        sa.Column("dynasty", sa.String(50)),
        sa.Column("occupation", sa.String(100)),
        sa.Column("birth_year", sa.Integer()),
        sa.Column("death_year", sa.Integer()),
        sa.Column("hometown", sa.String(100)),
        sa.Column("representative_works", postgresql.JSONB()),
        sa.Column("summary", sa.Text()),
        sa.Column("image_url", sa.String(500)),
        sa.Column("graph_sync_status", sa.String(20), nullable=False, server_default='synced'),
        sa.Column("graph_sync_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("graph_sync_status IN ('pending', 'synced', 'failed')", name="ck_kg_person_graph_sync_status"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "kg_person" IS \'知识图谱-历史人物\'')
    op.create_table(
        "kg_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("event_time", sa.String(100)),
        sa.Column("location", sa.String(200)),
        sa.Column("event_type", sa.String(50)),
        sa.Column("significance", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("graph_sync_status", sa.String(20), nullable=False, server_default='synced'),
        sa.Column("graph_sync_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("graph_sync_status IN ('pending', 'synced', 'failed')", name="ck_kg_event_graph_sync_status"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "kg_event" IS \'知识图谱-历史事件\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "kg_event"."event_time" IS \'发生时间，允许用朝代纪年表示（如「永乐十八年」），故用字符串\'')
    op.create_table(
        "kg_culture",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("culture_type", sa.String(50)),
        sa.Column("region", sa.String(100)),
        sa.Column("description", sa.Text()),
        sa.Column("image_url", sa.String(500)),
        sa.Column("graph_sync_status", sa.String(20), nullable=False, server_default='synced'),
        sa.Column("graph_sync_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("culture_type IN ('architecture', 'art', 'folklore', 'specialty')", name="ck_kg_culture_culture_type"),
        sa.CheckConstraint("graph_sync_status IN ('pending', 'synced', 'failed')", name="ck_kg_culture_graph_sync_status"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "kg_culture" IS \'知识图谱-文化元素\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "kg_culture"."culture_type" IS \'类型：architecture=建筑风格，art=艺术形式，folklore=民俗活动，specialty=地方特产\'')
    op.create_table(
        "kg_relation_type",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("cardinality", sa.String(20), nullable=False),
        sa.Column("source_types", postgresql.JSONB(), nullable=False),
        sa.Column("target_types", postgresql.JSONB(), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default='true'),
        sa.Column("description", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("cardinality IN ('one_to_one', 'many_to_many')", name="ck_kg_relation_type_cardinality"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "kg_relation_type" IS \'知识图谱-关系类型元数据\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "kg_relation_type"."cardinality" IS \'基数：one_to_one=不允许重复，many_to_many=允许重复\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "kg_relation_type"."source_types" IS \'允许的起始实体类型数组，如 ["attraction"]\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "kg_relation_type"."target_types" IS \'允许的目标实体类型数组，如 ["person"]\'')
    op.create_table(
        "featured_knowledge_graph",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("attraction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sort_weight", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "featured_knowledge_graph" IS \'发现页精选知识图谱（B端运营配置，控制展示与排序）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "featured_knowledge_graph"."attraction_id" IS \'被精选的景点，不可重复\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "featured_knowledge_graph"."sort_weight" IS \'展示排序权重，越大越靠前\'')
    op.create_index("idx_kgperson_name", "kg_person", ['name'])
    op.get_bind().exec_driver_sql('CREATE INDEX idx_kgperson_sync ON "kg_person" (graph_sync_status) WHERE graph_sync_status != \'synced\'')
    op.create_index("idx_kgevent_name", "kg_event", ['name'])
    op.get_bind().exec_driver_sql('CREATE INDEX idx_kgevent_sync ON "kg_event" (graph_sync_status) WHERE graph_sync_status != \'synced\'')
    op.create_index("idx_kgculture_type", "kg_culture", ['culture_type'])
    op.get_bind().exec_driver_sql('CREATE INDEX idx_kgculture_sync ON "kg_culture" (graph_sync_status) WHERE graph_sync_status != \'synced\'')
    op.create_index("uk_kgreltype_code", "kg_relation_type", ['code'], unique=True)
    op.create_index("uk_fkg_attraction", "featured_knowledge_graph", ['attraction_id'], unique=True)
    op.execute('CREATE INDEX idx_fkg_sort ON "featured_knowledge_graph" (sort_weight DESC)')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_kg_person_updated_at BEFORE UPDATE ON "kg_person" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_kg_event_updated_at BEFORE UPDATE ON "kg_event" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_kg_culture_updated_at BEFORE UPDATE ON "kg_culture" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS "featured_knowledge_graph" CASCADE')
    op.execute('DROP TABLE IF EXISTS "kg_relation_type" CASCADE')
    op.execute('DROP TABLE IF EXISTS "kg_culture" CASCADE')
    op.execute('DROP TABLE IF EXISTS "kg_event" CASCADE')
    op.execute('DROP TABLE IF EXISTS "kg_person" CASCADE')
