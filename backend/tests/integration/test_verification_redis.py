"""M01-T03 验证码服务的真实 Redis 集成测试。

验证 FakeRedis 通过的逻辑在真实 Redis 上同样成立，
特别是 SET NX EX 的原子性（60 秒间隔的核心）。

Redis 不可达时整组跳过。
"""

from __future__ import annotations

import uuid

import pytest

from app.infra import redis as redis_infra
from app.modules.account import verification as v
from app.modules.account.constants import VerifyScene

pytestmark = pytest.mark.integration


@pytest.fixture
async def redis_ready() -> None:
    if not await redis_infra.check_redis():
        pytest.skip("Redis 不可达")
    # 清空本次测试可能残留的 key
    client = redis_infra.get_client()
    keys = await client.keys(f"{redis_infra.settings.redis_key_prefix}:verify:*")
    if keys:
        await client.delete(*keys)


@pytest.fixture
async def clean_target() -> str:
    """每次用不同的手机号，避免测试间互相干扰。"""
    return f"139{uuid.uuid4().int % 100000000:08d}"


class TestRealRedisInterval:
    async def test_set_nx_is_atomic(
        self, redis_ready: None, clean_target: str
    ) -> None:
        """SET NX EX 在真实 Redis 上是原子的，并发只有一次成功。"""
        import asyncio

        client = redis_infra.get_client()
        key = v._interval_key(clean_target)

        async def try_acquire() -> bool:
            return bool(await client.set(key, "1", ex=60, nx=True))

        results = await asyncio.gather(*[try_acquire() for _ in range(10)])
        assert sum(results) == 1, "并发下应只有一次成功"

        await client.delete(key)

    async def test_interval_ttl(self, redis_ready: None, clean_target: str) -> None:
        client = redis_infra.get_client()
        key = v._interval_key(clean_target)
        await client.set(key, "1", ex=60, nx=True)

        ttl = await client.ttl(key)
        assert 55 <= ttl <= 60

        await client.delete(key)


class TestRealRedisCodeLifecycle:
    async def test_code_stored_with_ttl(
        self, redis_ready: None, clean_target: str
    ) -> None:
        client = redis_infra.get_client()
        key = v._code_key(VerifyScene.REGISTER, clean_target)

        await client.set(key, "123456", ex=300)
        assert await client.get(key) == "123456"

        ttl = await client.ttl(key)
        assert 295 <= ttl <= 300

        await client.delete(key)

    async def test_rate_counter_increments(
        self, redis_ready: None, clean_target: str
    ) -> None:
        client = redis_infra.get_client()
        key = v._rate_key(clean_target)

        assert await client.incr(key) == 1
        assert await client.incr(key) == 2
        assert await client.get(key) == "2"

        await client.delete(key)


class TestKeysUseBusinessDb:
    async def test_keys_land_in_db0(self, redis_ready: None, clean_target: str) -> None:
        """M0-T04：业务 key 必须落在 DB 0，不能污染 Langfuse 的 DB 1。"""
        client = redis_infra.get_client()
        assert client.connection_pool.connection_kwargs["db"] == 0

        key = v._code_key(VerifyScene.REGISTER, clean_target)
        await client.set(key, "x", ex=10)
        try:
            info = await client.info("keyspace")
            assert "db0" in info
        finally:
            await client.delete(key)


class TestSequentialSend:
    async def test_two_sends_blocked(
        self, redis_ready: None, clean_target: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """真实 Redis 上验证 60 秒间隔。"""
        from app.infra.sms import SmsResult

        async def fake_send(phone: str, code: str) -> SmsResult:
            return SmsResult(success=True, debug_code=code)

        monkeypatch.setattr(v.sms_sender, "send_code", fake_send)

        await v.send_verify_code(VerifyScene.REGISTER, clean_target)

        with pytest.raises(v.SendTooFrequentError) as exc_info:
            await v.send_verify_code(VerifyScene.REGISTER, clean_target)

        assert exc_info.value.code == 10003
        assert exc_info.value.http_status == 429
