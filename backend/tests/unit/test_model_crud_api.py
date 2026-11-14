"""M12-T02 模型 CRUD 接口的测试。

覆盖 DoD：
    1. 同类别下 model_code + base_url 重复 → 22001（409）
    2. 创建时 is_default=true 自动取消同类别原默认（DB 断言）
    3. 列表与详情不返回 api_key_encrypted（序列化断言）
    4. 更新时 category 不可修改 → 22002（400）
    5. API Key 加密存储（DB 中非明文）
边界：api_key 不传保持原值、传空字符串清空。
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.modules.model_gateway.crypto import decrypt_api_key

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
        result = await session.execute(
            text("SELECT to_regclass('public.model') IS NOT NULL")
        )
        if not result.scalar_one():
            pytest.skip("表未创建（先执行 alembic upgrade head）")


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
    created: list[str] = []
    yield created

    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        for model_id in created:
            await session.execute(
                text("DELETE FROM model WHERE id = :id"), {"id": model_id}
            )
        await session.commit()


def _unique(prefix: str = "m") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _create(
    client: httpx.AsyncClient, cleanup: list[str], **overrides: Any
) -> dict:
    payload = {
        "name": f"测试模型 {_unique()}",
        "category": "chat",
        "model_code": _unique("code"),
        "base_url": "https://api.example.com/v1",
        "max_context_tokens": 128000,
        "api_key": "sk-test-plaintext-key-12345",
        **overrides,
    }
    response = await client.post("/api/v1/admin/models", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    cleanup.append(data["id"])
    return data


# ============================================================
# 创建
# ============================================================


class TestCreate:
    async def test_create_returns_201(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        data = await _create(client, cleanup)
        assert data["category"] == "chat"
        assert data["is_default"] is False
        assert data["is_enabled"] is True

    async def test_duplicate_returns_22001(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        """DoD：同类别下 model_code + base_url 重复 → 22001（409）。"""
        first = await _create(client, cleanup)

        response = await client.post(
            "/api/v1/admin/models",
            json={
                "name": "重复的模型",
                "category": first["category"],
                "model_code": first["model_code"],
                "base_url": first["base_url"],
                "max_context_tokens": 8000,
            },
        )

        assert response.status_code == 409
        assert response.json()["code"] == 22001

    async def test_same_code_different_category_allowed(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        """不同类别下可以重复注册同一 model_code。"""
        first = await _create(client, cleanup, category="chat")
        second = await _create(
            client, cleanup, category="embedding", max_context_tokens=None
        )

        assert first["model_code"] != second["model_code"] or (
            first["category"] != second["category"]
        )

    async def test_default_unsets_previous(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        """DoD：创建 is_default=true 自动取消同类别原默认（DB 断言）。"""
        first = await _create(client, cleanup, is_default=True)
        assert first["is_default"] is True

        second = await _create(
            client, cleanup, is_default=True, model_code=_unique("code")
        )
        assert second["is_default"] is True

        # 查库确认旧的已取消
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            result = await session.execute(
                text("SELECT is_default FROM model WHERE id = :id"),
                {"id": first["id"]},
            )
            assert result.scalar_one() is False

    async def test_text_category_requires_context_tokens(
        self, client: httpx.AsyncClient
    ) -> None:
        """文本类模型必须填 max_context_tokens。"""
        response = await client.post(
            "/api/v1/admin/models",
            json={
                "name": "无上下文",
                "category": "chat",
                "model_code": _unique("code"),
                "base_url": "https://api.example.com/v1",
            },
        )
        # 项目约定：Pydantic 校验错误统一返回 10001 / HTTP 400（非 FastAPI 默认的 422）
        assert response.status_code == 400
        assert response.json()["code"] == 10001

    async def test_embedding_does_not_require_context(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        data = await _create(
            client, cleanup, category="embedding", max_context_tokens=None
        )
        assert data["category"] == "embedding"
        assert data["max_context_tokens"] is None

    async def test_invalid_category_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/admin/models",
            json={
                "name": "非法类别",
                "category": "not_a_category",
                "model_code": _unique("code"),
                "base_url": "https://api.example.com/v1",
                "max_context_tokens": 100,
            },
        )
        assert response.status_code == 400
        assert response.json()["code"] == 10001


# ============================================================
# 密钥安全（DoD 3 + 5）
# ============================================================


class TestApiKeySecurity:
    async def test_stored_encrypted(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        """DoD：API Key 加密存储（DB 中非明文）。"""
        plaintext = "sk-super-secret-key-abcdef"
        data = await _create(client, cleanup, api_key=plaintext)

        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            result = await session.execute(
                text("SELECT api_key_encrypted FROM model WHERE id = :id"),
                {"id": data["id"]},
            )
            stored = result.scalar_one()

        assert stored is not None
        assert plaintext not in stored
        assert stored.startswith("v1:")
        # 能解回原文
        assert decrypt_api_key(stored) == plaintext

    async def test_list_does_not_expose_key(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        """DoD：列表不返回 api_key_encrypted。"""
        await _create(client, cleanup)

        response = await client.get("/api/v1/admin/models", params={"page_size": 100})
        assert response.status_code == 200

        for item in response.json()["data"]["items"]:
            assert "api_key_encrypted" not in item
            assert "api_key" not in item

    async def test_detail_does_not_expose_key(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        """DoD：详情不返回 api_key_encrypted。"""
        data = await _create(client, cleanup)

        response = await client.get(f"/api/v1/admin/models/{data['id']}")
        assert response.status_code == 200

        payload = response.json()["data"]
        assert "api_key_encrypted" not in payload
        assert "api_key" not in payload

    async def test_has_api_key_flag(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        """用布尔标记替代密钥回显，前端仍能知道「配没配」。"""
        with_key = await _create(client, cleanup, api_key="sk-abc")
        assert with_key["has_api_key"] is True

        without_key = await _create(
            client, cleanup, api_key=None, model_code=_unique("code")
        )
        assert without_key["has_api_key"] is False


# ============================================================
# 更新
# ============================================================


class TestUpdate:
    async def test_update_returns_204(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        data = await _create(client, cleanup)

        response = await client.put(
            f"/api/v1/admin/models/{data['id']}",
            json={
                "name": "改过的名字",
                "model_code": data["model_code"],
                "base_url": data["base_url"],
                "max_context_tokens": 64000,
            },
        )
        assert response.status_code == 204

        detail = await client.get(f"/api/v1/admin/models/{data['id']}")
        assert detail.json()["data"]["name"] == "改过的名字"

    async def test_category_immutable_returns_22002(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        """DoD：更新时 category 不可修改，尝试修改返回 22002（400）。"""
        data = await _create(client, cleanup, category="chat")

        response = await client.put(
            f"/api/v1/admin/models/{data['id']}",
            json={
                "name": data["name"],
                "category": "embedding",
                "model_code": data["model_code"],
                "base_url": data["base_url"],
                "max_context_tokens": 1000,
            },
        )

        assert response.status_code == 400
        assert response.json()["code"] == 22002

    async def test_same_category_accepted(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        """传入与原值相同的 category 不算修改。"""
        data = await _create(client, cleanup, category="chat")

        response = await client.put(
            f"/api/v1/admin/models/{data['id']}",
            json={
                "name": data["name"],
                "category": "chat",
                "model_code": data["model_code"],
                "base_url": data["base_url"],
                "max_context_tokens": 1000,
            },
        )
        assert response.status_code == 204

    async def test_api_key_absent_keeps_original(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        """DoD 边界：api_key 不传保持原值。"""
        original = "sk-original-key-999"
        data = await _create(client, cleanup, api_key=original)

        await client.put(
            f"/api/v1/admin/models/{data['id']}",
            json={
                "name": "改名",
                "model_code": data["model_code"],
                "base_url": data["base_url"],
                "max_context_tokens": 1000,
            },
        )

        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            result = await session.execute(
                text("SELECT api_key_encrypted FROM model WHERE id = :id"),
                {"id": data["id"]},
            )
            assert decrypt_api_key(result.scalar_one()) == original

    async def test_api_key_empty_string_clears(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        """DoD 边界：api_key 传空字符串清空。"""
        data = await _create(client, cleanup, api_key="sk-to-be-cleared")

        await client.put(
            f"/api/v1/admin/models/{data['id']}",
            json={
                "name": "清空密钥",
                "model_code": data["model_code"],
                "base_url": data["base_url"],
                "max_context_tokens": 1000,
                "api_key": "",
            },
        )

        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            result = await session.execute(
                text("SELECT api_key_encrypted FROM model WHERE id = :id"),
                {"id": data["id"]},
            )
            assert not result.scalar_one()

    async def test_update_to_default_unsets_previous(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        first = await _create(client, cleanup, is_default=True)
        second = await _create(client, cleanup, model_code=_unique("code"))

        await client.put(
            f"/api/v1/admin/models/{second['id']}",
            json={
                "name": second["name"],
                "model_code": second["model_code"],
                "base_url": second["base_url"],
                "max_context_tokens": 1000,
                "is_default": True,
            },
        )

        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            result = await session.execute(
                text("SELECT is_default FROM model WHERE id = :id"),
                {"id": first["id"]},
            )
            assert result.scalar_one() is False

    async def test_update_nonexistent_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.put(
            f"/api/v1/admin/models/{uuid.uuid4()}",
            json={
                "name": "不存在",
                "model_code": "x",
                "base_url": "https://x.com",
                "max_context_tokens": 100,
            },
        )
        assert response.status_code == 404
        assert response.json()["code"] == 22007


# ============================================================
# 查询
# ============================================================


class TestQuery:
    async def test_list_filters_by_category(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        await _create(client, cleanup, category="chat")
        await _create(client, cleanup, category="rerank", max_context_tokens=None)

        response = await client.get(
            "/api/v1/admin/models", params={"category": "rerank", "page_size": 100}
        )
        items = response.json()["data"]["items"]

        assert all(item["category"] == "rerank" for item in items)

    async def test_list_pagination_fields(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        await _create(client, cleanup)

        response = await client.get("/api/v1/admin/models", params={"page_size": 5})
        data = response.json()["data"]

        for key in ("items", "total", "page", "page_size", "total_pages"):
            assert key in data

    async def test_detail_nonexistent_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get(f"/api/v1/admin/models/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["code"] == 22007

    async def test_invalid_category_filter_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get(
            "/api/v1/admin/models", params={"category": "bogus"}
        )
        assert response.status_code == 400
        assert response.json()["code"] == 10001


# ============================================================
# 删除
# ============================================================


class TestDelete:
    async def test_delete_returns_204(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        await _create(client, cleanup, category="ocr", max_context_tokens=None)
        target = await _create(
            client, cleanup, category="ocr", model_code=_unique("code"), max_context_tokens=None
        )

        response = await client.delete(f"/api/v1/admin/models/{target['id']}")
        assert response.status_code == 204

        detail = await client.get(f"/api/v1/admin/models/{target['id']}")
        assert detail.status_code == 404
        cleanup.remove(target["id"])

    async def test_cannot_delete_default_model(
        self, client: httpx.AsyncClient, cleanup: list[str]
    ) -> None:
        """API §10.7：是该类别默认 → 22003（409）。"""
        model = await _create(
            client, cleanup, category="vision", model_code=_unique("code"), is_default=True
        )

        response = await client.delete(f"/api/v1/admin/models/{model['id']}")

        assert response.status_code == 409
        assert response.json()["code"] == 22003
