"""M01 用户与账户 ORM 模型的测试（M01-T02）。

CLAUDE.md §5.1 要求：模型必须与数据库 DDL 差异归零。
本测试分两层：
    - 静态断言（无需数据库）：表名、字段、约束、无物理外键
    - 真实 DDL 比对（integration）：调用 check_model_drift 的逻辑
"""

from __future__ import annotations

import pytest
from sqlalchemy import Index, UniqueConstraint

from app.db.base import Base
from app.modules.account.constants import (
    BindingProvider,
    BudgetLevel,
    CompanionType,
    Gender,
    NotificationType,
    UserStatus,
    Visibility,
)
from app.modules.account.models import (
    Notification,
    OAuthBinding,
    User,
    UserProfile,
    UserSetting,
)

#: M01 拥有的五张表
EXPECTED_TABLES = {
    "user",
    "oauth_binding",
    "user_profile",
    "user_setting",
    "notification",
}


def _columns(model: type) -> set[str]:
    return {c.name for c in model.__table__.columns}


# ============================================================
# 表与字段
# ============================================================


class TestTableStructure:
    def test_all_five_tables_registered(self) -> None:
        registered = set(Base.metadata.tables)
        assert registered >= EXPECTED_TABLES, f"缺少: {EXPECTED_TABLES - registered}"

    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            (
                User,
                {
                    "id", "username", "nickname", "avatar_url", "gender",
                    "region_code", "status", "token_version", "last_login_at",
                    "created_at", "updated_at",
                },
            ),
            (
                OAuthBinding,
                {
                    "id", "user_id", "provider", "provider_uid",
                    "credential", "extra_data", "is_primary", "created_at",
                },
            ),
            (
                UserProfile,
                {
                    "id", "user_id", "travel_types", "travel_styles",
                    "budget_level", "companion_type", "preferred_seasons",
                    "departure_city_code", "updated_at",
                },
            ),
            (
                UserSetting,
                {
                    "id", "user_id", "profile_visibility", "footprint_visibility",
                    "plan_visibility", "allow_recommendation", "allow_notification",
                    "updated_at",
                },
            ),
            (
                Notification,
                {
                    "id", "user_id", "notification_type", "title", "content",
                    "related_type", "related_id", "is_read", "read_at", "created_at",
                },
            ),
        ],
    )
    def test_columns_match_ddl(self, model: type, expected: set[str]) -> None:
        assert _columns(model) == expected

    def test_primary_keys_are_uuid(self) -> None:
        from sqlalchemy.dialects.postgresql import UUID as PGUUID

        for model in (User, OAuthBinding, UserProfile, UserSetting, Notification):
            pk = next(iter(model.__table__.primary_key.columns))
            assert pk.name == "id"
            assert isinstance(pk.type, PGUUID)

    def test_tables_without_created_at(self) -> None:
        """user_profile / user_setting 只有 updated_at（数据库设计 §3.1）。"""
        for model in (UserProfile, UserSetting):
            cols = _columns(model)
            assert "updated_at" in cols
            assert "created_at" not in cols

    def test_tables_without_updated_at(self) -> None:
        """oauth_binding / notification 只有 created_at。"""
        for model in (OAuthBinding, Notification):
            cols = _columns(model)
            assert "created_at" in cols
            assert "updated_at" not in cols


# ============================================================
# 约束与索引
# ============================================================


class TestConstraints:
    def test_no_physical_foreign_key(self) -> None:
        """DoD：模型不得声明物理外键。"""
        for model in (User, OAuthBinding, UserProfile, UserSetting, Notification):
            assert not model.__table__.foreign_keys, f"{model.__name__} 含物理外键"

    def test_no_relationship_declaration(self) -> None:
        """DoD：不得使用 relationship() 表达关系。"""
        from pathlib import Path

        source = Path(__file__).resolve().parents[2] / "app" / "modules" / "account" / "models.py"
        content = source.read_text(encoding="utf-8")
        assert "relationship(" not in content

    def test_unique_indexes_match_ddl(self) -> None:
        """DDL 用 CREATE UNIQUE INDEX，模型必须用 Index(unique=True)。"""
        expected = {
            "user": "uk_user_username",
            "oauth_binding": "uk_oauth_provider_uid",
            "user_profile": "uk_user_profile_user_id",
            "user_setting": "uk_user_setting_user_id",
        }
        for table_name, index_name in expected.items():
            table = Base.metadata.tables[table_name]
            unique_indexes = {
                idx.name for idx in table.indexes if isinstance(idx, Index) and idx.unique
            }
            assert index_name in unique_indexes, f"{table_name} 缺少唯一索引 {index_name}"

    def test_no_unique_constraint_mismatch(self) -> None:
        """若用 UniqueConstraint 会与 DDL 的唯一索引产生差异。"""
        for model in (User, OAuthBinding, UserProfile, UserSetting):
            constraints = [
                c for c in model.__table__.constraints if isinstance(c, UniqueConstraint)
            ]
            assert not constraints, (
                f"{model.__name__} 用了 UniqueConstraint，DDL 用的是唯一索引"
            )

    def test_check_constraints_present(self) -> None:
        """枚举字段必须有 CHECK 约束。"""
        def check_names(model: type) -> set[str]:
            return {
                c.name
                for c in model.__table__.constraints
                if type(c).__name__ == "CheckConstraint"
            }

        assert "ck_user_gender" in check_names(User)
        assert "ck_user_status" in check_names(User)
        assert "ck_oauth_binding_provider" in check_names(OAuthBinding)
        assert "ck_notification_notification_type" in check_names(Notification)

    def test_notification_partial_index(self) -> None:
        """未读索引是部分索引，只索引 is_read = FALSE。"""
        table = Base.metadata.tables["notification"]
        idx = next(i for i in table.indexes if i.name == "idx_notification_unread")
        assert idx.dialect_options["postgresql"].get("where") is not None


# ============================================================
# 枚举
# ============================================================


class TestEnums:
    def test_enum_values_match_check_constraints(self) -> None:
        """枚举值与数据库 CHECK 约束必须一致。"""
        def check_sql(model: type, name: str) -> str:
            constraint = next(
                c for c in model.__table__.constraints if c.name == name
            )
            return str(constraint.sqltext)

        gender_sql = check_sql(User, "ck_user_gender")
        for value in Gender:
            assert f"'{value.value}'" in gender_sql

        status_sql = check_sql(User, "ck_user_status")
        for value in UserStatus:
            assert f"'{value.value}'" in status_sql

        provider_sql = check_sql(OAuthBinding, "ck_oauth_binding_provider")
        for value in BindingProvider:
            assert f"'{value.value}'" in provider_sql

        notif_sql = check_sql(Notification, "ck_notification_notification_type")
        for value in NotificationType:
            assert f"'{value.value}'" in notif_sql

    def test_enum_serializes_to_string(self) -> None:
        """StrEnum 序列化为字符串，前端拿到 "active" 而非 "UserStatus.ACTIVE"。"""
        assert str(UserStatus.ACTIVE) == "active"
        assert UserStatus.ACTIVE == "active"

    def test_third_party_provider_flag(self) -> None:
        assert BindingProvider.WECHAT.is_third_party is True
        assert BindingProvider.PHONE.is_third_party is False

    def test_all_enums_have_expected_members(self) -> None:
        assert len(UserStatus) == 3
        assert len(Gender) == 3
        assert len(BindingProvider) == 5
        assert len(BudgetLevel) == 4
        assert len(CompanionType) == 4
        assert len(Visibility) == 3
        assert len(NotificationType) == 3


# ============================================================
# 模型行为
# ============================================================


class TestModelBehavior:
    def test_user_is_active(self) -> None:
        user = User(username="u", nickname="n", status=UserStatus.ACTIVE.value)
        assert user.is_active() is True
        user.status = UserStatus.BANNED.value
        assert user.is_active() is False

    def test_notification_mark_read(self) -> None:
        notification = Notification(
            user_id=None,  # type: ignore[arg-type]
            notification_type=NotificationType.SYSTEM.value,
            title="t",
        )
        # is_read 的默认值来自 server_default，新建对象 flush 前为 None
        assert not notification.is_read
        assert notification.read_at is None

        notification.mark_read()
        assert notification.is_read is True
        assert notification.read_at is not None

    def test_notification_mark_read_is_idempotent(self) -> None:
        notification = Notification(
            user_id=None,  # type: ignore[arg-type]
            notification_type=NotificationType.SYSTEM.value,
            title="t",
        )
        notification.mark_read()
        first_read_at = notification.read_at
        notification.mark_read()
        assert notification.read_at == first_read_at


# ============================================================
# 与数据库 DDL 的真实比对（CLAUDE.md §5.1 规则）
# ============================================================


class TestNotificationTableM01T14:
    """M01-T14 专项：通知表的迁移与模型验收。"""

    def test_check_constraint_values(self) -> None:
        """DoD：notification_type 的 CHECK 取值为三个枚举。"""
        checks = [
            str(c.sqltext)
            for c in Notification.__table__.constraints
            if type(c).__name__ == "CheckConstraint"
        ]
        assert len(checks) == 1
        sql = checks[0]
        for value in ("plan_starting", "plan_ended", "system"):
            assert f"'{value}'" in sql, f"CHECK 缺少 {value}"

    def test_three_indexes_exist(self) -> None:
        """DoD：三个索引必须存在。"""
        names = {i.name for i in Notification.__table__.indexes}
        for expected in (
            "idx_notification_user",
            "idx_notification_unread",
            "idx_notification_type",
        ):
            assert expected in names, f"缺少索引 {expected}"

    def test_unread_index_is_partial(self) -> None:
        """`idx_notification_unread` 是部分索引（WHERE is_read = FALSE）。

        M0-T13 的生成器曾丢失 WHERE 子句，把部分索引建成全量索引。
        本测试守护该修复。
        """
        idx = next(
            i for i in Notification.__table__.indexes if i.name == "idx_notification_unread"
        )
        where = idx.dialect_options["postgresql"].get("where")
        assert where is not None, "未读索引必须是部分索引"
        assert "is_read" in str(where).lower()

    def test_no_foreign_key(self) -> None:
        """DoD：无物理外键。"""
        assert not Notification.__table__.foreign_keys

    def test_is_read_defaults_false(self) -> None:
        """边界：is_read 默认 FALSE。"""
        default = Notification.__table__.c.is_read.server_default
        assert default is not None
        assert "false" in str(default.arg).lower()

    def test_related_id_nullable(self) -> None:
        """边界：related_id 可空。"""
        assert Notification.__table__.c.related_id.nullable is True
