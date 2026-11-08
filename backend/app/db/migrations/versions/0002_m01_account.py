"""M01 用户与账户

Revision ID: 0002_m01_account
Revises: 0001_baseline
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

revision: str = "0002_m01_account"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("nickname", sa.String(50), nullable=False),
        sa.Column("avatar_url", sa.String(500)),
        sa.Column("gender", sa.String(10)),
        sa.Column("region_code", sa.String(20)),
        sa.Column("status", sa.String(20), nullable=False, server_default='active'),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("gender IN ('male', 'female', 'secret')", name="ck_user_gender"),
        sa.CheckConstraint("status IN ('active', 'banned', 'deleted')", name="ck_user_status"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "user" IS \'用户主表\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "user"."status" IS \'账号状态：active=正常，banned=封禁，deleted=已注销\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "user"."token_version" IS \'Token 版本号，登出/改密/封禁时自增，使所有已签发 Token 失效（全端登出）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "user"."region_code" IS \'常驻地区行政区划编码\'')
    op.create_table(
        "oauth_binding",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("provider_uid", sa.String(200), nullable=False),
        sa.Column("credential", sa.String(255)),
        sa.Column("extra_data", postgresql.JSONB()),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default='false'),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("provider IN ('phone', 'email', 'wechat', 'alipay', 'weibo')", name="ck_oauth_binding_provider"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "oauth_binding" IS \'登录方式绑定表\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "oauth_binding"."provider_uid" IS \'第三方唯一标识：手机号、邮箱、openid 等\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "oauth_binding"."credential" IS \'密码哈希，仅 phone/email 方式使用（bcrypt）\'')
    op.create_table(
        "user_profile",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("travel_types", postgresql.JSONB()),
        sa.Column("travel_styles", postgresql.JSONB()),
        sa.Column("budget_level", sa.String(20)),
        sa.Column("companion_type", sa.String(20)),
        sa.Column("preferred_seasons", postgresql.JSONB()),
        sa.Column("departure_city", sa.String(50)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("budget_level IN ('economy', 'moderate', 'comfortable', 'luxury')", name="ck_user_profile_budget_level"),
        sa.CheckConstraint("companion_type IN ('solo', 'couple', 'family', 'friends')", name="ck_user_profile_companion_type"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "user_profile" IS \'用户偏好档案（用户显式设置）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "user_profile"."travel_types" IS \'旅游类型偏好数组，如 ["历史人文","自然风光"]\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "user_profile"."budget_level" IS \'预算等级：economy=经济，moderate=中等，comfortable=舒适，luxury=豪华\'')
    op.create_table(
        "user_setting",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_visibility", sa.String(20), nullable=False, server_default='public'),
        sa.Column("footprint_visibility", sa.String(20), nullable=False, server_default='public'),
        sa.Column("plan_visibility", sa.String(20), nullable=False, server_default='public'),
        sa.Column("allow_recommendation", sa.Boolean(), nullable=False, server_default='true'),
        sa.Column("allow_notification", sa.Boolean(), nullable=False, server_default='true'),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("profile_visibility IN ('public', 'friends', 'private')", name="ck_user_setting_profile_visibility"),
        sa.CheckConstraint("footprint_visibility IN ('public', 'friends', 'private')", name="ck_user_setting_footprint_visibility"),
        sa.CheckConstraint("plan_visibility IN ('public', 'friends', 'private')", name="ck_user_setting_plan_visibility"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "user_setting" IS \'用户隐私与通知设置\'')
    op.create_table(
        "notification",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("related_type", sa.String(50)),
        sa.Column("related_id", postgresql.UUID(as_uuid=True)),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default='false'),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("notification_type IN ('plan_starting', 'plan_ended', 'system')", name="ck_notification_notification_type"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "notification" IS \'站内通知\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "notification"."notification_type" IS \'通知类型：plan_starting=计划即将开始，plan_ended=计划已结束（提醒确认完成），system=系统通知\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "notification"."related_type" IS \'关联对象类型：plan / footprint / system\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "notification"."related_id" IS \'关联对象 ID，点击通知可跳转到对应页面\'')
    op.create_index("uk_user_username", "user", ['username'], unique=True)
    op.create_index("idx_user_status", "user", ['status'])
    op.execute('CREATE INDEX idx_user_created_at ON "user" (created_at DESC)')
    op.create_index("uk_oauth_provider_uid", "oauth_binding", ['provider', 'provider_uid'], unique=True)
    op.create_index("idx_oauth_user_id", "oauth_binding", ['user_id'])
    op.create_index("uk_user_profile_user_id", "user_profile", ['user_id'], unique=True)
    op.create_index("uk_user_setting_user_id", "user_setting", ['user_id'], unique=True)
    op.execute('CREATE INDEX idx_notification_user ON "notification" (user_id, created_at DESC)')
    op.create_index("idx_notification_unread", "notification", ['user_id', 'is_read'])
    op.execute('CREATE INDEX idx_notification_type ON "notification" (notification_type, created_at DESC)')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_user_updated_at BEFORE UPDATE ON "user" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_user_profile_updated_at BEFORE UPDATE ON "user_profile" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_user_setting_updated_at BEFORE UPDATE ON "user_setting" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS "notification" CASCADE')
    op.execute('DROP TABLE IF EXISTS "user_setting" CASCADE')
    op.execute('DROP TABLE IF EXISTS "user_profile" CASCADE')
    op.execute('DROP TABLE IF EXISTS "oauth_binding" CASCADE')
    op.execute('DROP TABLE IF EXISTS "user" CASCADE')
