"""M12-T08 模型类别列表接口的测试。

覆盖 DoD：
    1. 返回 5 个类别（chat/vision/embedding/rerank/ocr）（结构断言）
    2. 类别为固定枚举，不可由 API 新增（评审 §Q6）
"""

from __future__ import annotations

import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def client() -> httpx.AsyncClient:
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
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


class TestModelCategories:
    async def test_returns_five_categories(self, client: httpx.AsyncClient) -> None:
        """DoD：返回 5 个类别。"""
        async with client:
            response = await client.get("/api/v1/admin/models/categories")

        assert response.status_code == 200
        items = response.json()["data"]["items"]
        assert len(items) == 5

    async def test_all_expected_codes_present(
        self, client: httpx.AsyncClient
    ) -> None:
        async with client:
            response = await client.get("/api/v1/admin/models/categories")

        codes = {item["code"] for item in response.json()["data"]["items"]}
        assert codes == {"chat", "vision", "embedding", "rerank", "ocr"}

    async def test_each_item_has_code_and_name(
        self, client: httpx.AsyncClient
    ) -> None:
        async with client:
            response = await client.get("/api/v1/admin/models/categories")

        for item in response.json()["data"]["items"]:
            assert set(item.keys()) == {"code", "name"}
            assert item["name"], "类别必须有中文显示名"

    async def test_chinese_labels(self, client: httpx.AsyncClient) -> None:
        async with client:
            response = await client.get("/api/v1/admin/models/categories")

        labels = {
            item["code"]: item["name"]
            for item in response.json()["data"]["items"]
        }
        assert labels["chat"] == "文本对话"
        assert labels["vision"] == "图片理解"
        assert labels["embedding"] == "向量化"
        assert labels["rerank"] == "重排序"
        assert labels["ocr"] == "OCR解析"

    async def test_order_is_stable(self, client: httpx.AsyncClient) -> None:
        """顺序即前端下拉框展示顺序，不应每次请求都变。"""
        async with client:
            first = await client.get("/api/v1/admin/models/categories")
            second = await client.get("/api/v1/admin/models/categories")

        assert first.json()["data"] == second.json()["data"]

    async def test_route_not_shadowed_by_model_id(
        self, client: httpx.AsyncClient
    ) -> None:
        """``/models/categories`` 不会被 ``/models/{model_id}`` 抢先匹配。

        若路由顺序写反，``categories`` 会被当成 UUID 解析从而返回 400。
        """
        async with client:
            response = await client.get("/api/v1/admin/models/categories")

        assert response.status_code == 200, (
            "路由被 /models/{model_id} 遮蔽了——检查注册顺序"
        )


class TestNoCreateEndpoint:
    """DoD：类别是固定枚举，不可由 API 新增（评审 §Q6）。"""

    async def test_post_categories_not_allowed(
        self, client: httpx.AsyncClient
    ) -> None:
        async with client:
            response = await client.post(
                "/api/v1/admin/models/categories",
                json={"code": "audio", "name": "语音"},
            )

        # 没有该路由；请求会落到 /models/{model_id} 的 POST 吗？
        # 没有 POST /models/{id}，因此应为 405 或 404
        assert response.status_code in (404, 405)

    async def test_put_categories_not_allowed(
        self, client: httpx.AsyncClient
    ) -> None:
        async with client:
            response = await client.put(
                "/api/v1/admin/models/categories",
                json={"code": "audio", "name": "语音"},
            )

        # PUT 会落到 /models/{model_id}，categories 被解析为 UUID 失败 → 400
        assert response.status_code in (400, 404, 405, 422)

    async def test_delete_categories_not_allowed(
        self, client: httpx.AsyncClient
    ) -> None:
        async with client:
            response = await client.delete("/api/v1/admin/models/categories")

        # DELETE 落到 /models/{model_id}，UUID 解析失败 → 400
        assert response.status_code in (400, 404, 405, 422)

    def test_openapi_has_no_category_mutation(self) -> None:
        """OpenAPI 里 categories 路径只应有 GET。"""
        from app.main import create_app

        schema = create_app().openapi()
        path = schema["paths"].get("/api/v1/admin/models/categories")

        assert path is not None
        assert set(path.keys()) == {"get"}
