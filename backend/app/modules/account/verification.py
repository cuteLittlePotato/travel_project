"""验证码生成、存储、校验与限流（M01-T03）。

需求 §2.1.1 / API §3.1：
    - 有效期 5 分钟
    - 同目标 60 秒内不可重复发送
    - 同目标每日最多 5 次
    - 校验失败多次后作废

Redis 存储（M0-T04 约定，业务只用 DB 0）：

    verify:{scene}:{target}       验证码明文，TTL 5 分钟
    verify:fail:{scene}:{target}  失败计数，TTL 5 分钟（与验证码同寿命）
    verify:rate:{target}:{date}   当日发送次数，TTL 24 小时

**为什么验证码存明文**：验证码本身是一次性短字符串，存哈希反而无法比对
（用户输入的是原文）。防护靠 TTL + 失败次数上限 + 单次使用即删除。

**为什么用 Redis 不用 PG**：验证码是短期临时数据，不需要持久化，
Redis 的 TTL 天然适配。Redis 不可用时无法发送验证码，属于可接受降级
（用户可改用密码登录）。
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.infra import redis as redis_infra
from app.infra.email import (
    EmailUnavailableError,
    email_sender,
)
from app.infra.sms import SmsUnavailableError, sms_sender
from app.modules.account.constants import (
    EMAIL_PATTERN,
    PHONE_PATTERN,
    VERIFY_CODE_DAILY_LIMIT,
    VERIFY_CODE_LENGTH,
    VERIFY_CODE_SEND_INTERVAL_SECONDS,
    VERIFY_CODE_TTL_SECONDS,
    BindingProvider,
    VerifyScene,
)

logger = logging.getLogger(__name__)

#: 单个验证码允许的最大校验失败次数，超过即作废
MAX_VERIFY_ATTEMPTS = 5


class VerifyCodeError(BusinessError):
    """验证码相关错误。"""


class SendTooFrequentError(BusinessError):
    """发送过于频繁。HTTP 429 + 10003。"""

    def __init__(self, message: str = "发送过于频繁，请稍后再试", retry_after: int = 0) -> None:
        super().__init__(
            ErrorCode.RATE_LIMITED,
            message,
            data={"retry_after": retry_after} if retry_after else None,
            http_status=429,
        )


class InvalidVerifyCodeError(BusinessError):
    """验证码错误、过期或已使用。"""

    def __init__(self, message: str = "验证码错误或已过期") -> None:
        super().__init__(ErrorCode.INVALID_VERIFY_CODE, message, http_status=400)


@dataclass(frozen=True, slots=True)
class SendResult:
    """发送结果。

    ``debug_code`` 仅在开发环境（``APP_ENV != production`` 且 Mock 模式）有值，
    供本地联调时直接拿到验证码。**生产环境必须为 None。**
    """

    expires_in: int
    debug_code: str | None = None


# ============================================================
# 目标识别与格式校验
# ============================================================


def detect_target_type(target: str) -> BindingProvider:
    """按格式判断是手机号还是邮箱。"""
    if PHONE_PATTERN.fullmatch(target):
        return BindingProvider.PHONE
    if EMAIL_PATTERN.fullmatch(target):
        return BindingProvider.EMAIL
    raise VerifyCodeError(
        ErrorCode.VALIDATION_FAILED,
        "请输入正确的手机号或邮箱",
        data={"errors": [{"field": "target", "reason": "手机号或邮箱格式不正确"}]},
    )


def _is_production() -> bool:
    return settings.app_env == "production"


# ============================================================
# Redis key
# ============================================================


def _code_key(scene: VerifyScene, target: str) -> str:
    return redis_infra.make_key("verify", scene.value, target)


def _fail_key(scene: VerifyScene, target: str) -> str:
    return redis_infra.make_key("verify", "fail", scene.value, target)


def _rate_key(target: str) -> str:
    """按自然日限流。用 UTC 日期，与数据库 TIMESTAMPTZ 策略一致。"""
    today = datetime.now(UTC).strftime("%Y%m%d")
    return redis_infra.make_key("verify", "rate", target, today)


def _interval_key(target: str) -> str:
    """60 秒间隔控制。SET NX EX 60 实现原子占位。"""
    return redis_infra.make_key("verify", "interval", target)


# ============================================================
# 发送
# ============================================================


def generate_code() -> str:
    """生成 6 位数字验证码。

    用 ``secrets`` 而非 ``random``：``random`` 是可预测的伪随机，
    验证码场景下可被暴力推算。
    """
    return "".join(secrets.choice("0123456789") for _ in range(VERIFY_CODE_LENGTH))


async def send_verify_code(scene: VerifyScene, target: str) -> SendResult:
    """发送验证码。

    流程：
        1. 校验目标格式
        2. 60 秒间隔检查（Redis SET NX EX，原子）
        3. 当日次数检查
        4. 生成并存储验证码
        5. 通过短信/邮件发送
        6. 发送失败则清理已写入的 key，允许用户重试

    抛错：
        ``SendTooFrequentError``  60 秒内重复发送 / 当日超限（429 + 10003）
        ``VerifyCodeError``       目标格式非法
    """
    target_type = detect_target_type(target)
    client = redis_infra.get_client()

    # ---------- 1. 60 秒间隔 ----------
    interval_key = _interval_key(target)
    acquired = await client.set(
        interval_key, "1", ex=VERIFY_CODE_SEND_INTERVAL_SECONDS, nx=True
    )
    if not acquired:
        ttl = await client.ttl(interval_key)
        raise SendTooFrequentError(
            f"发送过于频繁，请 {max(ttl, 1)} 秒后再试", retry_after=max(ttl, 1)
        )

    # ---------- 2. 当日次数 ----------
    rate_key = _rate_key(target)
    count = await client.incr(rate_key)
    if count == 1:
        # 首次计数时设置 24 小时过期，避免 key 永久堆积
        await client.expire(rate_key, 86400)

    if count > VERIFY_CODE_DAILY_LIMIT:
        # 超限时释放间隔占位，让用户次日可立即发送，不必等 60 秒
        await client.delete(interval_key)
        await client.decr(rate_key)
        raise SendTooFrequentError(
            f"今日发送次数已达上限（{VERIFY_CODE_DAILY_LIMIT} 次），请明天再试"
        )

    # ---------- 3. 生成并存储 ----------
    code = generate_code()
    try:
        await client.set(_code_key(scene, target), code, ex=VERIFY_CODE_TTL_SECONDS)
        await client.delete(_fail_key(scene, target))
    except Exception as exc:
        await _rollback(interval_key, rate_key)
        logger.error("验证码写入 Redis 失败: %s", exc)
        raise VerifyCodeError(ErrorCode.INTERNAL_ERROR, "验证码服务暂不可用") from exc

    # ---------- 4. 发送 ----------
    try:
        if target_type is BindingProvider.PHONE:
            result = await sms_sender.send_code(target, code)
        else:
            result = await email_sender.send_code(target, code, VERIFY_CODE_TTL_SECONDS)
    except (SmsUnavailableError, EmailUnavailableError) as exc:
        # 发送失败：清理已写入的 key，允许用户立即重试
        await _rollback(interval_key, rate_key)
        await client.delete(_code_key(scene, target))
        logger.error("验证码发送失败 scene=%s: %s", scene.value, exc)
        raise VerifyCodeError(
            ErrorCode.INTERNAL_ERROR, "验证码发送失败，请稍后重试"
        ) from exc

    # ---------- 5. 开发环境打印验证码 ----------
    if not _is_production():
        # 开发/测试环境把验证码打到日志，省去查邮件、连 Redis 或调用接口。
        # 生产环境不打印——那等于把登录凭据写进日志。
        logger.warning(
            "【开发环境】验证码 scene=%s target=%s code=%s（%d 秒内有效）",
            scene.value,
            target,
            code,
            VERIFY_CODE_TTL_SECONDS,
        )

    # ---------- 6. 返回 ----------
    debug_code = None if _is_production() else result.debug_code
    return SendResult(expires_in=VERIFY_CODE_TTL_SECONDS, debug_code=debug_code)


async def _rollback(interval_key: str, rate_key: str) -> None:
    """发送失败时回滚限流计数，避免用户被无端锁定。"""
    client = redis_infra.get_client()
    try:
        await client.delete(interval_key)
        await client.decr(rate_key)
    except Exception:
        logger.warning("回滚限流计数失败", exc_info=True)


# ============================================================
# 校验
# ============================================================


async def verify_code(scene: VerifyScene, target: str, code: str) -> bool:
    """校验验证码。

    - 校验成功：**立即删除验证码**（一次性使用），防止重放
    - 校验失败：累加失败次数，达到上限即作废（防止暴力枚举 6 位验证码）
    - 验证码不存在：说明已过期或已使用

    抛错：
        ``InvalidVerifyCodeError`` 验证码错误/过期/已使用
    """
    client = redis_infra.get_client()
    code_key = _code_key(scene, target)
    fail_key = _fail_key(scene, target)

    stored = await client.get(code_key)
    if stored is None:
        raise InvalidVerifyCodeError("验证码已过期，请重新获取")

    if not secrets.compare_digest(stored, code):
        # 用 compare_digest 而非 ==，避免时序攻击
        attempts = await client.incr(fail_key)
        if attempts == 1:
            await client.expire(fail_key, VERIFY_CODE_TTL_SECONDS)

        if attempts >= MAX_VERIFY_ATTEMPTS:
            # 失败次数达上限，作废验证码
            await client.delete(code_key, fail_key)
            raise InvalidVerifyCodeError("验证码错误次数过多，请重新获取")

        remaining = MAX_VERIFY_ATTEMPTS - attempts
        raise InvalidVerifyCodeError(f"验证码错误，还可尝试 {remaining} 次")

    # 成功：一次性使用
    await client.delete(code_key, fail_key)
    return True


async def consume_code_silently(scene: VerifyScene, target: str) -> None:
    """静默清除验证码。

    用于「验证通过但后续步骤失败」的场景（如注册时密码强度不达标），
    避免验证码被白白消耗。调用方若已完成业务，则不应调用本函数。
    """
    client = redis_infra.get_client()
    await client.delete(_code_key(scene, target), _fail_key(scene, target))


async def get_remaining_attempts(scene: VerifyScene, target: str) -> int:
    """剩余可尝试次数，供接口返回提示。"""
    client = redis_infra.get_client()
    attempts = await client.get(_fail_key(scene, target))
    used = int(attempts) if attempts else 0
    return max(MAX_VERIFY_ATTEMPTS - used, 0)
