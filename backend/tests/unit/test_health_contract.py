"""运维探针的接口契约测试（API 设计 §1.8）。

背景：`/api/health` 与 `/api/health/ready` 是实现中新增、后补入设计文档的。
本测试确保代码与文档一致，防止后续修改悄悄改变契约。

文档位置：docs/design/04.API接口设计.md §1.8 运维探针
"""

from __future__ import annotations

import pytest

#: 文档 §1.8.2 列出的依赖项，顺序不敏感但集合必须一致
DOCUMENTED_DEPENDENCIES = {
    "postgres",
    "redis",
    "milvus",
    "neo4j",
    "elasticsearch",
    "minio",
}


class TestLivenessContract:
    """§1.8.1 存活探针。"""

    def test_path_is_unversioned(self, client) -> None:
        """文档：路径不带版本前缀，升级 API 版本时探针地址不变。"""
        assert client.get("/api/health").status_code == 200

    def test_response_shape_matches_doc(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        """文档示例：{code:0, message:"ok", data:{status:"ok"}}"""
        response = client.get("/api/health")
        assert response.json() == {
            "code": 0,
            "message": "ok",
            "data": {"status": "ok"},
        }

    def test_does_not_probe_dependencies(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        """文档：不探测外部依赖，避免依赖级联失败导致容器反复重启。"""
        from app.api.v1 import health as health_module

        called = {"count": 0}

        async def _fail_if_called() -> bool:
            called["count"] += 1
            raise AssertionError("存活探针不应探测依赖")

        monkeypatch.setattr(health_module, "check_database", _fail_if_called)
        monkeypatch.setattr(health_module, "check_redis", _fail_if_called)
        monkeypatch.setattr(health_module, "check_all", _fail_if_called)

        assert client.get("/api/health").status_code == 200
        assert called["count"] == 0

    def test_requires_no_auth(self, client) -> None:
        """文档：认证要求为「无需」。"""
        assert client.get("/api/health").status_code == 200


class TestReadinessContract:
    """§1.8.2 就绪探针。"""

    def test_response_contains_status_and_dependencies(self, client) -> None:
        body = client.get("/api/health/ready").json()
        assert set(body) == {"code", "message", "data"}
        assert set(body["data"]) == {"status", "dependencies"}

    def test_dependency_keys_match_documentation(self, client) -> None:
        """文档列出的 6 个依赖项必须全部出现，且不多不少。"""
        deps = client.get("/api/health/ready").json()["data"]["dependencies"]
        assert set(deps) == DOCUMENTED_DEPENDENCIES

    def test_all_values_are_boolean(self, client) -> None:
        deps = client.get("/api/health/ready").json()["data"]["dependencies"]
        for name, value in deps.items():
            assert isinstance(value, bool), f"{name} 应为 bool，实际 {type(value)}"

    def test_status_values_are_ready_or_degraded(self, client) -> None:
        status = client.get("/api/health/ready").json()["data"]["status"]
        assert status in {"ready", "degraded"}

    def test_always_returns_200_even_when_degraded(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """文档：始终返回 HTTP 200，用 status 表达是否就绪。"""
        from app.api.v1 import health as health_module

        async def _down() -> bool:
            raise ConnectionError("down")

        async def _external_down() -> dict[str, bool]:
            raise ConnectionError("down")

        monkeypatch.setattr(health_module, "check_database", _down)
        monkeypatch.setattr(health_module, "check_redis", _down)
        monkeypatch.setattr(health_module, "check_all", _external_down)

        response = client.get("/api/health/ready")
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "degraded"

    def test_requires_no_auth(self, client) -> None:
        assert client.get("/api/health/ready").status_code == 200


class TestDocumentationConsistency:
    """确保设计文档与实现同步。"""

    def test_api_doc_has_health_section(self) -> None:
        from pathlib import Path

        doc = (
            Path(__file__).resolve().parents[3]
            / "docs"
            / "design"
            / "04.API接口设计.md"
        )
        content = doc.read_text(encoding="utf-8")

        assert "### 1.8 运维探针" in content
        assert "GET /api/health" in content
        assert "GET /api/health/ready" in content
        for dep in DOCUMENTED_DEPENDENCIES:
            assert dep in content, f"文档缺少依赖项说明: {dep}"

    def test_doc_lists_health_in_auth_matrix(self) -> None:
        """权限矩阵应标注探针无需认证。"""
        from pathlib import Path

        content = (
            Path(__file__).resolve().parents[3]
            / "docs"
            / "design"
            / "04.API接口设计.md"
        ).read_text(encoding="utf-8")
        assert "`/api/health`、`/api/health/ready` | 无需认证" in content

    def test_health_not_under_version_prefix(self, client) -> None:
        """文档强调探针不带版本前缀。"""
        assert client.get("/api/v1/health").status_code == 404
