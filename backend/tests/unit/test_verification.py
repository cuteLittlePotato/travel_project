"""M01-T03 验证码服务的测试。

覆盖 DoD：
    1. 60 秒内重复发送返回 10003（HTTP 429）
    2. 每日超过 5 次返回 10003
    3. 验证码错误或过期返回业务异常
    4. 验证码不在响应体中返回

用 fake Redis 而非真实实例，保证测试快速且可并行。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest

from app.core.config import settings
from app.core.exceptions import ErrorCode
from app.infra import redis as redis_infra
from app.modules.account import verification as v
from app.modules.account.constants import (
    VERIFY_CODE_DAILY_LIMIT,
    VERIFY_CODE_LENGTH,
    VERIFY_CODE_TTL_SECONDS,
    BindingProvider,
    VerifyScene,
)

# ============================================================
# Fake Redis
# ============================================================


class FakeRedis:
    """最小可用的内存 Redis 替身。

    只实现验证码服务用到的命令：get / set / set(nx,ex) / delete / incr / decr / expire / ttl。
    """

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._expiry: dict[str, float] = {}

    def _expired(self, key: str) -> bool:
        exp = self._expiry.get(key)
        if exp is None:
            return False
        if time.monotonic() >= exp:
            self._data.pop(key, None)
            self._expiry.pop(key, None)
            return True
        return False

    async def get(self, key: str) -> str | None:
        if self._expired(key):
            return None
        return self._data.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        if nx and not self._expired(key) and key in self._data:
            return None
        self._data[key] = value
        if ex:
            self._expiry[key] = time.monotonic() + ex
        return True

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._data:
                del self._data[key]
                self._expiry.pop(key, None)
                count += 1
        return count

    async def incr(self, key: str) -> int:
        current = int(self._data.get(key, "0")) + 1
        self._data[key] = str(current)
        return current

    async def decr(self, key: str) -> int:
        current = int(self._data.get(key, "0")) - 1
        self._data[key] = str(current)
        return current

    async def expire(self, key: str, seconds: int) -> bool:
        self._expiry[key] = time.monotonic() + seconds
        return True

    async def ttl(self, key: str) -> int:
        exp = self._expiry.get(key)
        if exp is None:
            return -1
        return max(int(exp - time.monotonic()), -2)


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    client = FakeRedis()
    monkeypatch.setattr(redis_infra, "get_client", lambda: client)
    # verification 模块直接引用 get_client，需一并替换
    monkeypatch.setattr(v.redis_infra, "get_client", lambda: client)
    return client


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """记录「发送」了哪些验证码，不真的走短信/邮件。"""
    calls: list[tuple[str, str]] = []

    async def fake_sms(phone: str, code: str) -> Any:
        calls.append((phone, code))
        from app.infra.sms import SmsResult

        return SmsResult(success=True, debug_code=code)

    async def fake_email(to: str, code: str, ttl: int = 300) -> Any:
        calls.append((to, code))
        from app.infra.email import EmailResult

        return EmailResult(success=True, debug_code=code)

    monkeypatch.setattr(v.sms_sender, "send_code", fake_sms)
    monkeypatch.setattr(v.email_sender, "send_code", fake_email)
    return calls


# ============================================================
# 目标格式
# ============================================================


class TestTargetDetection:
    @pytest.mark.parametrize(
        "phone", ["13800138000", "19912345678", "15012345678"]
    )
    def test_phone_detected(self, phone: str) -> None:
        assert v.detect_target_type(phone) is BindingProvider.PHONE

    @pytest.mark.parametrize(
        "email", ["a@b.com", "user.name@example.co.uk", "x+tag@mail.cn"]
    )
    def test_email_detected(self, email: str) -> None:
        assert v.detect_target_type(email) is BindingProvider.EMAIL

    @pytest.mark.parametrize(
        "bad", ["", "12345", "1234567890", "123456789012", "abc", "a@b", "@b.com", "a b@c.com"]
    )
    def test_invalid_rejected(self, bad: str) -> None:
        with pytest.raises(v.VerifyCodeError) as exc_info:
            v.detect_target_type(bad)
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED


# ============================================================
# 验证码生成
# ============================================================


class TestCodeGeneration:
    def test_length_and_charset(self) -> None:
        for _ in range(50):
            code = v.generate_code()
            assert len(code) == VERIFY_CODE_LENGTH
            assert code.isdigit()

    def test_is_random(self) -> None:
        """100 次生成不应全部相同（用 secrets 而非固定值）。"""
        codes = {v.generate_code() for _ in range(100)}
        assert len(codes) > 90


# ============================================================
# DoD 1：60 秒间隔
# ============================================================


class TestSendInterval:
    async def test_first_send_succeeds(self, fake_redis: FakeRedis, sent: list) -> None:
        result = await v.send_verify_code(VerifyScene.REGISTER, "13800138000")
        assert result.expires_in == VERIFY_CODE_TTL_SECONDS
        assert len(sent) == 1

    async def test_second_send_within_60s_rejected(
        self, fake_redis: FakeRedis, sent: list
    ) -> None:
        """DoD：60 秒内重复发送返回 10003（HTTP 429）。"""
        await v.send_verify_code(VerifyScene.REGISTER, "13800138000")

        with pytest.raises(v.SendTooFrequentError) as exc_info:
            await v.send_verify_code(VerifyScene.REGISTER, "13800138000")

        error = exc_info.value
        assert error.code == ErrorCode.RATE_LIMITED == 10003
        assert error.http_status == 429
        assert "retry_after" in (error.data or {})

    async def test_different_targets_independent(
        self, fake_redis: FakeRedis, sent: list
    ) -> None:
        await v.send_verify_code(VerifyScene.REGISTER, "13800138000")
        await v.send_verify_code(VerifyScene.REGISTER, "13900139000")
        assert len(sent) == 2

    async def test_different_scenes_share_interval(
        self, fake_redis: FakeRedis, sent: list
    ) -> None:
        """60 秒限制按 target 计，跨 scene 也生效——防止绕过场景刷短信。"""
        await v.send_verify_code(VerifyScene.REGISTER, "13800138000")
        with pytest.raises(v.SendTooFrequentError):
            await v.send_verify_code(VerifyScene.LOGIN, "13800138000")


# ============================================================
# DoD 2：每日 5 次
# ============================================================


class TestDailyLimit:
    async def test_fifth_send_allowed_sixth_rejected(
        self, fake_redis: FakeRedis, sent: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DoD：每日超过 5 次返回 10003。"""
        # 每次发送前清掉 60 秒间隔 key，模拟「等了一分钟再发」
        for _ in range(VERIFY_CODE_DAILY_LIMIT):
            await fake_redis.delete(v._interval_key("13800138000"))
            await v.send_verify_code(VerifyScene.REGISTER, "13800138000")

        assert len(sent) == VERIFY_CODE_DAILY_LIMIT

        await fake_redis.delete(v._interval_key("13800138000"))
        with pytest.raises(v.SendTooFrequentError) as exc_info:
            await v.send_verify_code(VerifyScene.REGISTER, "13800138000")

        assert exc_info.value.code == 10003
        assert "上限" in exc_info.value.message

    async def test_rate_key_expires_in_24h(
        self, fake_redis: FakeRedis, sent: list
    ) -> None:
        await v.send_verify_code(VerifyScene.REGISTER, "13800138000")
        ttl = await fake_redis.ttl(v._rate_key("13800138000"))
        assert 86000 < ttl <= 86400


# ============================================================
# DoD 3：校验
# ============================================================


class TestVerification:
    async def test_correct_code_passes(
        self, fake_redis: FakeRedis, sent: list
    ) -> None:
        await v.send_verify_code(VerifyScene.REGISTER, "13800138000")
        code = sent[0][1]
        assert await v.verify_code(VerifyScene.REGISTER, "13800138000", code) is True

    async def test_code_is_one_time_use(
        self, fake_redis: FakeRedis, sent: list
    ) -> None:
        """校验成功后立即删除，防止重放。"""
        await v.send_verify_code(VerifyScene.REGISTER, "13800138000")
        code = sent[0][1]

        assert await v.verify_code(VerifyScene.REGISTER, "13800138000", code) is True
        with pytest.raises(v.InvalidVerifyCodeError) as exc_info:
            await v.verify_code(VerifyScene.REGISTER, "13800138000", code)
        assert "过期" in exc_info.value.message

    async def test_wrong_code_rejected(
        self, fake_redis: FakeRedis, sent: list
    ) -> None:
        await v.send_verify_code(VerifyScene.REGISTER, "13800138000")
        with pytest.raises(v.InvalidVerifyCodeError) as exc_info:
            await v.verify_code(VerifyScene.REGISTER, "13800138000", "000000")
        assert exc_info.value.code == ErrorCode.INVALID_VERIFY_CODE

    async def test_expired_code_rejected(self, fake_redis: FakeRedis) -> None:
        """验证码不存在时视为过期。"""
        with pytest.raises(v.InvalidVerifyCodeError) as exc_info:
            await v.verify_code(VerifyScene.REGISTER, "13800138000", "123456")
        assert "过期" in exc_info.value.message

    async def test_wrong_scene_rejected(
        self, fake_redis: FakeRedis, sent: list
    ) -> None:
        """注册场景的验证码不能用于登录。"""
        await v.send_verify_code(VerifyScene.REGISTER, "13800138000")
        code = sent[0][1]

        with pytest.raises(v.InvalidVerifyCodeError):
            await v.verify_code(VerifyScene.LOGIN, "13800138000", code)

    async def test_failed_attempts_invalidate_code(
        self, fake_redis: FakeRedis, sent: list
    ) -> None:
        """边界：多次校验失败后验证码作废，防止暴力枚举。"""
        await v.send_verify_code(VerifyScene.REGISTER, "13800138000")
        code = sent[0][1]

        for attempt in range(v.MAX_VERIFY_ATTEMPTS - 1):
            with pytest.raises(v.InvalidVerifyCodeError) as exc_info:
                await v.verify_code(VerifyScene.REGISTER, "13800138000", "000000")
            assert f"还可尝试 {v.MAX_VERIFY_ATTEMPTS - attempt - 1} 次" in exc_info.value.message

        # 第 5 次失败后作废
        with pytest.raises(v.InvalidVerifyCodeError) as exc_info:
            await v.verify_code(VerifyScene.REGISTER, "13800138000", "000000")
        assert "次数过多" in exc_info.value.message

        # 此时即使输对也无效
        with pytest.raises(v.InvalidVerifyCodeError):
            await v.verify_code(VerifyScene.REGISTER, "13800138000", code)

    async def test_remaining_attempts(self, fake_redis: FakeRedis, sent: list) -> None:
        await v.send_verify_code(VerifyScene.REGISTER, "13800138000")
        assert await v.get_remaining_attempts(VerifyScene.REGISTER, "13800138000") == 5

        with pytest.raises(v.InvalidVerifyCodeError):
            await v.verify_code(VerifyScene.REGISTER, "13800138000", "000000")
        assert await v.get_remaining_attempts(VerifyScene.REGISTER, "13800138000") == 4


# ============================================================
# DoD 4：验证码不出现在响应中
# ============================================================


class TestCodeNotLeaked:
    async def test_production_returns_no_debug_code(
        self, fake_redis: FakeRedis, sent: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """生产环境绝不返回验证码。"""
        monkeypatch.setattr(settings, "app_env", "production")
        result = await v.send_verify_code(VerifyScene.REGISTER, "13800138000")
        assert result.debug_code is None

    async def test_development_may_return_debug_code(
        self, fake_redis: FakeRedis, sent: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """开发环境返回 debug_code 便于联调，但字段名明确标注为 debug。"""
        monkeypatch.setattr(settings, "app_env", "development")
        result = await v.send_verify_code(VerifyScene.REGISTER, "13800138000")
        assert result.debug_code is not None
        assert result.debug_code == sent[0][1]

    def test_send_result_shape(self) -> None:
        """响应只含 expires_in（API §3.1）。"""
        result = v.SendResult(expires_in=300)
        assert result.expires_in == 300
        assert result.debug_code is None


# ============================================================
# 边界：发送失败回滚
# ============================================================


class TestSendFailureRollback:
    async def test_failure_releases_interval_lock(
        self, fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """短信服务不可用时，应释放 60 秒锁，允许用户立即重试。"""
        from app.infra.sms import SmsUnavailableError

        async def fail(*_a: Any, **_k: Any) -> None:
            raise SmsUnavailableError("down")

        monkeypatch.setattr(v.sms_sender, "send_code", fail)

        with pytest.raises(v.VerifyCodeError):
            await v.send_verify_code(VerifyScene.REGISTER, "13800138000")

        # 间隔 key 已释放，可立即重试
        assert await fake_redis.get(v._interval_key("13800138000")) is None
        # 验证码也已清理
        assert await fake_redis.get(v._code_key(VerifyScene.REGISTER, "13800138000")) is None

    async def test_failure_does_not_consume_daily_quota(
        self, fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """发送失败不应占用当日次数。"""
        from app.infra.sms import SmsUnavailableError

        async def fail(*_a: Any, **_k: Any) -> None:
            raise SmsUnavailableError("down")

        monkeypatch.setattr(v.sms_sender, "send_code", fail)

        with pytest.raises(v.VerifyCodeError):
            await v.send_verify_code(VerifyScene.REGISTER, "13800138000")

        assert await fake_redis.get(v._rate_key("13800138000")) in (None, "0")


class TestRedisKeys:
    def test_code_key_format(self) -> None:
        key = v._code_key(VerifyScene.REGISTER, "13800138000")
        assert key == "travel:verify:register:13800138000"

    def test_fail_key_format(self) -> None:
        key = v._fail_key(VerifyScene.LOGIN, "a@b.com")
        assert key == "travel:verify:fail:login:a@b.com"

    def test_rate_key_has_date(self) -> None:
        key = v._rate_key("13800138000")
        assert key.startswith("travel:verify:rate:13800138000:")
        assert len(key.split(":")) == 5

    def test_all_keys_use_business_db(self) -> None:
        """M0-T04 约定：业务 key 必须带 travel: 前缀且走 DB 0。"""
        for key in (
            v._code_key(VerifyScene.REGISTER, "x"),
            v._fail_key(VerifyScene.REGISTER, "x"),
            v._rate_key("x"),
            v._interval_key("x"),
        ):
            assert key.startswith(f"{settings.redis_key_prefix}:")


# ============================================================
# 开发环境日志输出验证码
# ============================================================


class TestDebugCodeLogging:
    """开发环境把验证码打到日志，省去查邮件/Redis。

    生产环境绝不能打印——那等于把登录凭据写进日志。
    """

    async def test_logs_code_in_development(
        self, fake_redis, caplog
    ) -> None:
        import logging

        from app.modules.account import verification

        if verification._is_production():
            pytest.skip("当前为生产环境配置，本用例只验证开发环境")

        target = f"log_{uuid.uuid4().hex[:8]}@example.com"

        with caplog.at_level(logging.WARNING):
            await verification.send_verify_code(
                verification.VerifyScene.REGISTER, target
            )

        # 日志里应该能直接看到验证码
        stored = await fake_redis.get(
            verification._code_key(verification.VerifyScene.REGISTER, target)
        )
        assert stored is not None
        assert any(stored in record.message for record in caplog.records), (
            "开发环境日志中应包含验证码"
        )

    async def test_log_marked_as_development(
        self, fake_redis, caplog
    ) -> None:
        """日志文案带「开发环境」标记，避免被误认为生产泄露。"""
        import logging

        from app.modules.account import verification

        if verification._is_production():
            pytest.skip("当前为生产环境配置")

        target = f"log_{uuid.uuid4().hex[:8]}@example.com"

        with caplog.at_level(logging.WARNING):
            await verification.send_verify_code(
                verification.VerifyScene.LOGIN, target
            )

        assert any("开发环境" in record.message for record in caplog.records)

    def test_not_production_check(self) -> None:
        """``_is_production`` 只看 app_env，不依赖其他配置。"""
        from app.core.config import settings
        from app.modules.account import verification

        original = settings.app_env
        try:
            settings.app_env = "production"
            assert verification._is_production() is True

            settings.app_env = "development"
            assert verification._is_production() is False
        finally:
            settings.app_env = original
