"""M12-T04 模型删除保护的测试。

覆盖 DoD：
    1. 被知识库引用返回 22006（409）
    2. 是类别默认返回 22003（409）
    3. 删除后 model_call_log 记录保留（不级联）（DB 断言）
边界：引用检查需覆盖 knowledge_base.embedding_model_id 与 rerank_model_id。
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
        for table in ("model", "model_call_log", "knowledge_base"):
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
    created = {"models": [], "knowledge_bases": [], "logs": []}
    yield created

    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        for log_id in created["logs"]:
            await session.execute(
                text("DELETE FROM model_call_log WHERE id = :id"), {"id": log_id}
            )
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


async def _create_kb(
    cleanup: dict, *, embedding_model_id: str, rerank_model_id: str | None = None
) -> str:
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
                ) VALUES (:id, :name, :sep, :embedding_id, :rerank_id, :created_by)
                """
            ),
            {
                "id": kb_id,
                "name": f"测试知识库 {_unique('kb')}",
                "sep": "[]",
                "embedding_id": embedding_model_id,
                "rerank_id": rerank_model_id,
                "created_by": uuid7(),
            },
        )
        await session.commit()

    cleanup["knowledge_bases"].append(str(kb_id))
    return str(kb_id)


async def _create_call_log(cleanup: dict, model_id: str) -> str:
    from sqlalchemy import text as sa_text

    from app.db.session import SessionLocal
    from app.utils.ids import uuid7

    log_id = uuid7()
    async with SessionLocal() as session:
        await session.execute(
            sa_text(
                """
                INSERT INTO model_call_log (
                    id, model_id, caller_type, token_input, token_output, is_success
                ) VALUES (:id, :model_id, 'user_chat', 100, 50, TRUE)
                """
            ),
            {"id": log_id, "model_id": model_id},
        )
        await session.commit()

    cleanup["logs"].append(str(log_id))
    return str(log_id)


# ============================================================
# DoD 1：被知识库引用 → 22006
# ============================================================


class TestReferencedByKnowledgeBase:
    async def test_embedding_reference_blocks_delete(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """DoD：被知识库引用（embedding_model_id）→ 22006（409）。"""
        embedding = await _create(
            client, cleanup, category="embedding", max_context_tokens=None
        )
        await _create_kb(cleanup, embedding_model_id=embedding["id"])

        response = await client.delete(f"/api/v1/admin/models/{embedding['id']}")

        assert response.status_code == 409
        assert response.json()["code"] == 22006

        # 模型仍在
        detail = await client.get(f"/api/v1/admin/models/{embedding['id']}")
        assert detail.status_code == 200

    async def test_rerank_reference_blocks_delete(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """DoD 边界：引用检查覆盖 rerank_model_id。"""
        embedding = await _create(
            client, cleanup, category="embedding", max_context_tokens=None
        )
        rerank = await _create(
            client, cleanup, category="rerank", max_context_tokens=None
        )
        await _create_kb(
            cleanup,
            embedding_model_id=embedding["id"],
            rerank_model_id=rerank["id"],
        )

        response = await client.delete(f"/api/v1/admin/models/{rerank['id']}")

        assert response.status_code == 409
        assert response.json()["code"] == 22006

    async def test_no_reference_allows_delete(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """没有引用的模型可以正常删除。"""
        model = await _create(client, cleanup, category="ocr", max_context_tokens=None)

        response = await client.delete(f"/api/v1/admin/models/{model['id']}")

        assert response.status_code == 204
        cleanup["models"].remove(model["id"])


# ============================================================
# DoD 2：是类别默认 → 22003
# ============================================================


class TestDefaultBlocksDelete:
    async def test_default_blocks_delete(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """DoD：是类别默认 → 22003（409）。"""
        model = await _create(client, cleanup, is_default=True)

        response = await client.delete(f"/api/v1/admin/models/{model['id']}")

        assert response.status_code == 409
        assert response.json()["code"] == 22003

    async def test_delete_after_switching_default(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """换掉默认后，原默认模型就可以删了。"""
        first = await _create(client, cleanup, is_default=True)
        second = await _create(client, cleanup, model_code=_unique("code"))

        await client.put(f"/api/v1/admin/models/{second['id']}/default")

        response = await client.delete(f"/api/v1/admin/models/{first['id']}")
        assert response.status_code == 204
        cleanup["models"].remove(first["id"])

    async def test_default_checked_before_reference(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """同时满足两个条件时，先报「是默认」（22003）。

        顺序有讲究：默认标记是模型自身状态，比「被谁引用」更直接，
        用户先解除默认再处理引用，路径更清晰。
        """
        embedding = await _create(
            client, cleanup, category="embedding", max_context_tokens=None, is_default=True
        )
        await _create_kb(cleanup, embedding_model_id=embedding["id"])

        response = await client.delete(f"/api/v1/admin/models/{embedding['id']}")

        assert response.status_code == 409
        assert response.json()["code"] == 22003


# ============================================================
# DoD 3：删除后 model_call_log 保留
# ============================================================


class TestCallLogRetained:
    async def test_call_log_survives_model_deletion(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        """DoD：删除模型后 model_call_log 记录保留（不级联）。"""
        model = await _create(client, cleanup, category="ocr", max_context_tokens=None)
        await _create_call_log(cleanup, model["id"])

        response = await client.delete(f"/api/v1/admin/models/{model['id']}")
        assert response.status_code == 204
        cleanup["models"].remove(model["id"])

        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            result = await session.execute(
                text("SELECT count(*) FROM model_call_log WHERE model_id = :id"),
                {"id": model["id"]},
            )
            assert result.scalar_one() == 1

    async def test_multiple_logs_all_retained(
        self, client: httpx.AsyncClient, cleanup: dict
    ) -> None:
        model = await _create(client, cleanup, category="ocr", max_context_tokens=None)
        for _ in range(3):
            await _create_call_log(cleanup, model["id"])

        await client.delete(f"/api/v1/admin/models/{model['id']}")
        cleanup["models"].remove(model["id"])

        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            result = await session.execute(
                text("SELECT count(*) FROM model_call_log WHERE model_id = :id"),
                {"id": model["id"]},
            )
            assert result.scalar_one() == 3
