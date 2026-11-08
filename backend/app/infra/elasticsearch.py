"""Elasticsearch 客户端封装（BM25 关键词检索）。

与 Milvus 的分工（架构 §1.4）：
    - Milvus：向量相似度，语义匹配
    - ES：BM25 字面匹配，需 IK 中文分词
    两者互不依赖，文档切分后**并行**写入。

ES 不涉及向量化，因此向量模型变更时**无需重建 ES 索引**。
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.infra.exceptions import (
    ElasticsearchIndexNotFoundError,
    ElasticsearchUnavailableError,
)

logger = logging.getLogger(__name__)


class ElasticsearchManager:
    def __init__(self) -> None:
        self._client: Any = None

    # ---------------- 连接 ----------------

    def get_client(self) -> Any:
        if self._client is None:
            from elasticsearch import AsyncElasticsearch

            self._client = AsyncElasticsearch(
                hosts=settings.es_hosts,
                request_timeout=settings.es_request_timeout,
                max_retries=settings.es_max_retries,
            )
        return self._client

    async def check(self) -> bool:
        try:
            return bool(await self.get_client().ping())
        except Exception:
            logger.warning("Elasticsearch 健康检查失败", exc_info=True)
            return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    # ---------------- 索引操作 ----------------

    def index_name(self, suffix: str) -> str:
        """统一索引命名，避免多个系统共用一个 ES 时冲突。"""
        return f"{settings.es_index_prefix}_{suffix}"

    async def index_exists(self, index: str) -> bool:
        try:
            return bool(await self.get_client().indices.exists(index=index))
        except Exception as exc:
            raise ElasticsearchUnavailableError(str(exc)) from exc

    async def create_index(
        self, index: str, mappings: dict[str, Any], settings_body: dict[str, Any] | None = None
    ) -> None:
        """创建索引。

        ``mappings`` 中文本字段应指定 IK 分词器：
        ``{"type": "text", "analyzer": "ik_max_word", "search_analyzer": "ik_smart"}``
        """
        body: dict[str, Any] = {"mappings": mappings}
        if settings_body:
            body["settings"] = settings_body
        try:
            await self.get_client().indices.create(index=index, **body)
        except Exception as exc:
            raise ElasticsearchUnavailableError(f"创建索引失败：{exc}") from exc

    async def delete_index(self, index: str) -> None:
        try:
            await self.get_client().indices.delete(index=index)
        except Exception as exc:
            raise ElasticsearchUnavailableError(f"删除索引失败：{exc}") from exc

    async def refresh(self, index: str) -> None:
        """立即刷新，使刚写入的文档可被检索（测试与同步场景需要）。"""
        try:
            await self.get_client().indices.refresh(index=index)
        except Exception as exc:
            raise ElasticsearchUnavailableError(f"刷新索引失败：{exc}") from exc

    # ---------------- 文档操作 ----------------

    async def bulk_index(self, index: str, documents: list[dict[str, Any]]) -> None:
        """批量写入。文档需含 ``_id`` 字段作为主键。"""
        if not await self.index_exists(index):
            raise ElasticsearchIndexNotFoundError(index)

        if not documents:
            return

        # ES 8/9 客户端的 bulk API 要求每个操作自带 _index
        operations: list[dict[str, Any]] = []
        for doc in documents:
            doc_id = doc.get("_id")
            payload = {k: v for k, v in doc.items() if k != "_id"}
            operations.append({"index": {"_index": index, "_id": doc_id}})
            operations.append(payload)

        try:
            response = await self.get_client().bulk(operations=operations, refresh=True)
        except Exception as exc:
            raise ElasticsearchUnavailableError(f"批量写入失败：{exc}") from exc

        if response.get("errors"):
            failed = [
                item["index"]["error"]
                for item in response["items"]
                if item.get("index", {}).get("error")
            ]
            raise ElasticsearchUnavailableError(f"部分文档写入失败：{failed[:3]}")

    async def delete_by_ids(self, index: str, ids: list[str]) -> None:
        """批量删除。文档不存在不视为失败（幂等）。"""
        if not ids:
            return
        operations = [
            {"delete": {"_index": index, "_id": doc_id}} for doc_id in ids
        ]
        try:
            await self.get_client().bulk(operations=operations, refresh=True)
        except Exception as exc:
            raise ElasticsearchUnavailableError(f"批量删除失败：{exc}") from exc

    async def search(
        self, index: str, query: dict[str, Any], size: int = 10, **kwargs: Any
    ) -> list[dict[str, Any]]:
        if not await self.index_exists(index):
            raise ElasticsearchIndexNotFoundError(index)

        try:
            response = await self.get_client().search(
                index=index, query=query, size=size, **kwargs
            )
        except Exception as exc:
            raise ElasticsearchUnavailableError(f"检索失败：{exc}") from exc

        return [
            {"_id": hit["_id"], "_score": hit["_score"], **hit["_source"]}
            for hit in response["hits"]["hits"]
        ]


es_manager = ElasticsearchManager()
