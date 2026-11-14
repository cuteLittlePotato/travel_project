"""ORM 模型聚合入口。

**本文件只做导入，不定义任何模型。**

模型定义在各业务模块下：``app/modules/<module>/models.py``
（架构 §4.3，2026-11-08 确认）。Alembic 的 ``env.py`` 导入本文件即可
发现全部表；新增模块时在此登记一行。

规范（docs/rules/database-rules.md）：
- 主键统一 ``id``，类型 UUID（``UUIDPrimaryKeyMixin`` 提供）
- **禁止物理外键**：模型里不得出现外键约束或带外键参数的关联声明
- 表间关系通过逻辑关联字段（如 ``user_id``）维护，由应用层保证完整性

新增模型后的必做步骤（CLAUDE.md §5.1）：
    cd backend && uv run python scripts/check_model_drift.py --module <module>
    输出 ``[OK] model matches database DDL`` 才能继续写业务代码
"""

from __future__ import annotations

# ---------- M01 用户与账户 ----------
from app.modules.account.models import (
    Notification,
    OAuthBinding,
    User,
    UserProfile,
    UserSetting,
)

# ---------- M11 基础数据 ----------
from app.modules.catalog.models import (
    Activity,
    Attraction,
    AttractionCategory,
    AttractionCategoryRelation,
    Hotel,
    PopularityStat,
    Region,
    Restaurant,
    Transport,
)

# ---------- M12 模型管理 ----------
from app.modules.model_gateway.models import Model, ModelCallLog

# ---------- M15 系统管理 ----------
from app.modules.system.models import (
    AdminUser,
    AdminUserRole,
    OperationLog,
    Permission,
    Role,
    RolePermission,
    SiteSetting,
)

__all__ = [  # noqa: RUF022 - 按模块分组更易读，非字母序
    # M01
    "Notification",
    "OAuthBinding",
    "User",
    "UserProfile",
    "UserSetting",
    # M11
    "Activity",
    "Attraction",
    "AttractionCategory",
    "AttractionCategoryRelation",
    "Hotel",
    "PopularityStat",
    "Region",
    "Restaurant",
    "Transport",
    # M12
    "Model",
    "ModelCallLog",
    # M15
    "AdminUser",
    "AdminUserRole",
    "OperationLog",
    "Permission",
    "Role",
    "RolePermission",
    "SiteSetting",
]
