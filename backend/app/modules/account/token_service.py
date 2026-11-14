"""Token 刷新与轮换（M01-T08）。

**轮换机制**：每次刷新都签发新的 Refresh Token，旧的立即失效。
这样即使 Refresh Token 被窃取，攻击者只能用一次——合法用户下次刷新时会失败，
从而发现异常。

实现方式（Redis 黑名单）：

    travel:token:revoked:{jti}   已失效的 Refresh Token ID，TTL = 剩余有效期

**为什么用 jti 而非 Token 全文**：Token 可能很长（含用户声明），
存 jti 只需 32 字符，Redis 内存占用小。

**为什么是黑名单而非白名单**：白名单需要为每个 Token 存一条记录，
用户多了以后内存占用高。黑名单只存「已被使用过」的 Token，
正常使用下数量很少（每次刷新一条，但 TTL 只有 7 天）。

Redis 不可用时的降级：**拒绝刷新**。因为无法保证轮换的原子性，
放行会导致旧 Token 可重放。用户重新登录即可恢复。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.core.security import (
    create_token_pair,
    decode_token,
    verify_token_version,
)
from app.infra import redis as redis_infra
from app.modules.account.constants import UserStatus
from app.modules.account.repository import AccountRepository

logger = logging.getLogger(__name__)


class RefreshTokenRevokedError(BusinessError):
    """Refresh Token 已失效（被使用过、伪造或过期）。HTTP 401 + 11010。"""

    def __init__(self, message: str = "登录状态已失效，请重新登录") -> None:
        super().__init__(ErrorCode.REFRESH_TOKEN_REVOKED, message, http_status=401)


class RefreshUnavailableError(BusinessError):
    """Redis 不可用，无法保证轮换的原子性。HTTP 503。"""

    def __init__(self) -> None:
        super().__init__(
            ErrorCode.INTERNAL_ERROR,
            "服务暂不可用，请稍后重试",
            http_status=503,
        )


@dataclass(frozen=True, slots=True)
class RefreshResult:
    user_id: uuid.UUID
    access_token: str
    refresh_token: str
    expires_in: int


def _revoked_key(jti: str) -> str:
    return redis_infra.make_key("token", "revoked", jti)


async def _consume_jti(jti: str, ttl_seconds: int) -> bool:
    """原子地「占用」一个 jti。

    用 ``SET NX EX``：返回 True 表示首次使用（可用），
    False 表示已被使用过（重放攻击或正常轮换后的旧 Token）。

    这是轮换机制的核心——必须原子，否则两个并发刷新可能都成功。
    """
    client = redis_infra.get_client()
    try:
        acquired = await client.set(
            _revoked_key(jti), "1", ex=max(ttl_seconds, 1), nx=True
        )
    except Exception as exc:
        logger.error("Redis 不可用，拒绝刷新: %s", exc)
        raise RefreshUnavailableError() from exc

    return bool(acquired)


async def refresh_tokens(session: AsyncSession, *, refresh_token: str) -> RefreshResult:
    """刷新双 Token（API §3.6）。

    流程：
        1. 解析并校验 Refresh Token 的签名、类型、过期
        2. 取出 ``jti`` 与剩余有效期
        3. 原子占用 jti（失败 = 已重放，拒绝）
        4. 查账号状态（封禁 / 注销）
        5. 校验 ``token_version``
        6. 签发新双 Token

    任一步失败都抛 ``BusinessError``，由全局处理器转成统一响应。
    """
    # ---------- 1. 解析 ----------
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except BusinessError:
        # decode_token 已经抛了 401（过期/无效），统一为 11010
        raise RefreshTokenRevokedError() from None

    # ---------- 2. jti 与剩余有效期 ----------
    import time

    claims = _decode_claims(refresh_token)
    jti = claims.get("jti")
    if not jti:
        raise RefreshTokenRevokedError()

    exp = int(claims.get("exp", 0))
    remaining = max(exp - int(time.time()), 1)

    # ---------- 3. 原子占用 ----------
    if not await _consume_jti(jti, remaining):
        logger.warning("Refresh Token 重放 user_id=%s", payload.subject_id)
        raise RefreshTokenRevokedError()

    # ---------- 4. 账号状态 ----------
    repo = AccountRepository(session)
    user = await repo.users.get_by_id(payload.subject_id)

    if user is None:
        raise RefreshTokenRevokedError()
    if user.status == UserStatus.BANNED:
        # 封禁状态：即使 Refresh Token 有效也不能换新 Token
        raise BusinessError(
            ErrorCode.ACCOUNT_BANNED, "该账号已被封禁", http_status=403
        )
    if user.status == UserStatus.DELETED:
        raise BusinessError(
            ErrorCode.ACCOUNT_DELETED, "该账号已注销", http_status=403
        )

    # ---------- 5. token_version ----------
    verify_token_version(payload, user.token_version)

    # ---------- 6. 签发新 Token ----------
    tokens = create_token_pair(str(user.id), "user", user.token_version)
    logger.info("Token 刷新成功 user_id=%s", user.id)

    return RefreshResult(
        user_id=user.id,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens["expires_in"],
    )


def _decode_claims(token: str) -> dict:
    """解码但不校验，只为拿 ``jti`` 与 ``exp``。

    安全性由前面的 ``decode_token`` 保证；这里只读取已验签过的载荷。
    """
    import jwt

    from app.core.config import settings

    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"verify_exp": False},
    )


async def revoke_refresh_token(refresh_token: str) -> None:
    """主动作废一个 Refresh Token（登出时用）。

    登出主要靠 ``token_version`` 自增让所有 Token 失效；
    这里额外把当前 jti 加入黑名单，缩短失效传播的窗口。
    """
    try:
        claims = _decode_claims(refresh_token)
    except Exception:
        return

    jti = claims.get("jti")
    if not jti:
        return

    import time

    remaining = max(int(claims.get("exp", 0)) - int(time.time()), 1)
    try:
        await redis_infra.get_client().set(_revoked_key(jti), "1", ex=remaining)
    except Exception:
        # 登出时 Redis 失败不影响主流程（token_version 已自增）
        logger.warning("Redis 不可用，跳过 jti 黑名单", exc_info=True)


async def is_jti_revoked(jti: str) -> bool:
    """检查 jti 是否已被使用（供测试与排查）。"""
    try:
        return bool(await redis_infra.get_client().get(_revoked_key(jti)))
    except Exception:
        return False
