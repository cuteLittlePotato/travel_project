"""0001 baseline - 扩展与公共函数

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-08

本迁移只安装扩展与触发器函数，不建业务表。
业务表按模块拆分在 0002 起的迁移文件中。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: updated_at 自动更新函数。所有含 updated_at 列的表共用
TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    # pg_trgm：模糊搜索与相似度匹配（regions / attractions 的名称检索）
    op.get_bind().exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.get_bind().exec_driver_sql(TRIGGER_FUNCTION)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP FUNCTION IF EXISTS trigger_set_updated_at()")
    # 扩展不主动删除：可能被其他库对象依赖
