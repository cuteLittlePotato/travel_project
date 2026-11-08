"""M0-T04 Redis 真实连接测试。

需要 backend/.env 指向可用的 Redis；不可达时整组跳过。
"""

from __future__ import annotations

import uuid

import pytest

from app.infra import redis as redis_infra

pytestmark = pytest.mark.integration


@pytest.fixture
async def redis_ready() -> None:
    if not await redis_infra.check_redis():
        pytest.skip("Redis 不可达，跳过集成测试（检查 backend/.env）")


class TestRedisConnection:
    async def test_ping_returns_pong(self, redis_ready: None) -> None:
        """DoD：PING 返回 PONG。"""
        client = redis_infra.get_client()
        assert await client.ping() is True

    async def test_check_redis_true(self, redis_ready: None) -> None:
        assert await redis_infra.check_redis() is True

    async def test_connected_to_business_db(self, redis_ready: None) -> None:
        """确认实际连的是 DB 0，不是 Langfuse 的 DB 1。"""
        from app.core.config import settings

        client = redis_infra.get_client()
        info = await client.info("keyspace")
        # DB 0 有 key 时才会出现在 keyspace 里；用一次写入确保它存在
        key = redis_infra.make_key("m0t04", "probe", uuid.uuid4().hex)
        await client.set(key, "1", ex=10)
        try:
            info = await client.info("keyspace")
            assert "db0" in info, f"应连接到 DB 0，实际 keyspace={info}"
            if settings.redis_db_langfuse:
                # 不应在 DB 1 上看到我们写入的 key
                assert client.connection_pool.connection_kwargs["db"] == 0
        finally:
            await client.delete(key)

    async def test_set_get_delete_roundtrip(self, redis_ready: None) -> None:
        client = redis_infra.get_client()
        key = redis_infra.make_key("m0t04", "roundtrip", uuid.uuid4().hex)
        try:
            await client.set(key, "hello", ex=30)
            assert await client.get(key) == "hello"
            assert await client.ttl(key) > 0
        finally:
            await client.delete(key)
        assert await client.get(key) is None

    async def test_execute_wrapper_works(self, redis_ready: None) -> None:
        """封装层的重试逻辑不影响正常命令。"""
        client = redis_infra.get_client()
        assert await redis_infra.execute(client.ping) is True

    async def test_wrong_db_client_is_rejected_before_connect(self) -> None:
        """DB 1 的客户端在创建阶段就被拒绝，不会真的连上去。"""
        from app.core.exceptions import BusinessError

        with pytest.raises(BusinessError):
            redis_infra.create_client(db=redis_infra.LANGFUSE_DB)
