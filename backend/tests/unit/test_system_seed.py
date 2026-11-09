"""M15-T02 初始化角色与权限项的测试。

覆盖 DoD：
    1. 初始化后 ``role`` 表有 2 条记录（DB 断言）
    2. 权限项数量与模块数匹配（每模块至少 4 个 CRUD 权限）（DB 断言）
    3. 超级管理员角色拥有全部权限（关联数 = 权限总数）（DB 断言）
    4. 数据迁移可重复执行（幂等，ON CONFLICT DO NOTHING）
    5. 无物理外键
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from app.modules.system.constants import PermissionAction
from app.modules.system.permissions import (
    PERMISSION_DEFINITIONS,
    ROLE_DEFINITIONS,
    permission_codes,
    permissions_by_module,
)


def _load_migration_module():
    """按文件路径加载迁移模块。

    ``versions/`` 目录没有 ``__init__.py``（Alembic 不要求），
    因此不能常规 import。用 importlib 按路径加载。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_m15_seed_migration", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BACKEND_DIR = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    BACKEND_DIR
    / "app"
    / "db"
    / "migrations"
    / "versions"
    / "0015_m15_seed_permissions.py"
)


# ============================================================
# 权限项清单的静态检查（不依赖数据库）
# ============================================================


class TestPermissionDefinitions:
    def test_codes_are_unique(self) -> None:
        codes = permission_codes()
        assert len(codes) == len(set(codes)), "权限编码有重复"

    def test_code_format(self) -> None:
        """编码格式：``module.resource.action``。"""
        # 第三段是资源名，末段才是动作（受数据库 CHECK 约束）
        pattern = re.compile(
            r"^[a-z_]+\.[a-z_]+\.(create|read|update|delete|export|manage)$"
        )
        for item in PERMISSION_DEFINITIONS:
            assert pattern.match(item.code), f"编码格式不正确：{item.code}"

    def test_code_matches_module_and_action(self) -> None:
        """编码里的 module/action 必须与字段一致。"""
        for item in PERMISSION_DEFINITIONS:
            parts = item.code.split(".")
            assert parts[0] == item.module, f"{item.code} 的 module 不一致"
            assert parts[-1] == item.action, f"{item.code} 的 action 不一致"

    def test_action_is_valid_enum(self) -> None:
        valid = {action.value for action in PermissionAction}
        for item in PERMISSION_DEFINITIONS:
            assert item.action in valid, f"{item.code} 的 action 非法：{item.action}"

    def test_names_are_non_empty(self) -> None:
        for item in PERMISSION_DEFINITIONS:
            assert item.name.strip(), f"{item.code} 缺少中文名"

    def test_covers_expected_modules(self) -> None:
        """覆盖全部 B 端模块。"""
        modules = {item.module for item in PERMISSION_DEFINITIONS}
        assert modules == {
            "catalog",
            "knowledge_base",
            "knowledge_graph",
            "model",
            "quota",
            "user_ops",
            "system",
            "dashboard",
        }

    def test_each_module_has_crud(self) -> None:
        """DoD：每模块至少 4 个 CRUD 权限。

        ``quota`` / ``dashboard`` 是配置与只读模块，``user_ops`` 是运营模块
        （用户由 C 端注册产生，运营只能查、改、封禁，不能创建或删除），
        三者天然没有完整 CRUD——单独豁免，但仍需至少 2 个权限。
        """
        readonly_modules = {"quota", "dashboard", "user_ops"}

        grouped = permissions_by_module()
        for module, items in grouped.items():
            actions = {item.action for item in items}
            if module in readonly_modules:
                assert len(items) >= 2, f"{module} 权限项太少"
            else:
                crud = {"create", "read", "update", "delete"}
                missing = crud - actions
                assert not missing, f"{module} 缺少 CRUD 权限：{missing}"

    def test_total_count_reasonable(self) -> None:
        """权限项总数应与接口规模匹配——太少说明漏登记，太多说明粒度过细。"""
        assert 60 <= len(PERMISSION_DEFINITIONS) <= 150

    def test_permissions_by_module_covers_all(self) -> None:
        grouped = permissions_by_module()
        total = sum(len(items) for items in grouped.values())
        assert total == len(PERMISSION_DEFINITIONS)


class TestRoleDefinitions:
    def test_two_builtin_roles(self) -> None:
        """DoD：初始化 2 个角色。"""
        assert len(ROLE_DEFINITIONS) == 2

    def test_role_codes(self) -> None:
        codes = {role.code for role in ROLE_DEFINITIONS}
        assert codes == {"super_admin", "normal"}

    def test_both_are_builtin(self) -> None:
        assert all(role.is_builtin for role in ROLE_DEFINITIONS)

    def test_has_chinese_names(self) -> None:
        for role in ROLE_DEFINITIONS:
            assert role.name.strip()
            assert role.description.strip()


# ============================================================
# 迁移脚本的静态检查
# ============================================================


class TestMigrationScript:
    def test_exists(self) -> None:
        assert MIGRATION_PATH.exists()

    def test_uses_on_conflict_do_nothing(self) -> None:
        """DoD：数据迁移必须幂等。"""
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        assert source.count("ON CONFLICT") >= 3, "三处写入都应带 ON CONFLICT"

    def test_no_physical_foreign_key(self) -> None:
        """DoD：无物理外键。"""
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        hits = re.findall(r"(?i)foreign\s+key|references", source)
        assert hits == [], f"迁移中出现外键关键字：{hits}"

    def test_revision_chain(self) -> None:
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        assert 'revision: str = "0015_m15_seed_permissions"' in source
        assert 'down_revision: str | None = "0014_m17_user_event"' in source

    def test_permission_ids_are_deterministic(self) -> None:
        """权限 ID 由 uuid5 从编码推导——同一 code 永远得到同一 ID。"""
        mod = _load_migration_module()

        first = mod._permission_id("catalog.attraction.read")
        second = mod._permission_id("catalog.attraction.read")
        assert first == second

        different = mod._permission_id("catalog.attraction.delete")
        assert first != different

    def test_permission_id_is_valid_uuid(self) -> None:
        mod = _load_migration_module()

        parsed = uuid.UUID(mod._permission_id("model.model.read"))
        assert parsed.version == 5


# ============================================================
# 数据库断言（DoD 1 ~ 3）
# ============================================================


pytestmark_db = pytest.mark.integration


@pytest.fixture
async def db_session():
    from app.db.session import SessionLocal, check_database

    try:
        if not await check_database():
            pytest.skip("数据库不可达")
    except Exception:
        pytest.skip("数据库不可达")

    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT to_regclass('public.role') IS NOT NULL")
        )
        if not result.scalar_one():
            pytest.skip("表未创建（先执行 alembic upgrade head）")
        yield session


class TestSeededData:
    async def test_two_roles_exist(self, db_session) -> None:
        """DoD：``role`` 表有 2 条内置角色。"""
        result = await db_session.execute(
            text("SELECT code FROM role WHERE is_builtin = TRUE ORDER BY code")
        )
        codes = [row[0] for row in result.all()]

        assert "super_admin" in codes
        assert "normal" in codes

    async def test_permissions_match_definition_count(self, db_session) -> None:
        """DoD：库里的权限项数量与代码定义一致。"""
        result = await db_session.execute(text("SELECT count(*) FROM permission"))
        assert result.scalar_one() == len(PERMISSION_DEFINITIONS)

    async def test_super_admin_has_all_permissions(self, db_session) -> None:
        """DoD：超级管理员拥有全部权限（关联数 = 权限总数）。"""
        result = await db_session.execute(
            text(
                """
                SELECT count(*) FROM role_permission rp
                JOIN role r ON r.id = rp.role_id
                WHERE r.code = 'super_admin'
                """
            )
        )
        granted = result.scalar_one()

        total = (
            await db_session.execute(text("SELECT count(*) FROM permission"))
        ).scalar_one()

        assert granted == total

    async def test_normal_role_has_no_permissions(self, db_session) -> None:
        """普通管理员初始无权限，需手动授权（Q13）。"""
        result = await db_session.execute(
            text(
                """
                SELECT count(*) FROM role_permission rp
                JOIN role r ON r.id = rp.role_id
                WHERE r.code = 'normal'
                """
            )
        )
        assert result.scalar_one() == 0

    async def test_every_permission_can_be_granted(self, db_session) -> None:
        """每个权限项都能被引用——没有孤立的权限项。"""
        result = await db_session.execute(
            text(
                """
                SELECT count(*) FROM permission p
                WHERE NOT EXISTS (
                    SELECT 1 FROM role_permission rp WHERE rp.permission_id = p.id
                )
                """
            )
        )
        assert result.scalar_one() == 0

    async def test_permission_codes_match_code_definitions(self, db_session) -> None:
        result = await db_session.execute(text("SELECT code FROM permission"))
        db_codes = {row[0] for row in result.all()}
        assert db_codes == set(permission_codes())

    async def test_module_action_columns_correct(self, db_session) -> None:
        """库里的 module/action 列必须与编码一致。"""
        result = await db_session.execute(
            text("SELECT code, module, action FROM permission")
        )
        for code, module, action in result.all():
            parts = code.split(".")
            assert parts[0] == module
            assert parts[-1] == action


class TestIdempotency:
    async def test_on_conflict_clauses_prevent_duplicates(self, db_session) -> None:
        """DoD：数据迁移可重复执行（``ON CONFLICT DO NOTHING``）。

        验证方式：按迁移里的**同一套 INSERT 语句**再执行一遍，
        确认行数不变。不直接调用迁移函数——那需要 Alembic 的同步
        Connection，而测试环境只有 asyncpg；重复执行 SQL 已经能
        证明 ``ON CONFLICT`` 生效。
        """
        mod = _load_migration_module()

        async def counts() -> tuple[int, int, int]:
            roles = (
                await db_session.execute(text("SELECT count(*) FROM role"))
            ).scalar_one()
            perms = (
                await db_session.execute(text("SELECT count(*) FROM permission"))
            ).scalar_one()
            grants = (
                await db_session.execute(text("SELECT count(*) FROM role_permission"))
            ).scalar_one()
            return roles, perms, grants

        before = await counts()

        # 逐条重放迁移中的 INSERT（与迁移文件同一份 SQL）
        for role in (
            {
                "id": mod.SUPER_ADMIN_ROLE_ID,
                "code": "super_admin",
                "name": "超级管理员",
                "description": "拥有全部权限，不可删除",
            },
            {
                "id": mod.NORMAL_ROLE_ID,
                "code": "normal",
                "name": "普通管理员",
                "description": "无 B 端管理权限，仅可登录查看（初始状态，需手动授权）",
            },
        ):
            await db_session.execute(
                text(
                    """
                    INSERT INTO role (id, code, name, description, is_builtin,
                                      created_at, updated_at)
                    VALUES (:id, :code, :name, :description, TRUE, NOW(), NOW())
                    ON CONFLICT (code) DO NOTHING
                    """
                ),
                role,
            )

        from app.modules.system.permissions import PERMISSION_DEFINITIONS

        for item in PERMISSION_DEFINITIONS:
            await db_session.execute(
                text(
                    """
                    INSERT INTO permission (id, code, module, action, name,
                                            description, created_at)
                    VALUES (:id, :code, :module, :action, :name, :description, NOW())
                    ON CONFLICT (code) DO NOTHING
                    """
                ),
                {
                    "id": mod._permission_id(item.code),
                    "code": item.code,
                    "module": item.module,
                    "action": item.action,
                    "name": item.name,
                    "description": item.description,
                },
            )

        await db_session.execute(
            text(
                """
                INSERT INTO role_permission (id, role_id, permission_id, created_at)
                SELECT gen_random_uuid(), :role_id, p.id, NOW()
                FROM permission p
                ON CONFLICT (role_id, permission_id) DO NOTHING
                """
            ),
            {"role_id": mod.SUPER_ADMIN_ROLE_ID},
        )
        await db_session.commit()

        assert await counts() == before, "重复执行后行数发生了变化"

    async def test_migration_uses_on_conflict(self) -> None:
        """静态检查：三处写入都带 ``ON CONFLICT DO NOTHING``。"""
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        assert source.count("ON CONFLICT") >= 3
        assert source.count("DO NOTHING") >= 3
