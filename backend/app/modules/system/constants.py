"""M15 系统管理的枚举与常量。

与 ``scripts/sql/schema.sql`` 的 CHECK 约束一一对应。
"""

from __future__ import annotations

from enum import StrEnum


class AdminStatus(StrEnum):
    """管理员状态（``admin_user.status``）。"""

    ACTIVE = "active"
    DISABLED = "disabled"


class PermissionAction(StrEnum):
    """权限操作（``permission.action``）。

    六个动作覆盖 B 端全部操作类型：
        - ``create`` / ``read`` / ``update`` / ``delete``：常规 CRUD
        - ``export``：导出（独立于 read——能看≠能导出全部）
        - ``manage``：管理类操作（如启停、重算），粒度介于 update 与 delete 之间
    """

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    EXPORT = "export"
    MANAGE = "manage"


class OperationAction(StrEnum):
    """操作日志动作（``operation_log.action``）。

    **只记录增删改与登录登出，不记录查询**——查询量大，记下来
    反而淹没真正需要审计的写操作（DDL 注释明确该取舍）。
    """

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    EXPORT = "export"
    LOGIN = "login"
    LOGOUT = "logout"


#: 内置角色编码（M15-T02 初始化）
ROLE_SUPER_ADMIN = "super_admin"
ROLE_NORMAL = "normal"

#: 超级管理员权限编码通配符——拥有 ``*`` 即视为拥有全部权限
PERMISSION_WILDCARD = "*"


# ============================================================
# M15 错误码（码段 25000-25999）
#
# 25001~25008 按 API 设计 §14 的明确定义；
# 25002~25004 在任务卡 M15-T03 的 DoD 中也有引用，两处一致。
# 文档未定义的场景占用 25009 及之后。
# ============================================================

#: 权限不足（API §16.3）
ERROR_PERMISSION_DENIED = 25001

#: 用户名已存在（API §14.2，HTTP 409）
ERROR_ADMIN_USERNAME_DUPLICATE = 25002

#: 仅存的超级管理员不能删除（API §14.5，HTTP 409）
ERROR_ADMIN_LAST_SUPER = 25003

#: 不能删除自己（API §14.5，HTTP 400）
ERROR_ADMIN_SELF_DELETE = 25004

#: 角色已分配给管理员，不能删除（API §14.8，HTTP 409）
ERROR_ROLE_IN_USE = 25005

#: 内置角色不可删除（API §14.8，HTTP 400）
ERROR_ROLE_BUILTIN = 25006

#: 原密码错误（API §14.16，HTTP 400）
ERROR_OLD_PASSWORD_INVALID = 25007

#: 新密码与原密码相同（API §14.16，HTTP 400）
ERROR_SAME_PASSWORD = 25008

#: 管理员不存在（API 未定义）
ERROR_ADMIN_NOT_FOUND = 25009

#: 角色不存在（API 未定义）
ERROR_ROLE_NOT_FOUND = 25010

#: 不能禁用自己（API 未定义，M15-T03）
ERROR_ADMIN_SELF_DISABLE = 25011

#: 配置项不存在（API 未定义）
ERROR_SETTING_NOT_FOUND = 25012

#: 密码不符合要求（长度 / 复杂度）
ERROR_ADMIN_WEAK_PASSWORD = 25013

#: 角色编码重复（API 未定义）
ERROR_ROLE_CODE_DUPLICATE = 25014


__all__ = [
    "ERROR_ADMIN_LAST_SUPER",
    "ERROR_ADMIN_NOT_FOUND",
    "ERROR_ADMIN_SELF_DELETE",
    "ERROR_ADMIN_SELF_DISABLE",
    "ERROR_ADMIN_USERNAME_DUPLICATE",
    "ERROR_ADMIN_WEAK_PASSWORD",
    "ERROR_OLD_PASSWORD_INVALID",
    "ERROR_PERMISSION_DENIED",
    "ERROR_ROLE_BUILTIN",
    "ERROR_ROLE_IN_USE",
    "ERROR_ROLE_NOT_FOUND",
    "ERROR_SAME_PASSWORD",
    "ERROR_SETTING_NOT_FOUND",
    "PERMISSION_WILDCARD",
    "ROLE_NORMAL",
    "ROLE_SUPER_ADMIN",
    "AdminStatus",
    "OperationAction",
    "PermissionAction",
]
