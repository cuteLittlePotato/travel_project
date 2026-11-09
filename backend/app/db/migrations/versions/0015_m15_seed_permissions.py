"""M15-T02 初始化角色与权限项

Revision ID: 0015_m15_seed_permissions
Revises: 0014_m17_user_event
Create Date: 2026-11-08

**数据迁移**，不涉及表结构变更。

写入内容：
    1. 两个内置角色：``super_admin``（超级管理员）/ ``normal``（普通管理员）
    2. 全部权限项（按「模块 × 资源 × 操作」细粒度，见
       ``app/modules/system/permissions.py``）
    3. 超级管理员角色的全部权限关联

幂等性（DoD 要求）：
    全部使用 ``ON CONFLICT DO NOTHING``。重复执行不会报错，
    也不会覆盖已存在的记录——**不覆盖**是有意的：运营可能在线上
    调整过角色描述或权限分配，重跑迁移不应把他们的改动冲掉。

**硬编码 UUID**：种子数据的 ID 写死，不是随机生成。
理由是两个角色在代码里被直接引用（``ROLE_SUPER_ADMIN``），
每次重跑都换 ID 会让权限关联对不上。写死的 UUID 也让
「权限项 ID 在开发/测试/生产之间一致」，便于跨环境排查。

降级策略：只删除本次写入的种子数据，按 ``is_builtin`` 与
``permission`` 全表清理。若线上已基于这些角色配置了管理员，
``downgrade`` 会连带删除关联——这是数据迁移降级的固有风险，
生产环境不建议降级。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0015_m15_seed_permissions"
down_revision: str | None = "0014_m17_user_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: 内置角色的固定 UUID。写死而非生成，保证跨环境一致、
#: 且重跑迁移时权限关联仍能对上。
SUPER_ADMIN_ROLE_ID = "00000000-0000-4000-8000-000000000001"
NORMAL_ROLE_ID = "00000000-0000-4000-8000-000000000002"

#: 权限项 UUID 由编码确定性生成——同一个 code 在任何环境都得到同一个 ID。
#: 这样增量迁移可以直接按 code 定位权限项，不必先查库。
_PERMISSION_UUID_NAMESPACE = "00000000-0000-4000-8000-0000000000ff"


def _permission_id(code: str) -> str:
    """由权限编码确定性推导 UUID。

    用 ``uuid5`` 而非 ``uuid4``：同一 code 永远得到同一 ID，
    增量迁移与跨环境排查都依赖这个稳定性。
    """
    import uuid

    return str(uuid.uuid5(uuid.UUID(_PERMISSION_UUID_NAMESPACE), code))


def _seed_roles(conn: Any) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO role (id, code, name, description, is_builtin, created_at, updated_at)
            VALUES (:id, :code, :name, :description, TRUE, NOW(), NOW())
            ON CONFLICT (code) DO NOTHING
            """
        ),
        [
            {
                "id": SUPER_ADMIN_ROLE_ID,
                "code": "super_admin",
                "name": "超级管理员",
                "description": "拥有全部权限，不可删除",
            },
            {
                "id": NORMAL_ROLE_ID,
                "code": "normal",
                "name": "普通管理员",
                "description": "无 B 端管理权限，仅可登录查看（初始状态，需手动授权）",
            },
        ],
    )


def _seed_permissions(conn: Any) -> None:
    """写入全部权限项。

    从 ``app.modules.system.permissions`` 导入而不是在本文件里
    重复列一份——清单只有一处定义，改接口时只改那里。
    """
    from app.modules.system.permissions import PERMISSION_DEFINITIONS

    rows = [
        {
            "id": _permission_id(item.code),
            "code": item.code,
            "module": item.module,
            "action": item.action,
            "name": item.name,
            "description": item.description,
        }
        for item in PERMISSION_DEFINITIONS
    ]

    conn.execute(
        sa.text(
            """
            INSERT INTO permission (id, code, module, action, name, description, created_at)
            VALUES (:id, :code, :module, :action, :name, :description, NOW())
            ON CONFLICT (code) DO NOTHING
            """
        ),
        rows,
    )


def _grant_all_to_super_admin(conn: Any) -> None:
    """超级管理员拥有全部权限（DoD：关联数 = 权限总数）。

    用 ``SELECT`` 从库里取权限 ID 而非用 ``_permission_id`` 逐个推导：
    库里可能存在本迁移之外新增的权限项（后续增量迁移写入的），
    超级管理员同样应该拥有它们。
    """
    conn.execute(
        sa.text(
            """
            INSERT INTO role_permission (id, role_id, permission_id, created_at)
            SELECT gen_random_uuid(), :role_id, p.id, NOW()
            FROM permission p
            ON CONFLICT (role_id, permission_id) DO NOTHING
            """
        ),
        {"role_id": SUPER_ADMIN_ROLE_ID},
    )


def upgrade() -> None:
    conn = op.get_bind()

    _seed_roles(conn)
    _seed_permissions(conn)
    _grant_all_to_super_admin(conn)


def downgrade() -> None:
    conn = op.get_bind()

    # 先删关联（虽然没有物理外键，仍按依赖顺序）
    conn.execute(
        sa.text(
            """
            DELETE FROM role_permission
            WHERE role_id IN (SELECT id FROM role WHERE is_builtin = TRUE)
            """
        )
    )
    # 只删内置角色；运营自建的角色保留
    conn.execute(sa.text("DELETE FROM role WHERE is_builtin = TRUE"))
    # 权限项全是种子数据，全表清空
    conn.execute(sa.text("DELETE FROM permission"))
