"""ORM 模型导出入口。

Alembic 的 ``env.py`` 在此统一导入，autogenerate 才能发现全部表。
新增模型时**必须**在本文件登记，否则 ``alembic revision --autogenerate``
会漏掉对应的表。

按模块划分的模型文件直接放在各自业务模块下（``app/modules/<module>/models.py``），
此处只做聚合导入，不在此定义任何模型。

规范提醒（docs/rules/database-rules.md）：
- 主键统一 ``id``，类型 UUID（由 ``UUIDPrimaryKeyMixin`` 提供）
- **禁止物理外键**：模型里不得出现任何外键约束或带外键参数的关联声明
- 表间关系通过逻辑关联字段（如 ``user_id``）维护，由应用层保证完整性

当前状态：M0-T02 阶段尚无业务表，模型在 M01 起的各模块任务中逐步加入。
"""

from __future__ import annotations

__all__: list[str] = []

# 后续模型登记示例（模块任务完成后取消注释）：
# from app.modules.account.models import OAuthBinding, User, UserProfile, UserSetting
# from app.modules.attraction.models import Attraction, AttractionCategory
