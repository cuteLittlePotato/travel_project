"""M03 对话 / M06 Agent

Revision ID: 0007_m03_chat
Revises: 0006_m10_knowledge_graph
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

revision: str = "0007_m03_chat"
down_revision: str | None = "0006_m10_knowledge_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(200), nullable=False, server_default='新对话'),
        sa.Column("current_model_id", postgresql.UUID(as_uuid=True)),
        sa.Column("current_intent", sa.String(50)),
        sa.Column("flow_state", sa.String(50)),
        sa.Column("working_memory", postgresql.JSONB()),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "chat_session" IS \'对话会话\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "chat_session"."current_model_id" IS \'会话级模型切换，新会话恢复平台默认\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "chat_session"."working_memory" IS \'工作记忆：候选景点、已生成方案、调整历史\'')
    op.create_table(
        "chat_message",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(20), nullable=False, server_default='text'),
        sa.Column("tool_calls", postgresql.JSONB()),
        sa.Column("citations", postgresql.JSONB()),
        sa.Column("model_id", postgresql.UUID(as_uuid=True)),
        sa.Column("token_input", sa.Integer()),
        sa.Column("token_output", sa.Integer()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('user', 'assistant', 'system', 'tool')", name="ck_chat_message_role"),
        sa.CheckConstraint("content_type IN ('text', 'markdown', 'plan_card', 'clarify_options')", name="ck_chat_message_content_type"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "chat_message" IS \'对话消息\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "chat_message"."content_type" IS \'内容类型：plan_card=方案卡片，clarify_options=意图澄清选项\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "chat_message"."tool_calls" IS \'工具调用轨迹\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "chat_message"."citations" IS \'引用来源\'')
    op.create_table(
        "chat_pending_interaction",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("interaction_type", sa.String(50), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default='pending'),
        sa.Column("answer", postgresql.JSONB()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("interaction_type IN ('requirements', 'plan_selection', 'intent_clarify', 'adjustment_confirm')", name="ck_chat_pending_interaction_interaction_type"),
        sa.CheckConstraint("status IN ('pending', 'answered', 'expired', 'cancelled')", name="ck_chat_pending_interaction_status"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "chat_pending_interaction" IS \'待处理的用户交互（SSE 中断时的选项，落库保证连接断开后可恢复）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "chat_pending_interaction"."interaction_type" IS \'交互类型：requirements=需求收集，plan_selection=方案选择，intent_clarify=意图澄清，adjustment_confirm=调整确认\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "chat_pending_interaction"."payload" IS \'交互内容：选项列表、缺失字段说明、自定义输入提示等\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "chat_pending_interaction"."answer" IS \'用户的选择结果\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "chat_pending_interaction"."expires_at" IS \'过期时间，超时后标记为 expired\'')
    op.create_table(
        "agent_checkpoint",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", sa.String(100), nullable=False),
        sa.Column("checkpoint_id", sa.String(100), nullable=False),
        sa.Column("parent_checkpoint_id", sa.String(100)),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column("metadata", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "agent_checkpoint" IS \'LangGraph 检查点，用于中断恢复\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "agent_checkpoint"."state" IS \'LangGraph 图状态快照\'')
    op.execute('CREATE INDEX idx_chatsession_user ON "chat_session" (user_id, last_active_at DESC)')
    op.execute('CREATE INDEX idx_chatsession_active ON "chat_session" (last_active_at DESC)')
    op.execute('CREATE INDEX idx_chatmsg_session ON "chat_message" (session_id, created_at ASC)')
    op.execute('CREATE INDEX idx_chatmsg_created ON "chat_message" (created_at DESC)')
    op.create_index("idx_cpi_session", "chat_pending_interaction", ['session_id', 'status'])
    op.get_bind().exec_driver_sql('CREATE INDEX idx_cpi_pending ON "chat_pending_interaction" (status, created_at DESC) WHERE status = \'pending\'')
    op.get_bind().exec_driver_sql('CREATE UNIQUE INDEX uk_cpi_session_pending ON "chat_pending_interaction" (session_id) WHERE status = \'pending\'')
    op.execute('CREATE INDEX idx_agentcp_thread ON "agent_checkpoint" (thread_id, created_at DESC)')
    op.create_index("uk_agentcp_thread_checkpoint", "agent_checkpoint", ['thread_id', 'checkpoint_id'], unique=True)
    op.create_index("idx_agentcp_session", "agent_checkpoint", ['session_id'])
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_chat_session_updated_at BEFORE UPDATE ON "chat_session" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS "agent_checkpoint" CASCADE')
    op.execute('DROP TABLE IF EXISTS "chat_pending_interaction" CASCADE')
    op.execute('DROP TABLE IF EXISTS "chat_message" CASCADE')
    op.execute('DROP TABLE IF EXISTS "chat_session" CASCADE')
