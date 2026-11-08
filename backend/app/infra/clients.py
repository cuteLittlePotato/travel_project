"""外部服务聚合入口。

各服务的具体实现在独立模块中：
    - ``app.infra.milvus``         向量检索
    - ``app.infra.neo4j``          知识图谱
    - ``app.infra.elasticsearch``  关键词检索
    - ``app.infra.storage``        对象存储

本模块只负责批量健康检查与统一关闭，供 ``/api/health/ready`` 与应用
``lifespan`` 使用。
"""

from __future__ import annotations

import asyncio

from app.infra.elasticsearch import es_manager
from app.infra.milvus import milvus_manager
from app.infra.neo4j import neo4j_manager
from app.infra.storage import storage_manager

__all__ = [
    "check_all",
    "close_all",
    "es_manager",
    "milvus_manager",
    "neo4j_manager",
    "storage_manager",
]

#: 服务名 -> 管理器。运行时解析 ``check``，避免在导入期绑定方法
#: （绑定后替换管理器的方法不会生效，也让测试难以注入替身）
_MANAGERS: dict[str, object] = {
    "milvus": milvus_manager,
    "neo4j": neo4j_manager,
    "elasticsearch": es_manager,
    "minio": storage_manager,
}


async def check_all() -> dict[str, bool]:
    """并发探测四个服务。

    任一服务抛异常都记为不可用，不向上抛出——就绪探针的价值在于
    故障时仍能给出逐项诊断。
    """
    names = list(_MANAGERS)
    results = await asyncio.gather(
        *(_MANAGERS[name].check() for name in names),  # type: ignore[attr-defined]
        return_exceptions=True,
    )
    return {
        name: result is True
        for name, result in zip(names, results, strict=True)
    }


async def close_all() -> None:
    """应用关闭时释放连接。"""
    await neo4j_manager.close()
    await es_manager.close()
    milvus_manager.close()
    storage_manager.close()
