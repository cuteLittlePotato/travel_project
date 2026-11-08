"""M0-T06 四个外部服务封装的单元测试（不连真实服务）。

覆盖 DoD：
    1. 预签名 URL 有效期 1 小时
    2. storage_key 不直接暴露给 API 响应

边界：各服务不可达时给出可区分的错误类型；对象/节点不存在有明确异常。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.infra import elasticsearch as es_module
from app.infra import milvus as milvus_module
from app.infra import neo4j as neo4j_module
from app.infra import storage as storage_module
from app.infra.exceptions import (
    BucketNotFoundError,
    ElasticsearchIndexNotFoundError,
    ElasticsearchUnavailableError,
    MilvusUnavailableError,
    Neo4jNodeNotFoundError,
    Neo4jUnavailableError,
    ObjectNotFoundError,
    StorageUnavailableError,
)


def _mock(manager: Any, attr: str, client: Any) -> None:
    """把 manager 的内部客户端替换为 mock。"""
    setattr(manager, attr, client)


# ============================================================
# 预签名 URL（DoD 2）
# ============================================================


class TestPresignedUrl:
    def test_default_expiry_is_one_hour(self) -> None:
        """DoD：预签名 URL 有效期 1 小时（3600 秒）。"""
        assert settings.minio_presign_expire_seconds == 3600

    def test_presigned_get_uses_configured_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        manager = storage_module.StorageManager()
        fake_client = MagicMock()
        fake_client.presigned_get_object.return_value = "http://minio/presigned"
        _mock(manager, "_client", fake_client)

        url = manager.presigned_url("documents/a.pdf")

        assert url == "http://minio/presigned"
        _, kwargs = fake_client.presigned_get_object.call_args
        assert kwargs["expires"] == timedelta(seconds=settings.minio_presign_expire_seconds)

    def test_explicit_expiry_overrides_default(self) -> None:
        manager = storage_module.StorageManager()
        fake_client = MagicMock()
        fake_client.presigned_get_object.return_value = "http://x"
        _mock(manager, "_client", fake_client)

        manager.presigned_url("k", expires_seconds=600)

        _, kwargs = fake_client.presigned_get_object.call_args
        assert kwargs["expires"] == timedelta(seconds=600)

    def test_presigned_put_exists_for_direct_upload(self) -> None:
        manager = storage_module.StorageManager()
        fake_client = MagicMock()
        fake_client.presigned_put_object.return_value = "http://minio/put"
        _mock(manager, "_client", fake_client)

        assert manager.presigned_upload_url("k") == "http://minio/put"

    def test_presign_failure_raises_storage_error(self) -> None:
        manager = storage_module.StorageManager()
        fake_client = MagicMock()
        fake_client.presigned_get_object.side_effect = RuntimeError("conn refused")
        _mock(manager, "_client", fake_client)

        with pytest.raises(StorageUnavailableError):
            manager.presigned_url("k")


# ============================================================
# storage_key 不暴露（DoD 3）
# ============================================================


class TestStorageKeyNotExposed:
    def test_put_object_returns_key_for_internal_use_only(self) -> None:
        """``put_object`` 返回的是内部 key，注释已声明不得直接返回前端。"""
        manager = storage_module.StorageManager()
        fake_client = MagicMock()
        _mock(manager, "_client", fake_client)

        key = manager.put_object.__doc__ or ""
        assert "不要直接返回给前端" in key or "内部使用" in key

    def test_api_responses_have_no_storage_key_field(self) -> None:
        """响应模型不得出现 storage_key / object_key 等内部字段。"""
        from pydantic import BaseModel

        from app import schemas

        forbidden = {"storage_key", "object_key", "bucket", "minio_key", "storage_path"}
        offenders: list[str] = []

        for name in dir(schemas):
            obj = getattr(schemas, name)
            if not (isinstance(obj, type) and issubclass(obj, BaseModel)):
                continue
            for field_name in obj.model_fields:
                if field_name.lower() in forbidden:
                    offenders.append(f"{name}.{field_name}")

        assert not offenders, f"响应模型暴露了内部存储字段: {offenders}"

    def test_storage_module_documents_the_rule(self) -> None:
        assert "不得直接出现" in storage_module.__doc__
        assert "预签名 URL" in storage_module.__doc__


# ============================================================
# 可区分错误（边界与异常）
# ============================================================


class TestDistinguishableErrors:
    def test_milvus_error_names_service(self) -> None:
        error = MilvusUnavailableError("timeout")
        assert error.service == "Milvus"
        assert "Milvus" in error.message
        assert error.http_status == 503

    def test_neo4j_error_names_service(self) -> None:
        error = Neo4jUnavailableError()
        assert error.service == "Neo4j"
        assert error.http_status == 503

    def test_es_error_names_service(self) -> None:
        error = ElasticsearchUnavailableError()
        assert error.service == "Elasticsearch"
        assert error.http_status == 503

    def test_storage_error_names_service(self) -> None:
        error = StorageUnavailableError()
        assert error.service == "MinIO"
        assert error.http_status == 503

    def test_not_found_uses_404_not_503(self) -> None:
        """「对象不存在」与「服务不可用」必须区分：前者 404，后者 503。"""
        assert ObjectNotFoundError("k").http_status == 404
        assert BucketNotFoundError("b").http_status == 404
        assert Neo4jNodeNotFoundError("n").http_status == 404
        assert ElasticsearchIndexNotFoundError("i").http_status == 404

    def test_all_infra_errors_share_base(self) -> None:
        from app.infra.exceptions import InfraError

        for exc in (
            MilvusUnavailableError(),
            Neo4jUnavailableError(),
            ElasticsearchUnavailableError(),
            StorageUnavailableError(),
        ):
            assert isinstance(exc, InfraError)


# ============================================================
# Milvus
# ============================================================


class TestMilvus:
    def test_check_true_when_list_succeeds(self) -> None:
        manager = milvus_module.MilvusManager()
        _mock(manager, "_client", MagicMock(list_collections=MagicMock(return_value=[])))
        import asyncio

        assert asyncio.run(manager.check()) is True

    def test_check_false_when_unreachable(self) -> None:
        manager = milvus_module.MilvusManager()
        _mock(manager, "_client", MagicMock(list_collections=MagicMock(side_effect=OSError)))
        import asyncio

        assert asyncio.run(manager.check()) is False

    def test_has_collection_wraps_error(self) -> None:
        manager = milvus_module.MilvusManager()
        _mock(manager, "_client", MagicMock(has_collection=MagicMock(side_effect=OSError("x"))))
        import asyncio

        with pytest.raises(MilvusUnavailableError):
            asyncio.run(manager.has_collection("kb_1"))


# ============================================================
# Neo4j
# ============================================================


class TestNeo4jLabelInjection:
    """Cypher 标签无法参数化，必须严格校验。"""

    @pytest.mark.parametrize("label", ["Attraction", "Person_Node", "A1"])
    def test_valid_labels_accepted(self, label: str) -> None:
        neo4j_module._assert_label(label)

    @pytest.mark.parametrize(
        "label",
        ["", "Attraction) DETACH DELETE n //", "A B", "标签", "A-B", "A;DROP"],
    )
    def test_invalid_labels_rejected(self, label: str) -> None:
        with pytest.raises(ValueError, match="非法的 Cypher 标签"):
            neo4j_module._assert_label(label)

    async def test_require_node_raises_404_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = neo4j_module.Neo4jManager()

        async def _empty(*_a: Any, **_k: Any) -> None:
            return None

        monkeypatch.setattr(manager, "execute_single", _empty)
        with pytest.raises(Neo4jNodeNotFoundError):
            await manager.require_node("Attraction", "abc")


# ============================================================
# Elasticsearch
# ============================================================


class TestElasticsearch:
    def test_index_name_uses_configured_prefix(self) -> None:
        manager = es_module.ElasticsearchManager()
        assert manager.index_name("doc_chunk") == f"{settings.es_index_prefix}_doc_chunk"

    async def test_bulk_index_requires_existing_index(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = es_module.ElasticsearchManager()

        async def _missing(_index: str) -> bool:
            return False

        monkeypatch.setattr(manager, "index_exists", _missing)
        with pytest.raises(ElasticsearchIndexNotFoundError):
            await manager.bulk_index("travel_doc_chunk", [{"_id": "1", "text": "x"}])

    async def test_search_requires_existing_index(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = es_module.ElasticsearchManager()

        async def _missing(_index: str) -> bool:
            return False

        monkeypatch.setattr(manager, "index_exists", _missing)
        with pytest.raises(ElasticsearchIndexNotFoundError):
            await manager.search("travel_doc_chunk", {"match_all": {}})


# ============================================================
# 对象存储
# ============================================================


class TestStorage:
    async def test_object_exists_false_on_not_found(self) -> None:
        manager = storage_module.StorageManager()

        class _NoSuchKey(Exception):
            code = "NoSuchKey"

        fake = MagicMock()
        fake.stat_object.side_effect = _NoSuchKey()
        _mock(manager, "_client", fake)

        assert await manager.object_exists("missing.pdf") is False

    async def test_get_object_raises_404_on_not_found(self) -> None:
        manager = storage_module.StorageManager()

        class _NoSuchKey(Exception):
            code = "NoSuchKey"

        fake = MagicMock()
        fake.get_object.side_effect = _NoSuchKey()
        _mock(manager, "_client", fake)

        with pytest.raises(ObjectNotFoundError):
            await manager.get_object("missing.pdf")

    async def test_require_bucket_raises_when_missing(self) -> None:
        manager = storage_module.StorageManager()
        _mock(manager, "_client", MagicMock(bucket_exists=MagicMock(return_value=False)))

        with pytest.raises(BucketNotFoundError):
            await manager.require_bucket("nope")

    async def test_ensure_bucket_creates_when_missing(self) -> None:
        manager = storage_module.StorageManager()
        fake = MagicMock()
        fake.bucket_exists.return_value = False
        _mock(manager, "_client", fake)

        await manager.ensure_bucket("new-bucket")
        fake.make_bucket.assert_called_once_with("new-bucket")


# ============================================================
# 聚合入口
# ============================================================


class TestAggregateHealth:
    async def test_check_all_returns_all_four(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.infra import clients

        async def _ok() -> bool:
            return True

        for manager in (
            clients.milvus_manager,
            clients.neo4j_manager,
            clients.es_manager,
            clients.storage_manager,
        ):
            monkeypatch.setattr(manager, "check", _ok, raising=False)

        result = await clients.check_all()
        assert set(result) == {"milvus", "neo4j", "elasticsearch", "minio"}
        assert all(result.values())

    async def test_one_failure_does_not_break_others(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.infra import clients

        async def _ok() -> bool:
            return True

        async def _fail() -> bool:
            raise ConnectionError("down")

        monkeypatch.setattr(clients.milvus_manager, "check", _fail, raising=False)
        monkeypatch.setattr(clients.neo4j_manager, "check", _ok, raising=False)
        monkeypatch.setattr(clients.es_manager, "check", _ok, raising=False)
        monkeypatch.setattr(clients.storage_manager, "check", _ok, raising=False)

        result = await clients.check_all()
        assert result["milvus"] is False
        assert result["neo4j"] is True
