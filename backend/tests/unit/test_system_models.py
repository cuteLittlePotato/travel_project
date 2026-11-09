"""M15-T01 系统管理 ORM 的测试。

覆盖 DoD：
    1. ``admin_user.token_version`` 存在且默认 0
    2. ``role_permission`` 唯一约束 ``(role_id, permission_id)``
    3. ``admin_user_role`` 唯一约束 ``(admin_user_id, role_id)``
    4. ``permission.action`` CHECK 含 create/read/update/delete/export/manage
    5. 无物理外键；``site_setting.setting_key`` 唯一
边界：``admin_user`` 与 ``user`` 完全分离（评审 §Q10）。
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import CheckConstraint

from app.modules.account.models import User
from app.modules.system.constants import (
    OperationAction,
    PermissionAction,
)
from app.modules.system.models import (
    AdminUser,
    AdminUserRole,
    OperationLog,
    Permission,
    Role,
    RolePermission,
    SiteSetting,
)

MODELS_DIR = Path(__file__).resolve().parents[2] / "app" / "modules" / "system"

ALL_MODELS = (
    AdminUser,
    Role,
    Permission,
    RolePermission,
    AdminUserRole,
    OperationLog,
    SiteSetting,
)


def _columns(model: type) -> set[str]:
    return {c.name for c in model.__table__.columns}


def _unique_index_columns(model: type) -> list[list[str]]:
    return [
        [c.name for c in idx.columns]
        for idx in model.__table__.indexes
        if idx.unique
    ]


# ============================================================
# 表结构
# ============================================================


class TestTableNames:
    def test_seven_tables(self) -> None:
        expected = {
            "admin_user",
            "role",
            "permission",
            "role_permission",
            "admin_user_role",
            "operation_log",
            "site_setting",
        }
        assert {model.__tablename__ for model in ALL_MODELS} == expected


class TestAdminUser:
    def test_required_columns(self) -> None:
        columns = _columns(AdminUser)
        for name in (
            "id",
            "username",
            "password_hash",
            "real_name",
            "email",
            "status",
            "token_version",
            "last_login_at",
            "created_at",
            "updated_at",
        ):
            assert name in columns, f"缺少列 {name}"

    def test_token_version_default_zero(self) -> None:
        """DoD：``admin_user.token_version`` 存在且默认 0。"""
        column = AdminUser.__table__.c.token_version

        assert column.nullable is False
        assert str(column.server_default.arg) == "0"

    def test_username_unique(self) -> None:
        assert ["username"] in _unique_index_columns(AdminUser)

    def test_status_check(self) -> None:
        check = next(
            c for c in AdminUser.__table__.constraints if isinstance(c, CheckConstraint)
        )
        for status in ("active", "disabled"):
            assert status in str(check.sqltext)

    def test_password_hash_not_plaintext_column(self) -> None:
        """列名必须是 hash——明文密码列一旦建立就有人往里写明文。"""
        assert "password" not in _columns(AdminUser)
        assert "password_hash" in _columns(AdminUser)


class TestRole:
    def test_required_columns(self) -> None:
        for name in (
            "id",
            "code",
            "name",
            "description",
            "is_builtin",
            "created_at",
            "updated_at",
        ):
            assert name in _columns(Role)

    def test_code_unique(self) -> None:
        assert ["code"] in _unique_index_columns(Role)

    def test_is_builtin_not_null(self) -> None:
        assert Role.__table__.c.is_builtin.nullable is False


class TestPermission:
    def test_required_columns(self) -> None:
        for name in ("id", "code", "module", "action", "name", "description", "created_at"):
            assert name in _columns(Permission)

    def test_code_unique(self) -> None:
        assert ["code"] in _unique_index_columns(Permission)

    def test_action_check_covers_six(self) -> None:
        """DoD：CHECK 含 create/read/update/delete/export/manage。"""
        check = next(
            c for c in Permission.__table__.constraints if isinstance(c, CheckConstraint)
        )
        sql = str(check.sqltext)

        for action in ("create", "read", "update", "delete", "export", "manage"):
            assert action in sql

    def test_action_enum_matches(self) -> None:
        assert {action.value for action in PermissionAction} == {
            "create",
            "read",
            "update",
            "delete",
            "export",
            "manage",
        }

    def test_no_updated_at(self) -> None:
        """权限项是静态字典，随迁移初始化，不在运行时修改。"""
        assert "updated_at" not in _columns(Permission)


class TestRolePermission:
    def test_unique_constraint(self) -> None:
        """DoD：``role_permission`` 唯一约束 ``(role_id, permission_id)``。"""
        assert ["role_id", "permission_id"] in _unique_index_columns(RolePermission)

    def test_required_columns(self) -> None:
        for name in ("id", "role_id", "permission_id", "created_at"):
            assert name in _columns(RolePermission)

    def test_no_updated_at(self) -> None:
        assert "updated_at" not in _columns(RolePermission)


class TestAdminUserRole:
    def test_unique_constraint(self) -> None:
        """DoD：``admin_user_role`` 唯一约束 ``(admin_user_id, role_id)``。"""
        assert ["admin_user_id", "role_id"] in _unique_index_columns(AdminUserRole)

    def test_required_columns(self) -> None:
        for name in ("id", "admin_user_id", "role_id", "created_at"):
            assert name in _columns(AdminUserRole)


class TestOperationLog:
    def test_required_columns(self) -> None:
        for name in (
            "id",
            "admin_user_id",
            "module",
            "action",
            "target_type",
            "target_id",
            "detail",
            "ip_address",
            "user_agent",
            "is_success",
            "created_at",
        ):
            assert name in _columns(OperationLog)

    def test_action_check_covers_six(self) -> None:
        check = next(
            c
            for c in OperationLog.__table__.constraints
            if isinstance(c, CheckConstraint)
        )
        sql = str(check.sqltext)

        for action in ("create", "update", "delete", "export", "login", "logout"):
            assert action in sql

    def test_no_read_action(self) -> None:
        """DDL 注释的取舍：不记录查询。"""
        check = next(
            c
            for c in OperationLog.__table__.constraints
            if isinstance(c, CheckConstraint)
        )
        assert "read" not in str(check.sqltext)

    def test_action_enum_matches(self) -> None:
        assert {a.value for a in OperationAction} == {
            "create",
            "update",
            "delete",
            "export",
            "login",
            "logout",
        }

    def test_ip_address_fits_ipv6(self) -> None:
        """IPv6 最长 45 字符，列宽不足会截断。"""
        assert OperationLog.__table__.c.ip_address.type.length >= 45

    def test_no_updated_at(self) -> None:
        """日志写入后不修改。"""
        assert "updated_at" not in _columns(OperationLog)


class TestSiteSetting:
    def test_required_columns(self) -> None:
        for name in ("id", "setting_key", "setting_value", "description", "updated_by", "updated_at"):
            assert name in _columns(SiteSetting)

    def test_setting_key_unique(self) -> None:
        """DoD：``site_setting.setting_key`` 唯一。"""
        assert ["setting_key"] in _unique_index_columns(SiteSetting)

    def test_setting_value_is_jsonb(self) -> None:
        """配置值可能是字符串/数字/数组/对象，必须是 JSONB。"""
        column_type = SiteSetting.__table__.c.setting_value.type
        assert column_type.__class__.__name__ == "JSONB"

    def test_setting_value_not_null(self) -> None:
        assert SiteSetting.__table__.c.setting_value.nullable is False

    def test_no_created_at(self) -> None:
        """配置随初始化写入，创建时间无独立语义，只有 updated_at。"""
        assert "created_at" not in _columns(SiteSetting)


# ============================================================
# 规范检查
# ============================================================


class TestNoForeignKeys:
    def test_no_model_has_foreign_keys(self) -> None:
        """DoD：无物理外键。"""
        for model in ALL_MODELS:
            assert model.__table__.foreign_keys == set(), (
                f"{model.__tablename__} 存在物理外键"
            )

    def test_source_has_no_references(self) -> None:
        for filename in ("models.py", "constants.py"):
            source = (MODELS_DIR / filename).read_text(encoding="utf-8")
            hits = re.findall(r"(?i)foreign\s+key|references", source)
            assert hits == [], f"{filename} 中出现了外键关键字：{hits}"

    def test_no_relationship_declaration(self) -> None:
        source = (MODELS_DIR / "models.py").read_text(encoding="utf-8")
        assert "relationship(" not in source


class TestAdminUserSeparateFromUser:
    """边界：``admin_user`` 与 ``user`` 完全分离（评审 §Q10）。"""

    def test_different_tables(self) -> None:
        assert AdminUser.__tablename__ != User.__tablename__
        assert AdminUser.__tablename__ == "admin_user"
        assert User.__tablename__ == "user"

    def test_no_shared_primary_key_domain(self) -> None:
        """两张表的 id 各自独立，不存在指向关系。"""
        assert "user_id" not in _columns(AdminUser)
        assert "admin_user_id" not in _columns(User)

    def test_c_end_user_has_no_password(self) -> None:
        """C 端用户**不用密码登录**——只走验证码与 OAuth。

        B 端必须有 ``password_hash``，C 端故意没有：
        用户账号被盗的首要途径就是弱口令，去掉密码列等于从设计上消除
        这个攻击面。测试锁定这一差异，防止有人「顺手」给用户表加密码。
        """
        assert "password_hash" not in _columns(User)
        assert "password_hash" in _columns(AdminUser)

    def test_user_has_no_admin_fields(self) -> None:
        """C 端用户表不应有管理员专属字段。"""
        user_columns = _columns(User)
        assert "is_builtin" not in user_columns
        assert "real_name" not in user_columns

    def test_admin_user_has_no_c_end_fields(self) -> None:
        """管理员表不应有 C 端用户专属字段。"""
        admin_columns = _columns(AdminUser)
        for c_end_field in ("nickname", "phone", "avatar_url"):
            assert c_end_field not in admin_columns
