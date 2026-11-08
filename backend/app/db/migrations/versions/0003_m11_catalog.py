"""M11 基础数据

Revision ID: 0003_m11_catalog
Revises: 0002_m01_account
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

revision: str = "0003_m11_catalog"
down_revision: str | None = "0002_m01_account"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "region",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True)),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("cover_image_url", sa.String(500)),
        sa.Column("heat_score", sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column("sort_weight", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('level IN (1, 2)', name="ck_region_level"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "region" IS \'省市行政区划\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "region"."level" IS \'层级：1=省，2=市\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "region"."code" IS \'行政区划编码\'')
    op.create_table(
        "attraction_category",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("category_type", sa.String(20), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True)),
        sa.Column("description", sa.String(200)),
        sa.Column("sort_weight", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("category_type IN ('theme', 'level')", name="ck_attraction_category_category_type"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "attraction_category" IS \'景点分类字典（B端维护）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "attraction_category"."category_type" IS \'分类类型：theme=主题类型（历史人文/自然景色），level=等级称号（5A景区/世界遗产）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "attraction_category"."parent_id" IS \'上级分类，支持二级分类\'')
    op.create_table(
        "attraction",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("city_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("latitude", sa.Numeric(10, 7)),
        sa.Column("longitude", sa.Numeric(10, 7)),
        sa.Column("address", sa.String(255)),
        sa.Column("summary", sa.String(200)),
        sa.Column("description", sa.Text()),
        sa.Column("image_urls", postgresql.JSONB()),
        sa.Column("ticket_price", sa.Numeric(10, 2)),
        sa.Column("opening_hours", postgresql.JSONB()),
        sa.Column("visit_duration_minutes", sa.Integer()),
        sa.Column("best_seasons", postgresql.JSONB()),
        sa.Column("website", sa.String(500)),
        sa.Column("phone", sa.String(50)),
        sa.Column("traffic_guide", sa.Text()),
        sa.Column("base_popularity", sa.Numeric(10, 2), nullable=False, server_default='50'),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default='true'),
        sa.Column("sort_weight", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "attraction" IS \'景点信息\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "attraction"."base_popularity" IS \'基础热度权重（运营配置，0-100）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "attraction"."opening_hours" IS \'开放时间，如 {"mon":"09:00-17:00"}\'')
    op.create_table(
        "attraction_category_relation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("attraction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "attraction_category_relation" IS \'景点与分类的关联（多对多）\'')
    op.create_table(
        "restaurant",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("city_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cuisine_type", sa.String(50)),
        sa.Column("latitude", sa.Numeric(10, 7)),
        sa.Column("longitude", sa.Numeric(10, 7)),
        sa.Column("address", sa.String(255)),
        sa.Column("summary", sa.Text()),
        sa.Column("avg_cost", sa.Numeric(10, 2)),
        sa.Column("business_hours", postgresql.JSONB()),
        sa.Column("signature_dishes", postgresql.JSONB()),
        sa.Column("image_urls", postgresql.JSONB()),
        sa.Column("need_reservation", sa.Boolean(), nullable=False, server_default='false'),
        sa.Column("phone", sa.String(50)),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default='true'),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "restaurant" IS \'餐厅信息\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "restaurant"."avg_cost" IS \'人均消费（元）\'')
    op.create_table(
        "hotel",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("city_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("star_level", sa.String(20)),
        sa.Column("latitude", sa.Numeric(10, 7)),
        sa.Column("longitude", sa.Numeric(10, 7)),
        sa.Column("address", sa.String(255)),
        sa.Column("summary", sa.Text()),
        sa.Column("min_price", sa.Numeric(10, 2)),
        sa.Column("max_price", sa.Numeric(10, 2)),
        sa.Column("room_types", postgresql.JSONB()),
        sa.Column("facilities", postgresql.JSONB()),
        sa.Column("image_urls", postgresql.JSONB()),
        sa.Column("booking_url", sa.String(500)),
        sa.Column("phone", sa.String(50)),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default='true'),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "hotel" IS \'酒店信息\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "hotel"."star_level" IS \'星级：5星级/4星级/3星级/经济型/精品酒店/民宿\'')
    op.create_table(
        "transport",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("attraction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("transport_type", sa.String(50)),
        sa.Column("price", sa.Numeric(10, 2)),
        sa.Column("description", sa.Text()),
        sa.Column("operating_hours", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "transport" IS \'景区专属交通（观光车、索道等），城际交通不入库\'')
    op.create_table(
        "activity",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("cover_image_url", sa.String(500)),
        sa.Column("activity_type", sa.String(50)),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("city_id", postgresql.UUID(as_uuid=True)),
        sa.Column("attraction_id", postgresql.UUID(as_uuid=True)),
        sa.Column("detail_url", sa.String(500)),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default='true'),
        sa.Column("sort_weight", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("activity_type IN ('discount', 'festival', 'exhibition', 'other')", name="ck_activity_activity_type"),
        sa.CheckConstraint('end_date >= start_date', name="chk_activity_date"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "activity" IS \'旅游活动（发现页推荐用）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "activity"."activity_type" IS \'类型：discount=特惠，festival=节庆，exhibition=展览，other=其他\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "activity"."city_id" IS \'目标城市，NULL 表示全国性活动\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "activity"."attraction_id" IS \'关联景点，NULL 表示不限定\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "activity"."detail_url" IS \'活动详情页外部链接，价格等信息在此页面展示\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "activity"."id" IS \'活动状态（未开始/进行中/已结束）由 start_date、end_date 与当前时间实时计算，不单独存储\'')
    op.create_index("uk_region_code", "region", ['code'], unique=True)
    op.create_index("idx_region_parent_id", "region", ['parent_id'])
    op.create_index("idx_region_level", "region", ['level'])
    op.create_index("uk_attr_cat_type_name", "attraction_category", ['category_type', 'name'], unique=True)
    op.create_index("idx_attr_cat_type", "attraction_category", ['category_type', 'sort_weight'])
    op.create_index("idx_attr_cat_parent", "attraction_category", ['parent_id'])
    op.create_index("uk_attraction_name_city", "attraction", ['name', 'city_id'], unique=True)
    op.create_index("idx_attraction_city_id", "attraction", ['city_id'])
    op.execute('CREATE INDEX idx_attraction_published ON "attraction" (is_published, sort_weight DESC)')
    op.create_index("idx_attraction_geo", "attraction", ['latitude', 'longitude'])
    op.create_index("uk_attr_cat_rel", "attraction_category_relation", ['attraction_id', 'category_id'], unique=True)
    op.create_index("idx_attr_cat_rel_attraction", "attraction_category_relation", ['attraction_id'])
    op.create_index("idx_attr_cat_rel_category", "attraction_category_relation", ['category_id'])
    op.create_index("idx_restaurant_city_id", "restaurant", ['city_id'])
    op.create_index("idx_restaurant_cuisine", "restaurant", ['cuisine_type'])
    op.create_index("idx_restaurant_geo", "restaurant", ['latitude', 'longitude'])
    op.create_index("idx_hotel_city_id", "hotel", ['city_id'])
    op.create_index("idx_hotel_star", "hotel", ['star_level'])
    op.create_index("idx_hotel_geo", "hotel", ['latitude', 'longitude'])
    op.create_index("idx_transport_attraction_id", "transport", ['attraction_id'])
    op.execute('CREATE INDEX idx_activity_published ON "activity" (is_published, sort_weight DESC)')
    op.create_index("idx_activity_dates", "activity", ['start_date', 'end_date'])
    op.create_index("idx_activity_city", "activity", ['city_id'])
    op.create_index("idx_activity_attraction", "activity", ['attraction_id'])
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_region_updated_at BEFORE UPDATE ON "region" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_attraction_category_updated_at BEFORE UPDATE ON "attraction_category" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_attraction_updated_at BEFORE UPDATE ON "attraction" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_restaurant_updated_at BEFORE UPDATE ON "restaurant" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_hotel_updated_at BEFORE UPDATE ON "hotel" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_transport_updated_at BEFORE UPDATE ON "transport" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_activity_updated_at BEFORE UPDATE ON "activity" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS "activity" CASCADE')
    op.execute('DROP TABLE IF EXISTS "transport" CASCADE')
    op.execute('DROP TABLE IF EXISTS "hotel" CASCADE')
    op.execute('DROP TABLE IF EXISTS "restaurant" CASCADE')
    op.execute('DROP TABLE IF EXISTS "attraction_category_relation" CASCADE')
    op.execute('DROP TABLE IF EXISTS "attraction" CASCADE')
    op.execute('DROP TABLE IF EXISTS "attraction_category" CASCADE')
    op.execute('DROP TABLE IF EXISTS "region" CASCADE')
