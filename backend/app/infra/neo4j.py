"""Neo4j 客户端封装（知识图谱）。

**数据边界（架构 §1.4）**：Neo4j 只存储图谱结构与关系，不冗余景点业务属性。
节点仅保存实体标识（如 ``attraction_id``），名称、简介等回 PostgreSQL 补齐。
这样做的目的是消除 PG 与 Neo4j 之间的数据同步问题。
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.infra.exceptions import Neo4jNodeNotFoundError, Neo4jUnavailableError

logger = logging.getLogger(__name__)


class Neo4jManager:
    """Driver 管理与 Cypher 执行封装。"""

    def __init__(self) -> None:
        self._driver: Any = None

    # ---------------- 连接 ----------------

    def get_driver(self) -> Any:
        if self._driver is None:
            from neo4j import AsyncGraphDatabase

            self._driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
        return self._driver

    async def check(self) -> bool:
        try:
            await self.execute("RETURN 1 AS ok")
            return True
        except Exception:
            logger.warning("Neo4j 健康检查失败", exc_info=True)
            return False

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None

    # ---------------- Cypher 执行 ----------------

    async def execute(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """执行 Cypher 并返回全部结果的 dict 列表。"""
        try:
            async with self.get_driver().session(database=settings.neo4j_database) as session:
                result = await session.run(cypher, params or {})
                return [record.data() async for record in result]
        except Neo4jNodeNotFoundError:
            raise
        except Exception as exc:
            raise Neo4jUnavailableError(str(exc)) from exc

    async def execute_single(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """执行并返回首条结果；无结果返回 None。"""
        records = await self.execute(cypher, params)
        return records[0] if records else None

    async def node_exists(self, label: str, node_id: str) -> bool:
        """按实体标识检查节点是否存在。

        ``label`` 来自代码中的固定枚举，不来自用户输入，故可安全拼接；
        节点标识一律通过参数传递，避免 Cypher 注入。
        """
        _assert_label(label)
        record = await self.execute_single(
            f"MATCH (n:{label} {{entity_id: $entity_id}}) RETURN count(n) AS cnt",
            {"entity_id": node_id},
        )
        return bool(record and record.get("cnt", 0) > 0)

    async def require_node(self, label: str, node_id: str) -> dict[str, Any]:
        """节点不存在时抛 ``Neo4jNodeNotFoundError``（404），与「服务不可用」区分。"""
        _assert_label(label)
        record = await self.execute_single(
            f"MATCH (n:{label} {{entity_id: $entity_id}}) RETURN n",
            {"entity_id": node_id},
        )
        if record is None:
            raise Neo4jNodeNotFoundError(f"{label} 节点不存在：{node_id}")
        return record

    async def verify_connectivity(self) -> None:
        """显式校验连接，启动时可用。"""
        try:
            await self.get_driver().verify_connectivity()
        except Exception as exc:
            raise Neo4jUnavailableError(str(exc)) from exc


#: 允许出现在 Cypher 标签位置的字符集。
#: 标签无法参数化，只能拼接，因此必须严格限制，防止注入。
_SAFE_LABEL_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def _assert_label(label: str) -> None:
    if not label or not set(label) <= _SAFE_LABEL_CHARS:
        raise ValueError(f"非法的 Cypher 标签: {label!r}")


neo4j_manager = Neo4jManager()
