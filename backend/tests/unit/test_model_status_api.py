"""M12-T03 启用/禁用/默认接口的测试。

覆盖 DoD：
    1. 禁用默认模型 → 22003（409）
    2. 禁用被知识库引用的模型 → 22004（409）
    3. 设为默认时模型必须启用，否则 22005（400）
    4. 设默认后同类别原默认 is_default=false（DB 断言）
边界：并发设置默认（部分唯一索引保证）。
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


# ============================================================
# 夹具
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
        for table in ("model", "knowledge_base"):
            result = await session.execute(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": f"public.{table}"},
            )
            if not result.scalar_one():
                pytest.skip(f"表 {table} 未创建（先执行 alembic upgrade head）")


@pytest.fixture
async def client(db_ready: None) -> httpx.AsyncClient:
    from app.api.middleware.admin_auth import CurrentAdmin, require_admin
    from app.api.middleware.permission import get_permission_resolver
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[require_admin] = lambda: CurrentAdmin(
        admin_id=uuid.uuid4(), token_version=0
    )

    # M15-T05 之后 B 端接口需要权限项。测试统一按「拥有全部权限」放行，
    # 权限校验本身的行为由 test_permission_middleware.py 单独覆盖。
    # 注意返回的是真实权限编码集合，中间件没有通配符分支。
    # get_permission_resolver 是**工厂**：它的返回值才是真正的 resolver。
    # 直接覆盖它为 async 函数会被 FastAPI 当成依赖去解析参数（400）。
    # 因此覆盖成「返回全权 resolver 的同步函数」。
    from app.modules.system.permissions import permission_codes

    async def _all_permissions(_session, _admin_id) -> set[str]:
        return set(permission_codes())

    app.dependency_overrides[get_permission_resolver] = lambda: _all_permissions
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def cleanup() -> Any:
    created = {"models": [], "knowledge_bases": []}
    yield created

    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        for kb_id in created["knowledge_bases"]:
            await session.execute(
                text("DELETE FROM knowledge_base WHERE id = :id"), {"id": kb_id}
            )
        for model_id in created["models"]:
            await session.execute(
                text("DELETE FROM model WHERE id = :id"), {"id": model_id}
            )
        await session.commit()


def _unique(prefix: str = "m") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _create(
    client: httpx.AsyncClient, cleanup: dict, **overrides: Any
) -> dict:
    payload = {
        "name": f"测试模型 {_unique()}",
        "category": "chat",
        "model_code": _unique("code"),
        "base_url": "https://api.example.com/v1",
        "max_context_tokens": 128000,
        **overrides,
    }
    response = await client.post("/api/v1/admin/models", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    cleanup["models"].append(data["id"])
    return data


async def _create_kb_referencing(
    cleanup: dict,
    model_id: str,
    *,
    as_rerank: bool = False,
    embedding_model_id: str | None = None,
) -> str:
    """直接插入一条引用该模型的知识库记录。

    ``knowledge_base`` 的完整 CRUD 在 M09，这里只需要一条引用数据
    来验证 M12 的引用检查，因此直接写库。

    ``embedding_model_id`` 是 NOT NULL，测 rerank 引用时必须显式传入
    一个 embedding 模型 ID（可以是任意 UUID，引用检查不关心它是否存在）。
    """
    from sqlalchemy import text as sa_text

    from app.db.session import SessionLocal
    from app.utils.ids import uuid7

    kb_id = uuid7()
    async with SessionLocal() as session:
        await session.execute(
            sa_text(
                """
                INSERT INTO knowledge_base (
                    id, name, separator_config,
                    embedding_model_id, rerank_model_id, created_by
                ) VALUES (
                    :id, :name, :sep,
                    :embedding_id, :rerank_id, :created_by
                )
                """
            ),
            {
                "id": kb_id,
                "name": f"测试知识库 {_unique('kb')}",
                "sep": "[]",
                "embedding_id": embedding_model_id
                if embedding_model_id is not None
                else (None if as_rerank else model_id),
                "rerank_id": model_id if as_rerank else None,
                "created_by": uuid7(),
            },
        )
        await session.commit()

    cleanup["knowledge_bases"].append(str(kb_id))
    return str(kb_id)


# ============================================================
# 启用 / 禁用（DoD 1 + 2）
# ============================================================


class TestUpdateStatus:
    async def test_disable_returns_204(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        model = await _create(client, cleanup)

        response = await client.patch(
            f"/api/v1/admin/models/{model['id']}/status",
            json={"is_enabled": False},
        )
        assert response.status_code == 204

        detail = await client.get(f"/api/v1/admin/models/{model['id']}")
        assert detail.json()["data"]["is_enabled"] is False

    async def test_enable_returns_204(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        model = await _create(client, cleanup, is_enabled=False)

        response = await client.patch(
            f"/api/v1/admin/models/{model['id']}/status",
            json={"is_enabled": True},
        )
        assert response.status_code == 204

    async def test_disable_default_returns_22003(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """DoD：禁用默认模型 → 22003（409）。"""
        model = await _create(client, cleanup, is_default=True)
        assert model["is_default"] is True

        response = await client.patch(
            f"/api/v1/admin/models/{model['id']}/status",
            json={"is_enabled": False},
        )

        assert response.status_code == 409
        assert response.json()["code"] == 22003

    async def test_disable_referenced_returns_22004(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """DoD：禁用被知识库引用的模型 → 22004（409）。"""
        model = await _create(
            client, cleanup, category="embedding", max_context_tokens=None
        )
        await _create_kb_referencing(cleanup, model["id"])

        response = await client.patch(
            f"/api/v1/admin/models/{model['id']}/status",
            json={"is_enabled": False},
        )

        assert response.status_code == 409
        assert response.json()["code"] == 22004

    async def test_disable_referenced_as_rerank_returns_22004(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """引用检查要覆盖 rerank_model_id 字段。"""
        model = await _create(
            client, cleanup, category="rerank", max_context_tokens=None
        )
        embedding = await _create(
            client, cleanup, category="embedding", max_context_tokens=None
        )
        await _create_kb_referencing(
            cleanup,
            model["id"],
            as_rerank=True,
            embedding_model_id=embedding["id"],
        )

        response = await client.patch(
            f"/api/v1/admin/models/{model['id']}/status",
            json={"is_enabled": False},
        )

        assert response.status_code == 409
        assert response.json()["code"] == 22004

    async def test_enable_referenced_allowed(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """启用不设限制——启用只会让模型可用，不破坏任何关系。"""
        model = await _create(
            client, cleanup, category="embedding", max_context_tokens=None
        )
        await _create_kb_referencing(cleanup, model["id"])

        response = await client.patch(
            f"/api/v1/admin/models/{model['id']}/status",
            json={"is_enabled": True},
        )
        assert response.status_code == 204

    async def test_status_nonexistent_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.patch(
            f"/api/v1/admin/models/{uuid.uuid4()}/status",
            json={"is_enabled": False},
        )
        assert response.status_code == 404
        assert response.json()["code"] == 22007

    async def test_missing_is_enabled_rejected(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        model = await _create(client, cleanup)

        response = await client.patch(
            f"/api/v1/admin/models/{model['id']}/status", json={}
        )
        assert response.status_code == 400
        assert response.json()["code"] == 10001


# ============================================================
# 设置默认（DoD 3 + 4）
# ============================================================


class TestSetDefault:
    async def test_set_default_returns_204(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        model = await _create(client, cleanup)

        response = await client.put(f"/api/v1/admin/models/{model['id']}/default")
        assert response.status_code == 204

        detail = await client.get(f"/api/v1/admin/models/{model['id']}")
        assert detail.json()["data"]["is_default"] is True

    async def test_disabled_model_returns_22005(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """DoD：设为默认时模型必须启用，否则 22005（400）。

        创建接口不接受 ``is_enabled``（新建即启用，API §10.2），
        因此先创建再禁用。
        """
        model = await _create(client, cleanup)
        await client.patch(
            f"/api/v1/admin/models/{model['id']}/status",
            json={"is_enabled": False},
        )

        response = await client.put(f"/api/v1/admin/models/{model['id']}/default")

        assert response.status_code == 400
        assert response.json()["code"] == 22005

    async def test_previous_default_cleared(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """DoD：设默认后同类别原默认 is_default=false（DB 断言）。"""
        first = await _create(client, cleanup, is_default=True)
        second = await _create(client, cleanup, model_code=_unique("code"))

        response = await client.put(f"/api/v1/admin/models/{second['id']}/default")
        assert response.status_code == 204

        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            result = await session.execute(
                text(
                    "SELECT id, is_default FROM model "
                    "WHERE id IN (:a, :b) ORDER BY id"
                ),
                {"a": first["id"], "b": second["id"]},
            )
            rows = {str(row[0]): row[1] for row in result.all()}

        assert rows[first["id"]] is False
        assert rows[second["id"]] is True

    async def test_only_one_default_per_category(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """反复切换默认，任何时刻同类别只有一个 is_default=TRUE。"""
        models = [
            await _create(client, cleanup, model_code=_unique("code"))
            for _ in range(3)
        ]

        for model in models:
            await client.put(f"/api/v1/admin/models/{model['id']}/default")

            from app.db.session import SessionLocal

            async with SessionLocal() as session:
                result = await session.execute(
                    text(
                        "SELECT count(*) FROM model "
                        "WHERE category = 'chat' AND is_default = TRUE"
                    )
                )
                assert result.scalar_one() == 1

    async def test_set_default_twice_idempotent(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """已经是默认时重复调用应幂等成功。"""
        model = await _create(client, cleanup)

        first = await client.put(f"/api/v1/admin/models/{model['id']}/default")
        second = await client.put(f"/api/v1/admin/models/{model['id']}/default")

        assert first.status_code == 204
        assert second.status_code == 204

    async def test_nonexistent_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.put(f"/api/v1/admin/models/{uuid.uuid4()}/default")
        assert response.status_code == 404
        assert response.json()["code"] == 22007

    async def test_default_of_other_category_untouched(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """设默认只影响同类别，不能把别的类别的默认清掉。"""
        chat_default = await _create(client, cleanup, category="chat", is_default=True)
        ocr_model = await _create(
            client, cleanup, category="ocr", max_context_tokens=None
        )

        await client.put(f"/api/v1/admin/models/{ocr_model['id']}/default")

        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            result = await session.execute(
                text("SELECT is_default FROM model WHERE id = :id"),
                {"id": chat_default["id"]},
            )
            assert result.scalar_one() is True


# ============================================================
# 删除保护（T03 顺带覆盖，完整规则在 T04）
# ============================================================


class TestDeleteProtection:
    async def test_delete_default_returns_22003(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        model = await _create(client, cleanup, is_default=True)

        response = await client.delete(f"/api/v1/admin/models/{model['id']}")

        assert response.status_code == 409
        assert response.json()["code"] == 22003

    async def test_delete_referenced_returns_22006(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """DoD（T04）：被知识库引用返回 22006（409）。"""
        model = await _create(
            client, cleanup, category="embedding", max_context_tokens=None
        )
        await _create_kb_referencing(cleanup, model["id"])

        response = await client.delete(f"/api/v1/admin/models/{model['id']}")

        assert response.status_code == 409
        assert response.json()["code"] == 22006
