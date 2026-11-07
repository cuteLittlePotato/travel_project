"""外部服务客户端：Milvus / Neo4j / Elasticsearch / MinIO。

统一从配置读取连接参数，各自提供健康检查。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import settings

# ============================================================
# Milvus（向量检索）
# ============================================================


class MilvusClientManager:
    def __init__(self) -> None:
        self._client: Any = None

    def get_client(self) -> Any:
        if self._client is None:
            from pymilvus import MilvusClient

            self._client = MilvusClient(
                uri=f"http://{settings.milvus_host}:{settings.milvus_port}",
                user=settings.milvus_user or "",
                password=settings.milvus_password or "",
            )
        return self._client

    async def check(self) -> bool:
        # pymilvus 为同步库，放到线程池避免阻塞事件循环
        return await asyncio.to_thread(
            lambda: bool(self.get_client().list_collections() is not None)
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


# ============================================================
# Neo4j（图数据库：仅存图谱结构与关系）
# ============================================================


class Neo4jManager:
    def __init__(self) -> None:
        self._driver: Any = None

    def get_driver(self) -> Any:
        if self._driver is None:
            from neo4j import AsyncGraphDatabase

            self._driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
        return self._driver

    async def execute(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        async with self.get_driver().session(database=settings.neo4j_database) as session:
            result = await session.run(cypher, params or {})
            return [record.data() async for record in result]

    async def check(self) -> bool:
        try:
            await self.execute("RETURN 1 AS ok")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None


# ============================================================
# Elasticsearch（BM25 关键词检索，IK 分词）
# ============================================================


class ElasticsearchManager:
    def __init__(self) -> None:
        self._client: Any = None

    def get_client(self) -> Any:
        if self._client is None:
            from elasticsearch import AsyncElasticsearch

            self._client = AsyncElasticsearch(hosts=settings.es_hosts)
        return self._client

    def index_name(self, suffix: str) -> str:
        return f"{settings.es_index_prefix}_{suffix}"

    async def check(self) -> bool:
        return bool(await self.get_client().ping())

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None


# ============================================================
# MinIO（对象存储，S3 协议）
# ============================================================


class StorageManager:
    """对象存储封装。

    规定：``storage_key`` 不直接暴露给 API 响应，一律转换为预签名 URL。
    """

    def __init__(self) -> None:
        self._client: Any = None

    def get_client(self) -> Any:
        if self._client is None:
            from minio import Minio

            self._client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
        return self._client

    def presigned_url(self, bucket: str, object_key: str) -> str:
        from datetime import timedelta

        return self.get_client().presigned_get_object(
            bucket,
            object_key,
            expires=timedelta(seconds=settings.minio_presign_expire_seconds),
        )

    async def check(self) -> bool:
        return await asyncio.to_thread(
            lambda: self.get_client().bucket_exists(settings.minio_bucket_documents)
        )

    async def ensure_bucket(self, bucket: str) -> None:
        client = self.get_client()
        exists = await asyncio.to_thread(client.bucket_exists, bucket)
        if not exists:
            await asyncio.to_thread(client.make_bucket, bucket)

    def close(self) -> None:
        self._client = None


milvus_manager = MilvusClientManager()
neo4j_manager = Neo4jManager()
es_manager = ElasticsearchManager()
storage_manager = StorageManager()


async def check_all() -> dict[str, bool]:
    """并发探测四个服务，供 /health 使用。"""
    results = await asyncio.gather(
        milvus_manager.check(),
        neo4j_manager.check(),
        es_manager.check(),
        storage_manager.check(),
        return_exceptions=True,
    )
    names = ("milvus", "neo4j", "elasticsearch", "minio")
    return {
        name: (result is True)
        for name, result in zip(names, results, strict=True)
    }


async def close_all() -> None:
    await neo4j_manager.close()
    await es_manager.close()
    milvus_manager.close()
    storage_manager.close()
