"""M0-T06 四个外部服务的真实连接测试。

服务部署在 192.168.75.100，配置见 backend/.env。
任一服务不可达时对应测试自动跳过，不阻塞其他人。
"""

from __future__ import annotations

import contextlib
import uuid

import pytest

from app.core.config import settings
from app.infra.elasticsearch import es_manager
from app.infra.milvus import milvus_manager
from app.infra.neo4j import neo4j_manager
from app.infra.storage import storage_manager

pytestmark = pytest.mark.integration


class TestMilvusHealth:
    async def test_health_check(self) -> None:
        """DoD：Milvus 客户端通过健康检查。"""
        if not await milvus_manager.check():
            pytest.skip("Milvus 不可达")
        assert await milvus_manager.check() is True

    async def test_list_collections(self) -> None:
        if not await milvus_manager.check():
            pytest.skip("Milvus 不可达")
        collections = await milvus_manager.list_collections()
        assert isinstance(collections, list)

    async def test_collection_roundtrip(self) -> None:
        """建集合 -> 检查存在 -> 删除，验证写入路径可用。"""
        if not await milvus_manager.check():
            pytest.skip("Milvus 不可达")

        name = f"travel_probe_{uuid.uuid4().hex[:8]}"
        try:
            await milvus_manager.create_collection(name, dimension=8)
            assert await milvus_manager.has_collection(name) is True
        finally:
            with contextlib.suppress(Exception):
                await milvus_manager.drop_collection(name)


class TestNeo4jHealth:
    async def test_health_check(self) -> None:
        """DoD：Neo4j 客户端通过健康检查。"""
        if not await neo4j_manager.check():
            pytest.skip("Neo4j 不可达")
        assert await neo4j_manager.check() is True

    async def test_cypher_return(self) -> None:
        if not await neo4j_manager.check():
            pytest.skip("Neo4j 不可达")
        result = await neo4j_manager.execute("RETURN 1 AS ok")
        assert result[0]["ok"] == 1

    async def test_write_and_readback(self) -> None:
        """写入临时节点再读回，最后清理，确认图写入可用。"""
        if not await neo4j_manager.check():
            pytest.skip("Neo4j 不可达")

        entity_id = f"probe_{uuid.uuid4().hex[:8]}"
        try:
            await neo4j_manager.execute(
                "CREATE (n:M0T06Probe {entity_id: $id})", {"id": entity_id}
            )
            assert await neo4j_manager.node_exists("M0T06Probe", entity_id) is True
        finally:
            await neo4j_manager.execute(
                "MATCH (n:M0T06Probe {entity_id: $id}) DELETE n", {"id": entity_id}
            )


class TestElasticsearchHealth:
    async def test_health_check(self) -> None:
        """DoD：Elasticsearch 客户端通过健康检查。"""
        if not await es_manager.check():
            pytest.skip("Elasticsearch 不可达")
        assert await es_manager.check() is True

    async def test_info_reachable(self) -> None:
        if not await es_manager.check():
            pytest.skip("Elasticsearch 不可达")
        info = await es_manager.get_client().info()
        assert "version" in info

    async def test_index_roundtrip(self) -> None:
        """建索引 -> 写入 -> 检索 -> 删除。"""
        if not await es_manager.check():
            pytest.skip("Elasticsearch 不可达")

        index = es_manager.index_name(f"probe_{uuid.uuid4().hex[:8]}")
        try:
            await es_manager.create_index(
                index,
                {"properties": {"text": {"type": "text"}}},
            )
            assert await es_manager.index_exists(index) is True

            await es_manager.bulk_index(index, [{"_id": "1", "text": "故宫"}])
            hits = await es_manager.search(index, {"match": {"text": "故宫"}})
            assert len(hits) == 1
            assert hits[0]["text"] == "故宫"
        finally:
            with contextlib.suppress(Exception):
                await es_manager.delete_index(index)


class TestMinioHealth:
    async def test_health_check(self) -> None:
        """DoD：MinIO 客户端通过健康检查。"""
        if not await storage_manager.check():
            pytest.skip("MinIO 不可达")
        assert await storage_manager.check() is True

    async def test_object_roundtrip_and_presigned_url(self) -> None:
        """上传 -> 预签名 URL 可访问 -> 删除。"""
        if not await storage_manager.check():
            pytest.skip("MinIO 不可达")

        key = f"probe/{uuid.uuid4().hex}.txt"
        try:
            await storage_manager.put_object(key, b"hello travel", content_type="text/plain")
            assert await storage_manager.object_exists(key) is True

            data = await storage_manager.get_object(key)
            assert data == b"hello travel"

            url = storage_manager.presigned_url(key)
            assert url.startswith("http")
            assert "X-Amz-Expires=3600" in url or "Expires=" in url
        finally:
            with contextlib.suppress(Exception):
                await storage_manager.delete_object(key)

    async def test_missing_object_raises_404(self) -> None:
        if not await storage_manager.check():
            pytest.skip("MinIO 不可达")

        from app.infra.exceptions import ObjectNotFoundError

        with pytest.raises(ObjectNotFoundError):
            await storage_manager.get_object("definitely/not/exists.bin")


class TestAllServices:
    async def test_check_all_reports_each_service(self) -> None:
        """四个服务全部可达时，就绪探针应全部为 true。"""
        from app.infra.clients import check_all

        result = await check_all()
        assert set(result) == {"milvus", "neo4j", "elasticsearch", "minio"}

        unreachable = [name for name, ok in result.items() if not ok]
        if unreachable:
            pytest.skip(f"以下服务不可达: {unreachable}")
        assert all(result.values())

    async def test_config_points_to_expected_hosts(self) -> None:
        """连接参数来自配置，指向测试服务器。"""
        assert settings.milvus_host
        assert settings.neo4j_uri.startswith("bolt://")
        assert settings.es_hosts
        assert settings.minio_endpoint
