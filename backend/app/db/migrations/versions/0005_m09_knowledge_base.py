"""M09 知识库

Revision ID: 0005_m09_knowledge_base
Revises: 0004_popularity
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

revision: str = "0005_m09_knowledge_base"
down_revision: str | None = "0004_popularity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_base",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("icon", sa.String(50)),
        sa.Column("capacity_gb", sa.Numeric(10, 2), nullable=False, server_default='5'),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column("chunk_size", sa.Integer(), nullable=False, server_default='1024'),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False, server_default='100'),
        sa.Column("separator_config", postgresql.JSONB(), nullable=False),
        sa.Column("retrieval_top_k", sa.Integer(), nullable=False, server_default='5'),
        sa.Column("retrieval_threshold", sa.Numeric(4, 3), nullable=False, server_default='0.500'),
        sa.Column("embedding_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rerank_model_id", postgresql.UUID(as_uuid=True)),
        sa.Column("permission_scope", sa.String(20), nullable=False, server_default='all'),
        sa.Column("rebuild_status", sa.String(20), nullable=False, server_default='normal'),
        sa.Column("doc_count", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("permission_scope IN ('all', 'specific')", name="ck_knowledge_base_permission_scope"),
        sa.CheckConstraint("rebuild_status IN ('normal', 'pending_rebuild', 'rebuilding')", name="ck_knowledge_base_rebuild_status"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "knowledge_base" IS \'RAG 知识库\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "knowledge_base"."separator_config" IS \'分隔符配置数组，含启用状态与优先级\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "knowledge_base"."retrieval_top_k" IS \'检索返回切片数，平台默认 5\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "knowledge_base"."retrieval_threshold" IS \'相似度阈值，平台默认 0.5\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "knowledge_base"."rebuild_status" IS \'非 normal 时该知识库暂停参与检索\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "knowledge_base"."doc_count" IS \'文档数（冗余字段，便于列表展示）\'')
    op.create_table(
        "kb_document",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(20), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("source_url", sa.String(1000)),
        sa.Column("process_status", sa.String(20), nullable=False, server_default='queued'),
        sa.Column("process_progress", sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column("queue_position", sa.Integer()),
        sa.Column("error_message", sa.Text()),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("markdown_content", sa.Text()),
        sa.Column("chunk_count", sa.Integer()),
        sa.Column("page_count", sa.Integer()),
        sa.Column("indexed_meta", postgresql.JSONB()),
        sa.Column("es_indexed", sa.Boolean(), nullable=False, server_default='false'),
        sa.Column("milvus_indexed", sa.Boolean(), nullable=False, server_default='false'),
        sa.Column("task_id", sa.String(100)),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("process_status IN ('queued', 'parsing', 'chunking', 'embedding', 'success', 'failed')", name="ck_kb_document_process_status"),
        sa.CheckConstraint('process_progress BETWEEN 0 AND 100', name="ck_kb_document_process_progress"),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "kb_document" IS \'知识库文档\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "kb_document"."process_status" IS \'处理状态：queued=排队，parsing=解析中，chunking=切分中，embedding=向量化中，success=完成，failed=失败\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "kb_document"."indexed_meta" IS \'入库时的切分配置快照，用于识别旧参数文档\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "kb_document"."storage_key" IS \'MinIO 中的对象键\'')
    op.create_table(
        "kb_chunk",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading_path", sa.String(500)),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("milvus_vector_id", sa.String(100)),
        sa.Column("es_doc_id", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.get_bind().exec_driver_sql('COMMENT ON TABLE "kb_chunk" IS \'文档切片（PG 为源数据，Milvus 存向量，ES 存索引副本）\'')
    op.get_bind().exec_driver_sql('COMMENT ON COLUMN "kb_chunk"."heading_path" IS \'标题路径，如「第三章 > 3.2 太和殿」\'')
    op.create_index("idx_kb_embedding_model", "knowledge_base", ['embedding_model_id'])
    op.create_index("idx_kb_rerank_model", "knowledge_base", ['rerank_model_id'])
    op.create_index("idx_kb_rebuild_status", "knowledge_base", ['rebuild_status'])
    op.execute('CREATE INDEX idx_kbdoc_kb_id ON "kb_document" (knowledge_base_id, created_at DESC)')
    op.create_index("idx_kbdoc_status", "kb_document", ['process_status'])
    op.create_index("idx_kbdoc_task", "kb_document", ['task_id'])
    op.create_index("uk_kbchunk_doc_index", "kb_chunk", ['document_id', 'chunk_index'], unique=True)
    op.create_index("idx_kbchunk_kb_id", "kb_chunk", ['knowledge_base_id'])
    op.create_index("idx_kbchunk_milvus", "kb_chunk", ['milvus_vector_id'])
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_knowledge_base_updated_at BEFORE UPDATE ON "knowledge_base" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')
    op.get_bind().exec_driver_sql('CREATE TRIGGER trg_kb_document_updated_at BEFORE UPDATE ON "kb_document" FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS "kb_chunk" CASCADE')
    op.execute('DROP TABLE IF EXISTS "kb_document" CASCADE')
    op.execute('DROP TABLE IF EXISTS "knowledge_base" CASCADE')
