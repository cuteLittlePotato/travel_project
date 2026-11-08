"""Milvus 客户端封装（向量检索）。

用途：RAG 语义检索。Collection 按知识库隔离（M09 任务设计）。
pymilvus 是同步库，所有阻塞调用都放到线程池，避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import settings
from app.infra.exceptions import MilvusUnavailableError

logger = logging.getLogger(__name__)


class MilvusManager:
    """Milvus 连接管理与常用操作封装。"""

    def __init__(self) -> None:
        self._client: Any = None

    # ---------------- 连接 ----------------

    def get_client(self) -> Any:
        """懒加载客户端。连接参数来自配置。"""
        if self._client is None:
            from pymilvus import MilvusClient

            self._client = MilvusClient(
                uri=f"http://{settings.milvus_host}:{settings.milvus_port}",
                user=settings.milvus_user or "",
                password=settings.milvus_password or "",
            )
        return self._client

    async def check(self) -> bool:
        """健康检查。不抛异常，供就绪探针使用。"""
        try:
            await asyncio.to_thread(self.get_client().list_collections)
            return True
        except Exception:
            logger.warning("Milvus 健康检查失败", exc_info=True)
            return False

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # ---------------- Collection 操作 ----------------

    async def has_collection(self, name: str) -> bool:
        try:
            return bool(await asyncio.to_thread(self.get_client().has_collection, name))
        except Exception as exc:
            raise MilvusUnavailableError(str(exc)) from exc

    async def list_collections(self) -> list[str]:
        try:
            return list(await asyncio.to_thread(self.get_client().list_collections))
        except Exception as exc:
            raise MilvusUnavailableError(str(exc)) from exc

    async def create_collection(self, name: str, dimension: int, **kwargs: Any) -> None:
        """创建 Collection。维度由 Embedding 模型决定，不可事后修改。"""
        try:
            await asyncio.to_thread(
                self.get_client().create_collection,
                collection_name=name,
                dimension=dimension,
                **kwargs,
            )
        except Exception as exc:
            raise MilvusUnavailableError(f"创建 Collection 失败：{exc}") from exc

    async def drop_collection(self, name: str) -> None:
        try:
            await asyncio.to_thread(self.get_client().drop_collection, collection_name=name)
        except Exception as exc:
            raise MilvusUnavailableError(f"删除 Collection 失败：{exc}") from exc

    async def insert(self, name: str, data: list[dict[str, Any]]) -> Any:
        try:
            return await asyncio.to_thread(
                self.get_client().insert, collection_name=name, data=data
            )
        except Exception as exc:
            raise MilvusUnavailableError(f"写入失败：{exc}") from exc

    async def delete(self, name: str, ids: list[str]) -> Any:
        try:
            return await asyncio.to_thread(
                self.get_client().delete, collection_name=name, ids=ids
            )
        except Exception as exc:
            raise MilvusUnavailableError(f"删除失败：{exc}") from exc

    async def search(
        self, name: str, data: list[list[float]], limit: int = 10, **kwargs: Any
    ) -> list[Any]:
        try:
            return await asyncio.to_thread(
                self.get_client().search,
                collection_name=name,
                data=data,
                limit=limit,
                **kwargs,
            )
        except Exception as exc:
            raise MilvusUnavailableError(f"检索失败：{exc}") from exc


milvus_manager = MilvusManager()
