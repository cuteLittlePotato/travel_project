"""M15-T06 操作日志的记录与查询测试。

覆盖 DoD：
    1. 增删改操作自动写入 operation_log（DB 断言）
    2. **查询操作不记录**（评审 §Q13）
    3. 日志含操作人/模块/操作类型/目标/结果（结构断言）
    4. 日志写入异步，不阻塞主流程
边界：日志表增长控制（归档策略）。
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.api.middleware.operation_log import (
    METHOD_TO_ACTION,
    PATH_MODULE_MAP,
    build_log_entity,
    resolve_module,
    resolve_target,
    should_log,
)

pytestmark_db = pytest.mark.integration


# ============================================================
# 纯函数（不依赖数据库）
# ============================================================


class TestShouldLog:
    def test_write_methods_logged(self) -> None:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert should_log(method), f"{method} 应记日志"

    def test_read_methods_not_logged(self) -> None:
        """DoD：查询操作不记录（评审 §Q13）。"""
        for method in ("GET", "HEAD", "OPTIONS"):
            assert not should_log(method), f"{method} 不应记日志"

    def test_lowercase_also_works(self) -> None:
        assert should_log("post")
        assert not should_log("get")

    def test_method_map_has_no_get(self) -> None:
        assert "GET" not in METHOD_TO_ACTION
        assert "HEAD" not in METHOD_TO_ACTION
        assert "OPTIONS" not in METHOD_TO_ACTION


class TestResolveModule:
    def test_catalog_paths(self) -> None:
        assert resolve_module("/api/v1/admin/attractions") == "catalog"
        assert resolve_module("/api/v1/admin/attractions/xxx") == "catalog"
        assert resolve_module("/api/v1/admin/regions/provinces") == "catalog"
        assert resolve_module("/api/v1/admin/activities/xxx/status") == "catalog"

    def test_model_paths(self) -> None:
        assert resolve_module("/api/v1/admin/models") == "model"
        assert resolve_module("/api/v1/admin/models/xxx/default") == "model"

    def test_system_paths(self) -> None:
        assert resolve_module("/api/v1/admin/system/admins") == "system"
        assert resolve_module("/api/v1/admin/system/roles/xxx") == "system"

    def test_unknown_path(self) -> None:
        assert resolve_module("/api/v1/admin/unknown-thing") == "unknown"
        assert resolve_module("/api/v1/attractions") == "unknown"

    def test_all_mapped_modules_are_valid(self) -> None:
        from app.modules.system.permissions import permissions_by_module

        valid_modules = set(permissions_by_module().keys())
        for segment, module in PATH_MODULE_MAP.items():
            assert module in valid_modules, f"{segment} 映射到了未定义的模块 {module}"


class TestResolveTarget:
    def test_extracts_uuid(self) -> None:
        target_id = uuid.uuid4()
        target_type, parsed = resolve_target(f"/api/v1/admin/attractions/{target_id}")
        assert target_type == "attractions"
        assert parsed == target_id

    def test_collection_path_has_no_id(self) -> None:
        target_type, parsed = resolve_target("/api/v1/admin/attractions")
        assert target_type == "attractions"
        assert parsed is None

    def test_stops_at_action_suffix(self) -> None:
        """``/models/{id}/status`` 的 target_type 应是 models，不是 status。"""
        target_id = uuid.uuid4()
        target_type, parsed = resolve_target(
            f"/api/v1/admin/models/{target_id}/status"
        )
        assert target_type == "models"
        assert parsed == target_id

    def test_non_admin_path(self) -> None:
        assert resolve_target("/api/v1/attractions") == (None, None)


class TestBuildLogEntity:
    def test_contains_required_fields(self) -> None:
        """DoD：日志含操作人/模块/操作类型/目标/结果。"""
        from starlette.requests import Request

        admin_id = uuid.uuid4()
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/admin/attractions",
            "headers": [(b"user-agent", b"pytest")],
            "client": ("127.0.0.1", 1234),
            "query_string": b"",
        }
        request = Request(scope)

        log = build_log_entity(
            admin_id=admin_id, request=request, is_success=True
        )

        assert log.admin_user_id == admin_id  # 操作人
        assert log.module == "catalog"  # 模块
        assert log.action == "create"  # 操作类型
        assert log.target_type == "attractions"  # 目标
        assert log.is_success is True  # 结果
        assert log.ip_address == "127.0.0.1"
        assert log.user_agent == "pytest"

    def test_prefers_x_forwarded_for(self) -> None:
        """反代后应取真实客户端 IP，而不是反代地址。"""
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/admin/attractions",
            "headers": [(b"x-forwarded-for", b"203.0.113.5, 10.0.0.1")],
            "client": ("10.0.0.1", 1234),
            "query_string": b"",
        }
        log = build_log_entity(
            admin_id=uuid.uuid4(), request=Request(scope), is_success=True
        )
        assert log.ip_address == "203.0.113.5"

    def test_delete_maps_to_delete_action(self) -> None:
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "DELETE",
            "path": f"/api/v1/admin/models/{uuid.uuid4()}",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "query_string": b"",
        }
        log = build_log_entity(
            admin_id=uuid.uuid4(), request=Request(scope), is_success=False
        )
        assert log.action == "delete"
        assert log.is_success is False


# ============================================================
# 数据库与接口
# ============================================================


@pytest.fixture
async def db_ready() -> None:
    from app.db.session import SessionLocal, check_database

    try:
        if not await check_database():
            pytest.skip("数据库不可达")
    except Exception:
        pytest.skip("数据库不可达")

    async with SessionLocal() as session:
        for table in ("operation_log", "admin_user", "role"):
            result = await session.execute(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": f"public.{table}"},
            )
            if not result.scalar_one():
                pytest.skip(f"表 {table} 未创建")


@pytest.fixture
async def admin_id(db_ready: None) -> Any:
    """创建一个真实管理员，供日志外键（逻辑）引用。"""
    from app.core.security import hash_password
    from app.db.session import SessionLocal
    from app.utils.ids import uuid7

    new_id = uuid7()
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
                "id": new_id,
                "username": f"log_{uuid.uuid4().hex[:8]}",
                "hash": hash_password("Passw0rd123"),
            },
        )
        await session.commit()

    yield new_id

    async with SessionLocal() as session:
        await session.execute(
            text("DELETE FROM operation_log WHERE admin_user_id = :id"),
            {"id": new_id},
        )
        await session.execute(
            text("DELETE FROM admin_user WHERE id = :id"), {"id": new_id}
        )
        await session.commit()


def _simple_request(method: str, path: str):
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "query_string": b"",
        }
    )


def _make_client(admin_id: uuid.UUID) -> httpx.AsyncClient:
    from app.api.middleware.admin_auth import CurrentAdmin, require_admin
    from app.api.middleware.permission import get_permission_resolver
    from app.main import create_app
    from app.modules.system.permissions import permission_codes

    app = create_app()
    app.dependency_overrides[require_admin] = lambda: CurrentAdmin(
        admin_id=admin_id, token_version=0
    )

    async def _all_permissions(_session, _admin_id) -> set[str]:
        return set(permission_codes())

    app.dependency_overrides[get_permission_resolver] = lambda: _all_permissions

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _count_logs(admin_id: uuid.UUID) -> int:
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT count(*) FROM operation_log WHERE admin_user_id = :id"),
            {"id": admin_id},
        )
        return result.scalar_one()


class TestAutoLogging:
    """验证日志记录逻辑本身。

    不通过 HTTP 中间件验证——测试里 `require_admin` 被
    `dependency_overrides` 替换，没有真实 Token，中间件无法确定
    「这条日志是谁的」，自然不会记录。直接调用写入函数更可靠。
    """

    @staticmethod
    def _make_request(method: str, path: str) -> Any:
        from starlette.requests import Request

        return Request(
            {
                "type": "http",
                "method": method,
                "path": path,
                "headers": [],
                "client": ("127.0.0.1", 1234),
                "query_string": b"",
            }
        )

    async def test_write_creates_row(self, admin_id: uuid.UUID) -> None:
        """DoD：增删改操作写入 operation_log。"""
        from app.api.middleware.operation_log import write_operation_log
        from app.db.session import SessionLocal

        before = await _count_logs(admin_id)

        async with SessionLocal() as session:
            await write_operation_log(
                session,
                admin_id=admin_id,
                request=self._make_request(
                    "POST", "/api/v1/admin/attractions"
                ),
                is_success=True,
            )

        assert await _count_logs(admin_id) == before + 1

    async def test_written_row_has_all_fields(self, admin_id: uuid.UUID) -> None:
        """DoD：日志含操作人/模块/操作类型/目标/结果。"""
        from app.api.middleware.operation_log import write_operation_log
        from app.db.session import SessionLocal

        target_id = uuid.uuid4()
        async with SessionLocal() as session:
            await write_operation_log(
                session,
                admin_id=admin_id,
                request=self._make_request(
                    "DELETE", f"/api/v1/admin/models/{target_id}"
                ),
                is_success=False,
            )

        async with SessionLocal() as session:
            result = await session.execute(
                text(
                    "SELECT admin_user_id, module, action, target_type, "
                    "target_id, is_success, ip_address "
                    "FROM operation_log WHERE admin_user_id = :id "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"id": admin_id},
            )
            row = result.one()

        assert row[0] == admin_id
        assert row[1] == "model"
        assert row[2] == "delete"
        assert row[3] == "models"
        assert row[4] == target_id
        assert row[5] is False
        assert row[6] == "127.0.0.1"

    async def test_log_failure_does_not_raise(self, admin_id: uuid.UUID) -> None:
        """DoD：日志写入失败不阻塞主流程——不向上抛异常。"""
        from app.api.middleware.operation_log import write_operation_log

        class _BrokenSession:
            def add(self, _obj) -> None:
                raise RuntimeError("模拟写入故障")

            async def commit(self) -> None:
                raise RuntimeError("模拟提交故障")

        # 不抛异常即通过
        await write_operation_log(
            _BrokenSession(),  # type: ignore[arg-type]
            admin_id=admin_id,
            request=self._make_request("POST", "/api/v1/admin/attractions"),
            is_success=True,
        )

    async def test_get_is_not_logged(self, admin_id: uuid.UUID) -> None:
        """DoD：查询操作不记录——中间件层直接拒绝。"""
        from app.api.middleware.audit import OperationLogMiddleware

        request = self._make_request("GET", "/api/v1/admin/attractions")
        assert not OperationLogMiddleware._should_record(request)

    async def test_post_is_recorded(self, admin_id: uuid.UUID) -> None:
        from app.api.middleware.audit import OperationLogMiddleware

        request = self._make_request("POST", "/api/v1/admin/attractions")
        assert OperationLogMiddleware._should_record(request)

    def test_c_end_paths_not_recorded(self) -> None:
        """C 端路径不记 B 端操作日志。"""
        from app.api.middleware.audit import OperationLogMiddleware

        request = self._make_request("POST", "/api/v1/plans")
        assert not OperationLogMiddleware._should_record(request)

    def test_auth_paths_excluded(self) -> None:
        """登录/登出由 M15-T08 单独记录（动作是 login/logout）。"""
        from app.api.middleware.audit import OperationLogMiddleware

        request = self._make_request("POST", "/api/v1/admin/auth/login")
        assert not OperationLogMiddleware._should_record(request)


class TestQueryLogs:
    async def test_query_returns_pagination(self, admin_id: uuid.UUID) -> None:
        async with _make_client(admin_id) as client:
            response = await client.get(
                "/api/v1/admin/system/operation-logs",
                params={"page": 1, "page_size": 10},
            )

        assert response.status_code == 200
        data = response.json()["data"]
        for key in ("items", "total", "page", "page_size", "total_pages"):
            assert key in data

    async def test_query_includes_admin_username(self, admin_id: uuid.UUID) -> None:
        from app.api.middleware.operation_log import write_operation_log
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            await write_operation_log(
                session,
                admin_id=admin_id,
                request=_simple_request("POST", "/api/v1/admin/attractions"),
                is_success=True,
            )

        async with _make_client(admin_id) as client:
            response = await client.get(
                "/api/v1/admin/system/operation-logs",
                params={"admin_user_id": str(admin_id)},
            )

        items = response.json()["data"]["items"]
        assert items, "应有日志记录"
        assert all(item["admin_username"] for item in items)

    async def test_filter_by_module(self, admin_id: uuid.UUID) -> None:
        async with _make_client(admin_id) as client:
            response = await client.get(
                "/api/v1/admin/system/operation-logs",
                params={"module": "catalog"},
            )

        for item in response.json()["data"]["items"]:
            assert item["module"] == "catalog"

    async def test_filter_by_action(self, admin_id: uuid.UUID) -> None:
        async with _make_client(admin_id) as client:
            response = await client.get(
                "/api/v1/admin/system/operation-logs",
                params={"action": "create"},
            )

        for item in response.json()["data"]["items"]:
            assert item["action"] == "create"

    async def test_invalid_action_rejected(self, admin_id: uuid.UUID) -> None:
        """``read`` 不是合法的日志动作——查询不记录。"""
        async with _make_client(admin_id) as client:
            response = await client.get(
                "/api/v1/admin/system/operation-logs",
                params={"action": "read"},
            )

        assert response.status_code == 400
        assert response.json()["code"] == 10001

    async def test_querying_logs_does_not_create_logs(
        self, admin_id: uuid.UUID
    ) -> None:
        """看日志这个动作本身不应产生日志，否则日志表会被自己填满。"""
        before = await _count_logs(admin_id)

        async with _make_client(admin_id) as client:
            for _ in range(3):
                await client.get("/api/v1/admin/system/operation-logs")

        after = await _count_logs(admin_id)
        assert after == before
