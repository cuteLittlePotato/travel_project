"""统一地区字段为行政区划编码

Revision ID: 0016_m01_departure_city_code
Revises: 0015_m15_seed_permissions
Create Date: 2026-11-09

## 变更内容

``user_profile.departure_city``（VARCHAR(50)，城市**名称**）
→ ``user_profile.departure_city_code``（VARCHAR(20)，行政区划**编码**）

## 为什么

项目里有两处「地区」字段，格式不一致：

    user.region_code                      VARCHAR(20)  存编码
    user_profile.departure_city           VARCHAR(50)  存名称

名称会因运营在 B 端「省市管理」中改名而失效——用户设了「杭州市」，
运营改成「杭州」后这条偏好就再也匹配不上。编码（GB/T 2260）是稳定标识。

两个字段语义高度相似，统一为编码，避免：
    - 前端要为两种格式各写一套逻辑
    - 推荐时按名称匹配需要额外的名称→编码查询

## 数据迁移

已有的 ``departure_city`` 是自由文本，可能包含：
    - 标准城市名（如「北京市」）→ 可按 ``region.name`` 匹配并回填编码
    - 非标准写法（如「北京」「北京城区」）→ 匹配不上，置空

匹配不上的数据宁可置空，也不做模糊匹配——错误的编码比没有编码更糟：
用户会看到一个自己从未选过的城市。

## 降级

``downgrade`` 把编码还原成名称。编码在地区表中不存在时置空。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_m01_departure_city_code"
down_revision: str | None = "0015_m15_seed_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. 先加新列，允许为空
    op.add_column(
        "user_profile",
        sa.Column(
            "departure_city_code",
            sa.String(20),
            nullable=True,
            comment="默认出发城市编码（GB/T 2260），与 user.region_code 同一套格式",
        ),
    )

    # 2. 按城市名回填编码。只精确匹配，不做模糊匹配。
    conn.execute(
        sa.text(
            """
            UPDATE user_profile p
            SET departure_city_code = r.code
            FROM region r
            WHERE r.level = 2
              AND p.departure_city IS NOT NULL
              AND p.departure_city = r.name
            """
        )
    )

    # 3. 删除旧列
    op.drop_column("user_profile", "departure_city")


def downgrade() -> None:
    conn = op.get_bind()

    op.add_column(
        "user_profile",
        sa.Column("departure_city", sa.String(50), nullable=True),
    )

    conn.execute(
        sa.text(
            """
            UPDATE user_profile p
            SET departure_city = r.name
            FROM region r
            WHERE p.departure_city_code IS NOT NULL
              AND p.departure_city_code = r.code
            """
        )
    )

    op.drop_column("user_profile", "departure_city_code")
