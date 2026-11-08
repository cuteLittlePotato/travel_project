"""M15 系统管理

Revision ID: 0013_m15_system
Revises: 0012_m13_quota
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

revision: str = "0013_m15_system"
down_revision: str | None = "0012_m13_quota"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("real_name", sa.String(50)),
        sa.Column("email", sa.String(100)),
        sa.Column("status", sa.String(20), nullable=False, server_default='active'),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_admin_user_status"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "admin_user" IS \'B端管理员账号\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "admin_user"."token_version" IS \'Token 版本号，登出/改密/禁用时自增，使所有已签发 Token 失效\'')
    op.create_table(
        "role",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("description", sa.String(200)),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default='false'),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "role" IS \'角色（当前内置超级管理员与普通用户，结构支持扩展）\'')
    op.create_table(
        "permission",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("module", sa.String(50), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("action IN ('create', 'read', 'update', 'delete', 'export', 'manage')", name="ck_permission_action"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "permission" IS \'权限项（模块 × 操作，细粒度）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "permission"."code" IS \'权限编码，如 catalog.attraction.delete\'')
    op.create_table(
        "role_permission",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "role_permission" IS \'角色权限关联\'')
    op.create_table(
        "admin_user_role",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "admin_user_role" IS \'管理员角色关联\'')
    op.create_table(
        "operation_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module", sa.String(50), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("target_type", sa.String(50)),
        sa.Column("target_id", postgresql.UUID(as_uuid=True)),
        sa.Column("detail", postgresql.JSONB()),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("user_agent", sa.String(500)),
        sa.Column("is_success", sa.Boolean(), nullable=False, server_default='true'),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("action IN ('create', 'update', 'delete', 'export', 'login', 'logout')", name="ck_operation_log_action"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "operation_log" IS \'操作日志（仅记录增删改与登录登出，不记录查询）\'')
    op.create_table(
        "site_setting",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("setting_key", sa.String(100), nullable=False),
        sa.Column("setting_value", postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.String(200)),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "site_setting" IS \'平台级配置（键值对）\'')
    op.create_index("uk_admin_username", "admin_user", ['username'], unique=True)
    op.create_index("uk_role_code", "role", ['code'], unique=True)
    op.create_index("uk_permission_code", "permission", ['code'], unique=True)
    op.create_index("idx_permission_module", "permission", ['module', 'action'])
    op.create_index("uk_role_perm", "role_permission", ['role_id', 'permission_id'], unique=True)
    op.create_index("idx_roleperm_role", "role_permission", ['role_id'])
    op.create_index("uk_admin_role", "admin_user_role", ['admin_user_id', 'role_id'], unique=True)
    op.create_index("idx_adminrole_admin", "admin_user_role", ['admin_user_id'])
    op.execute('CREATE INDEX idx_oplog_admin ON "operation_log" (admin_user_id, created_at DESC)')
    op.execute('CREATE INDEX idx_oplog_module ON "operation_log" (module, created_at DESC)')
    op.execute('CREATE INDEX idx_oplog_time ON "operation_log" (created_at DESC)')
    op.create_index("uk_setting_key", "site_setting", ['setting_key'], unique=True)
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_admin_user_updated_at BEFORE UPDATE ON "admin_user" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_role_updated_at BEFORE UPDATE ON "role" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_site_setting_updated_at BEFORE UPDATE ON "site_setting" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS "site_setting" CASCADE')
    op.execute('DROP TABLE IF EXISTS "operation_log" CASCADE')
    op.execute('DROP TABLE IF EXISTS "admin_user_role" CASCADE')
    op.execute('DROP TABLE IF EXISTS "role_permission" CASCADE')
    op.execute('DROP TABLE IF EXISTS "permission" CASCADE')
    op.execute('DROP TABLE IF EXISTS "role" CASCADE')
    op.execute('DROP TABLE IF EXISTS "admin_user" CASCADE')
