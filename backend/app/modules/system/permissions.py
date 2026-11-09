"""权限项清单（M15-T02，评审 §Q13 数据驱动）。

**权限项是静态字典**——由数据迁移写入 ``permission`` 表，运行时只读。
新增接口时在 ``PERMISSION_DEFINITIONS`` 里登记一行，再生成一条增量迁移。

编码格式：``{module}.{resource}.{action}``（API §16「权限项示例」）

    catalog.attraction.create        创建景点
    knowledge_base.document.create   上传文档
    system.admin.manage              管理员管理

**为什么不用「模块 × 操作」二维表**：
    二分会把「景点」和「餐厅」的删除权限绑定在一起——运营可能只需要
    管理景点，不需要动餐厅。``module.resource.action`` 三段式让授权
    可以精确到单个资源类型。

清单来源：API 接口设计第四、八、九、十、十二、十三、十四、十五节的
全部 B 端接口，按「一个资源一组操作」归纳。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.system.constants import PermissionAction


@dataclass(frozen=True, slots=True)
class PermissionDefinition:
    """一条权限项定义。"""

    code: str
    module: str
    action: str
    name: str
    description: str | None = None


def _p(
    code: str,
    name: str,
    *,
    module: str,
    action: str,
    description: str | None = None,
) -> PermissionDefinition:
    return PermissionDefinition(
        code=code, module=module, action=action, name=name, description=description
    )


# ============================================================
# 权限项清单
#
# 顺序即前端「权限项列表」的展示顺序：按业务域从数据到运营。
# ============================================================

PERMISSION_DEFINITIONS: tuple[PermissionDefinition, ...] = (
    # ---------- M11 基础数据（catalog） ----------
    _p("catalog.region.read", "查看省市", module="catalog", action="read"),
    _p("catalog.region.create", "创建省市", module="catalog", action="create"),
    _p("catalog.region.update", "编辑省市", module="catalog", action="update"),
    _p("catalog.region.delete", "删除省市", module="catalog", action="delete"),
    _p("catalog.category.read", "查看景点分类", module="catalog", action="read"),
    _p("catalog.category.create", "创建景点分类", module="catalog", action="create"),
    _p("catalog.category.update", "编辑景点分类", module="catalog", action="update"),
    _p("catalog.category.delete", "删除景点分类", module="catalog", action="delete"),
    _p("catalog.attraction.read", "查看景点", module="catalog", action="read"),
    _p("catalog.attraction.create", "创建景点", module="catalog", action="create"),
    _p("catalog.attraction.update", "编辑景点", module="catalog", action="update"),
    _p("catalog.attraction.delete", "删除景点", module="catalog", action="delete"),
    # 批量导入不单列权限：它本质是批量创建，能建单个景点就该能导入。
    # 真正的差异在「批量」带来的风险，由接口层的文件大小与行数上限控制。
    _p("catalog.attraction.export", "导出景点", module="catalog", action="export"),
    _p("catalog.restaurant.read", "查看餐厅", module="catalog", action="read"),
    _p("catalog.restaurant.create", "创建餐厅", module="catalog", action="create"),
    _p("catalog.restaurant.update", "编辑餐厅", module="catalog", action="update"),
    _p("catalog.restaurant.delete", "删除餐厅", module="catalog", action="delete"),
    _p("catalog.hotel.read", "查看酒店", module="catalog", action="read"),
    _p("catalog.hotel.create", "创建酒店", module="catalog", action="create"),
    _p("catalog.hotel.update", "编辑酒店", module="catalog", action="update"),
    _p("catalog.hotel.delete", "删除酒店", module="catalog", action="delete"),
    _p("catalog.transport.read", "查看景区交通", module="catalog", action="read"),
    _p("catalog.transport.create", "创建景区交通", module="catalog", action="create"),
    _p("catalog.transport.delete", "删除景区交通", module="catalog", action="delete"),
    _p("catalog.activity.read", "查看活动", module="catalog", action="read"),
    _p("catalog.activity.create", "创建活动", module="catalog", action="create"),
    _p("catalog.activity.update", "编辑活动", module="catalog", action="update"),
    _p("catalog.activity.delete", "删除活动", module="catalog", action="delete"),
    _p("catalog.activity.manage", "活动上下架", module="catalog", action="manage"),
    # ---------- M09 知识库（knowledge_base） ----------
    _p("knowledge_base.kb.read", "查看知识库", module="knowledge_base", action="read"),
    _p(
        "knowledge_base.kb.create",
        "创建知识库",
        module="knowledge_base",
        action="create",
    ),
    _p(
        "knowledge_base.kb.update",
        "编辑知识库",
        module="knowledge_base",
        action="update",
    ),
    _p(
        "knowledge_base.kb.delete",
        "删除知识库",
        module="knowledge_base",
        action="delete",
    ),
    _p(
        "knowledge_base.kb.manage",
        "重建知识库索引",
        module="knowledge_base",
        action="manage",
    ),
    _p(
        "knowledge_base.document.read",
        "查看文档",
        module="knowledge_base",
        action="read",
    ),
    _p(
        "knowledge_base.document.create",
        "上传文档",
        module="knowledge_base",
        action="create",
    ),
    _p(
        "knowledge_base.document.delete",
        "删除文档",
        module="knowledge_base",
        action="delete",
    ),
    _p(
        "knowledge_base.document.manage",
        "重解析/取消文档处理",
        module="knowledge_base",
        action="manage",
    ),
    # ---------- M10 知识图谱（knowledge_graph） ----------
    _p(
        "knowledge_graph.entity.read",
        "查看图谱实体",
        module="knowledge_graph",
        action="read",
    ),
    _p(
        "knowledge_graph.entity.create",
        "创建图谱实体",
        module="knowledge_graph",
        action="create",
    ),
    _p(
        "knowledge_graph.entity.update",
        "编辑图谱实体",
        module="knowledge_graph",
        action="update",
    ),
    _p(
        "knowledge_graph.entity.delete",
        "删除图谱实体",
        module="knowledge_graph",
        action="delete",
    ),
    _p(
        "knowledge_graph.relation.read",
        "查看图谱关系",
        module="knowledge_graph",
        action="read",
    ),
    _p(
        "knowledge_graph.relation.create",
        "创建图谱关系",
        module="knowledge_graph",
        action="create",
    ),
    _p(
        "knowledge_graph.relation.delete",
        "删除图谱关系",
        module="knowledge_graph",
        action="delete",
    ),
    _p(
        "knowledge_graph.entity.export",
        "导出图谱关系",
        module="knowledge_graph",
        action="export",
    ),
    _p(
        "knowledge_graph.entity.manage",
        "图谱同步与导入",
        module="knowledge_graph",
        action="manage",
    ),
    _p(
        "knowledge_graph.featured.manage",
        "精选景点知识图谱管理",
        module="knowledge_graph",
        action="manage",
    ),
    # ---------- M12 模型管理（model） ----------
    _p("model.model.read", "查看模型", module="model", action="read"),
    _p("model.model.create", "注册模型", module="model", action="create"),
    _p("model.model.update", "编辑模型", module="model", action="update"),
    _p("model.model.delete", "删除模型", module="model", action="delete"),
    _p("model.model.manage", "启停与连通性测试", module="model", action="manage"),
    # ---------- M13 额度服务（quota） ----------
    _p("quota.config.read", "查看额度配置", module="quota", action="read"),
    _p("quota.config.update", "修改额度配置", module="quota", action="update"),
    # ---------- M14 用户运营（user_ops） ----------
    _p("user_ops.user.read", "查看用户", module="user_ops", action="read"),
    _p("user_ops.user.update", "编辑用户资料", module="user_ops", action="update"),
    _p("user_ops.user.manage", "封禁/解封用户", module="user_ops", action="manage"),
    _p(
        "user_ops.user.export",
        "导出用户名单",
        module="user_ops",
        action="export",
    ),
    # ---------- M15 系统管理（system） ----------
    _p("system.admin.read", "查看管理员", module="system", action="read"),
    _p("system.admin.create", "创建管理员", module="system", action="create"),
    _p("system.admin.update", "编辑管理员", module="system", action="update"),
    _p("system.admin.delete", "删除管理员", module="system", action="delete"),
    _p("system.admin.manage", "重置管理员密码", module="system", action="manage"),
    _p("system.role.read", "查看角色", module="system", action="read"),
    _p("system.role.create", "创建角色", module="system", action="create"),
    _p("system.role.update", "编辑角色与授权", module="system", action="update"),
    _p("system.role.delete", "删除角色", module="system", action="delete"),
    _p("system.permission.read", "查看权限项", module="system", action="read"),
    _p("system.setting.read", "查看站点配置", module="system", action="read"),
    _p("system.setting.update", "修改站点配置", module="system", action="update"),
    _p("system.log.read", "查看操作日志", module="system", action="read"),
    _p("system.log.export", "导出操作日志", module="system", action="export"),
    # ---------- M16 数据看板（dashboard） ----------
    _p("dashboard.metric.read", "查看看板指标", module="dashboard", action="read"),
    _p("dashboard.metric.export", "导出看板数据", module="dashboard", action="export"),
)


# ============================================================
# 角色定义
# ============================================================


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    code: str
    name: str
    description: str
    is_builtin: bool


ROLE_DEFINITIONS: tuple[RoleDefinition, ...] = (
    RoleDefinition(
        code="super_admin",
        name="超级管理员",
        description="拥有全部权限，不可删除",
        is_builtin=True,
    ),
    RoleDefinition(
        code="normal",
        name="普通管理员",
        description="无 B 端管理权限，仅可登录查看（初始状态，需手动授权）",
        is_builtin=True,
    ),
)


def permission_codes() -> tuple[str, ...]:
    """全部权限编码，按定义顺序。"""
    return tuple(item.code for item in PERMISSION_DEFINITIONS)


def permissions_by_module() -> dict[str, list[PermissionDefinition]]:
    """按模块分组，供前端权限勾选树使用。"""
    grouped: dict[str, list[PermissionDefinition]] = {}
    for item in PERMISSION_DEFINITIONS:
        grouped.setdefault(item.module, []).append(item)
    return grouped


__all__ = [
    "PERMISSION_DEFINITIONS",
    "ROLE_DEFINITIONS",
    "PermissionAction",
    "PermissionDefinition",
    "RoleDefinition",
    "permission_codes",
    "permissions_by_module",
]
