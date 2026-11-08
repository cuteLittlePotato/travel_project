"""Alembic autogenerate 的对象过滤规则。

单独成模块的原因：``env.py`` 依赖 Alembic 的运行时 ``context``，
只能在迁移环境中导入。而 ``scripts/check_model_drift.py`` 也需要同一套
过滤规则，因此把纯函数抽出来共用。
"""

from __future__ import annotations

#: 分区子表由 DDL 直接创建（PARTITION OF），ORM 无法表达，
#: 必须从 autogenerate 比较中排除，否则每次 check 都报告「应删除」
PARTITION_SUFFIXES = ("_default",)
PARTITION_MARKER = "_p2026_"


def include_object(
    obj: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object,
) -> bool:
    """autogenerate 的对象过滤钩子。

    :return: True 表示参与比较，False 表示跳过
    """
    if type_ == "table" and name:
        if name == "alembic_version":
            return False
        if name.endswith(PARTITION_SUFFIXES) or PARTITION_MARKER in name:
            return False
    return True
