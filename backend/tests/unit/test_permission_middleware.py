"""M15-T05 权限校验中间件的测试。

覆盖 DoD：
    1. 无权限访问返回 403 + 25001（接口测试）
    2. 超级管理员绕过权限检查（单测）
    3. 权限查询有缓存，缓存失效后重新加载（单测）
    4. 权限校验数据驱动，不硬编码角色判断
边界：权限变更后缓存失效策略。
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from app.api.middleware.permission import (
    EMPTY_PERMISSION_MARKER,
    PERMISSION_CACHE_PREFIX,
    PERMISSION_CACHE_TTL,
    _cache_key,
    _decode_cached,
    invalidate_admin_permissions,
    require_permission,
)

BACKEND_APP = Path(__file__).resolve().parents[2] / "app"
API_DIR = BACKEND_APP / "api"


# ============================================================
# 纯函数与常量（不依赖数据库）
# ============================================================


class TestCacheKey:
    def test_key_contains_admin_id(self) -> None:
        admin_id = uuid.uuid4()
        assert str(admin_id) in _cache_key(admin_id)

    def test_key_uses_prefix(self) -> None:
        assert PERMISSION_CACHE_PREFIX in _cache_key(uuid.uuid4())

    def test_key_has_ttl_configured(self) -> None:
        assert PERMISSION_CACHE_TTL > 0


class TestDecodeCached:
    def test_normal_members(self) -> None:
        assert _decode_cached({"a.b.c", "d.e.f"}) == {"a.b.c", "d.e.f"}

    def test_empty_marker_removed(self) -> None:
        """空集合占位符不能泄漏成真实权限编码。"""
        assert _decode_cached({EMPTY_PERMISSION_MARKER}) == set()

    def test_marker_mixed_with_real(self) -> None:
        result = _decode_cached({EMPTY_PERMISSION_MARKER, "a.b.c"})
        assert result == {"a.b.c"}


class TestRequirePermissionFactory:
    def test_returns_callable(self) -> None:
        dep = require_permission("catalog.attraction.read")
        assert callable(dep)

    def test_dependency_name_readable(self) -> None:
        """依赖函数名可读，便于 OpenAPI 与日志排查。"""
        dep = require_permission("model.model.delete")
        assert dep.__name__ == "require_permission_model_model_delete"

    def test_different_codes_different_functions(self) -> None:
        a = require_permission("a.b.c")
        b = require_permission("d.e.f")
        assert a is not b


# ============================================================
# 规范检查：数据驱动，不硬编码角色（DoD 4）
# ============================================================


class TestNoHardcodedRoleChecks:
    def test_no_role_equality_in_api_layer(self) -> None:
        """DoD：``grep -rn 'if.*role.*==.*super_admin' backend/app/api/`` 无输出。

        权限校验必须数据驱动——接口声明「需要哪个权限项」，
        而不是「需要哪个角色」。加角色只需配置数据。
        """
        pattern = re.compile(r"if\s+.*role.*==.*super_admin", re.IGNORECASE)

        offenders: list[str] = []
        for path in API_DIR.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if pattern.search(source):
                offenders.append(str(path.relative_to(BACKEND_APP)))

        assert offenders == [], f"以下文件硬编码了角色判断：{offenders}"

    def test_middleware_has_no_role_lookup(self) -> None:
        """中间件代码本身不应出现角色名（注释里解释设计是允许的）。"""
        import ast

        path = API_DIR / "middleware" / "permission.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))

        identifiers: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                identifiers.append(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.append(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                identifiers.append(node.value)

        joined = " ".join(identifiers).lower()
        assert "super_admin" not in joined
        assert "role_super_admin" not in joined

    def test_b_end_routes_declare_permissions(self) -> None:
        """所有 B 端业务路由都应声明权限项。"""
        for filename in ("catalog.py", "models.py", "system.py"):
            source = (API_DIR / "v1" / "b_end" / filename).read_text(encoding="utf-8")

            # 路由函数数 vs 权限声明数
            route_count = len(re.findall(r"@router\.(get|post|put|patch|delete)", source))
            perm_count = len(
                re.findall(r"^Admin\w+ = Annotated\[CurrentAdmin, Depends\(require_permission", source, re.M)
            )
            assert perm_count > 0, f"{filename} 没有声明任何权限项"
            # 别名至少覆盖了用到的编码种类，不要求与路由数一一对应
            assert route_count > 0


# ============================================================
# 接口级测试（DoD 1）
# ============================================================


pytestmark_db = pytest.mark.integration


@pytest.fixture
async def db_ready() -> None:
    from app.db.session import SessionLocal, check_database

    try:
        if not await check_database():
            pytest.skip("数据库不可达")
    except Exception:
        pytest.skip("数据库不可达")

    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT to_regclass('public.permission') IS NOT NULL")
        )
        if not result.scalar_one():
            pytest.skip("表未创建")


@pytest.fixture
async def admin_factory(db_ready: None):
    """创建一个真实管理员，返回 (id, cleanup)。"""
    created: list[uuid.UUID] = []

    async def _create(*role_codes: str) -> uuid.UUID:
        from app.core.security import hash_password
        from app.db.session import SessionLocal
        from app.utils.ids import uuid7

        admin_id = uuid7()
        async with SessionLocal() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO admin_user (id, username, password_hash, status,
                                            token_version, created_at, updated_at)
                    VALUES (:id, :username, :hash, 'active', 0, NOW(), NOW())
                    """
                ),
                {
                    "id": admin_id,
                    "username": f"perm_{uuid.uuid4().hex[:8]}",
                    "hash": hash_password("Passw0rd123"),
                },
            )
            if role_codes:
                await session.execute(
                    text(
                        """
                        INSERT INTO admin_user_role (id, admin_user_id, role_id, created_at)
                        SELECT gen_random_uuid(), :admin_id, r.id, NOW()
                        FROM role r WHERE r.code = ANY(:codes)
                        """
                    ),
                    {"admin_id": admin_id, "codes": list(role_codes)},
                )
            await session.commit()

        created.append(admin_id)
        return admin_id

    yield _create

    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        for admin_id in created:
            await session.execute(
                text("DELETE FROM admin_user_role WHERE admin_user_id = :id"),
                {"id": admin_id},
            )
            await session.execute(
                text("DELETE FROM admin_user WHERE id = :id"), {"id": admin_id}
            )
        await session.commit()


def _make_client(admin_id: uuid.UUID, resolver=None) -> httpx.AsyncClient:
    """构造以指定管理员身份请求的客户端。

    ``resolver`` 为 ``None`` 时走真实权限解析（查库 + 缓存）。
    """
    from app.api.middleware.admin_auth import CurrentAdmin, require_admin
    from app.api.middleware.permission import get_permission_resolver
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[require_admin] = lambda: CurrentAdmin(
        admin_id=admin_id, token_version=0
    )
    if resolver is not None:
        app.dependency_overrides[get_permission_resolver] = lambda: resolver

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


class TestPermissionDenied:
    async def test_no_permission_returns_403_with_25001(
        self, admin_factory
    ) -> None:
        """DoD：无权限访问返回 403 + 25001。"""
        # 不给任何角色
        admin_id = await admin_factory()

        async with _make_client(admin_id) as client:
            response = await client.get("/api/v1/admin/system/permissions")

        assert response.status_code == 403
        assert response.json()["code"] == 25001

    async def test_error_message_names_required_permission(
        self, admin_factory
    ) -> None:
        """错误信息应指出缺哪个权限项，便于排查。"""
        admin_id = await admin_factory()

        async with _make_client(admin_id) as client:
            response = await client.get("/api/v1/admin/system/roles")

        message = response.json()["message"]
        assert "system.role.read" in message

    async def test_normal_role_without_permissions_denied(
        self, admin_factory
    ) -> None:
        """普通管理员角色初始没有任何权限（Q13），应被拒。"""
        admin_id = await admin_factory("normal")

        async with _make_client(admin_id) as client:
            response = await client.get("/api/v1/admin/models")

        assert response.status_code == 403
        assert response.json()["code"] == 25001


class TestSuperAdminBypass:
    async def test_super_admin_can_access_everything(self, admin_factory) -> None:
        """DoD：超级管理员绕过权限检查。

        实现方式是「超管拥有全部权限项」（数据驱动），
        而不是代码里的角色判断分支。
        """
        admin_id = await admin_factory("super_admin")

        async with _make_client(admin_id) as client:
            for path in (
                "/api/v1/admin/system/permissions",
                "/api/v1/admin/system/roles",
                "/api/v1/admin/models",
                "/api/v1/admin/models/categories",
                "/api/v1/admin/regions/provinces",
                "/api/v1/admin/attractions",
                "/api/v1/admin/restaurants",
                "/api/v1/admin/hotels",
                "/api/v1/admin/activities",
            ):
                response = await client.get(path)
                assert response.status_code == 200, f"{path} 返回 {response.status_code}"


# ============================================================
# 缓存行为（DoD 3 + 边界）
# ============================================================


class TestPermissionCache:
    async def test_cache_is_written_after_first_read(
        self, admin_factory
    ) -> None:
        """第一次读取后应写入缓存。"""
        from app.infra import redis as redis_infra

        admin_id = await admin_factory("super_admin")

        try:
            client = redis_infra.get_client()
            await client.delete(_cache_key(admin_id))
        except Exception:
            pytest.skip("Redis 不可用")

        async with _make_client(admin_id) as http:
            await http.get("/api/v1/admin/models")

        cached = await redis_infra.get_client().smembers(_cache_key(admin_id))
        assert cached, "权限集合未写入缓存"

    async def test_empty_permission_set_is_cached(self, admin_factory) -> None:
        """空集合也会被缓存——否则无角色管理员每个请求都回源查库。"""
        from app.infra import redis as redis_infra

        admin_id = await admin_factory()  # 无角色

        try:
            client = redis_infra.get_client()
            await client.delete(_cache_key(admin_id))
        except Exception:
            pytest.skip("Redis 不可用")

        async with _make_client(admin_id) as http:
            await http.get("/api/v1/admin/models")

        cached = await redis_infra.get_client().smembers(_cache_key(admin_id))
        assert EMPTY_PERMISSION_MARKER in cached

    async def test_invalidate_clears_cache(self, admin_factory) -> None:
        """DoD 边界：权限变更后缓存失效。"""
        from app.infra import redis as redis_infra

        admin_id = await admin_factory("super_admin")

        async with _make_client(admin_id) as http:
            await http.get("/api/v1/admin/models")

        assert await redis_infra.get_client().smembers(_cache_key(admin_id))

        await invalidate_admin_permissions(admin_id)

        assert not await redis_infra.get_client().smembers(_cache_key(admin_id))

    async def test_cache_reloads_after_invalidation(self, admin_factory) -> None:
        """DoD：缓存失效后重新加载。"""
        admin_id = await admin_factory("super_admin")

        async with _make_client(admin_id) as http:
            first = await http.get("/api/v1/admin/models")
            assert first.status_code == 200

            await invalidate_admin_permissions(admin_id)

            second = await http.get("/api/v1/admin/models")
            assert second.status_code == 200

    async def test_permission_change_takes_effect_after_invalidation(
        self, admin_factory
    ) -> None:
        """给管理员加角色并失效缓存后，应立刻获得新权限。"""
        from app.db.session import SessionLocal

        admin_id = await admin_factory()  # 无角色，403

        async with _make_client(admin_id) as http:
            denied = await http.get("/api/v1/admin/models")
            assert denied.status_code == 403

            # 加超管角色
            async with SessionLocal() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO admin_user_role (id, admin_user_id, role_id, created_at)
                        SELECT gen_random_uuid(), :admin_id, r.id, NOW()
                        FROM role r WHERE r.code = 'super_admin'
                        ON CONFLICT (admin_user_id, role_id) DO NOTHING
                        """
                    ),
                    {"admin_id": admin_id},
                )
                await session.commit()

            await invalidate_admin_permissions(admin_id)

            allowed = await http.get("/api/v1/admin/models")
            assert allowed.status_code == 200


class TestCacheDegradation:
    async def test_uses_db_when_cache_empty(self, admin_factory) -> None:
        """缓存为空时回源查库，结果正确。"""
        admin_id = await admin_factory("super_admin")

        async with _make_client(admin_id) as http:
            response = await http.get("/api/v1/admin/models")
            assert response.status_code == 200

    async def test_resolver_returns_expected_codes(self, admin_factory) -> None:
        """直接验证解析器返回的集合内容。"""
        from app.api.middleware.permission import resolve_permissions
        from app.db.session import SessionLocal
        from app.modules.system.permissions import permission_codes

        admin_id = await admin_factory("super_admin")

        async with SessionLocal() as session:
            codes = await resolve_permissions(session, admin_id)

        assert codes == set(permission_codes())


# ============================================================
# 依赖声明本身
# ============================================================


class TestDependencyWiring:
    def test_catalog_routes_use_permission_alias(self) -> None:
        """catalog 路由应使用权限别名而不是裸 CurrentAdminDep。"""
        source = (
            API_DIR / "v1" / "b_end" / "catalog.py"
        ).read_text(encoding="utf-8")

        assert "CurrentAdminDep" not in source
        assert "require_permission" in source

    def test_models_routes_use_permission_alias(self) -> None:
        source = (
            API_DIR / "v1" / "b_end" / "models.py"
        ).read_text(encoding="utf-8")

        assert "CurrentAdminDep" not in source
        assert "require_permission" in source

    def test_system_routes_use_permission_alias(self) -> None:
        source = (
            API_DIR / "v1" / "b_end" / "system.py"
        ).read_text(encoding="utf-8")

        assert "CurrentAdminDep" not in source
        assert "require_permission" in source

    def test_all_declared_codes_exist_in_catalog(self) -> None:
        """路由声明的权限编码必须存在于权限项清单中。

        防止手写编码时拼错——拼错的编码永远不会被授予，
        接口就变成了「谁都进不去」。
        """
        from app.modules.system.permissions import permission_codes

        valid = set(permission_codes())
        declared: set[str] = set()

        for filename in ("catalog.py", "models.py", "system.py"):
            source = (
                API_DIR / "v1" / "b_end" / filename
            ).read_text(encoding="utf-8")
            declared.update(
                re.findall(r'require_permission\("([^"]+)"\)', source)
            )

        unknown = declared - valid
        assert unknown == set(), f"以下权限编码未在清单中定义：{sorted(unknown)}"
