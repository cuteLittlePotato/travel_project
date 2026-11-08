"""JWT 签发校验与密码哈希。

Token 设计（API 设计 §1.2）：
    - Access Token 有效期 30 分钟，Refresh Token 7 天
    - 载荷含 ``user_type``（``user``/``admin``）与 ``token_version``
    - ``token_version`` 与用户表比对，登出/改密/封禁后旧 Token 立即失效

攻击面防护：
    - 算法白名单，显式拒绝 ``alg=none`` 与算法混淆
    - 强制校验 ``exp``/``sub``/``user_type``/``token_version`` 四个必需声明
    - 所有校验失败统一转 ``UnauthorizedError``（401 / 11001），不泄露具体原因给前端
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import UnauthorizedError

UserType = Literal["user", "admin"]
TokenType = Literal["access", "refresh"]

#: 允许的签名算法。禁止 none / 非对称算法混用
_ALGORITHM_WHITELIST = frozenset({"HS256", "HS384", "HS512"})

#: bcrypt 只处理前 72 字节，超出部分会被静默截断，导致不同密码可能等价
_BCRYPT_MAX_BYTES = 72

#: JWT 必需声明
_REQUIRED_CLAIMS = ("exp", "sub", "user_type", "token_version")


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """解码后的 Token 载荷，避免业务层反复做类型转换。"""

    subject_id: uuid.UUID
    user_type: UserType
    token_version: int
    token_type: TokenType


# ============================================================
# 密码哈希
# ============================================================


def hash_password(plain: str) -> str:
    """生成 bcrypt 哈希。

    超过 72 字节的密码会被 bcrypt 截断，这里显式拒绝而不是静默截断，
    否则两个前 72 字节相同的密码会被判定为同一个。
    """
    encoded = plain.encode("utf-8")
    if len(encoded) > _BCRYPT_MAX_BYTES:
        raise ValueError(f"密码长度不能超过 {_BCRYPT_MAX_BYTES} 字节")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验密码。哈希格式非法或超长时按失败处理，不向外抛异常。"""
    encoded = plain.encode("utf-8")
    if len(encoded) > _BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ============================================================
# Token 签发
# ============================================================


def _create_token(
    subject: str,
    user_type: UserType,
    token_version: int,
    expires_delta: timedelta,
    token_type: TokenType,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "user_type": user_type,
        "token_version": token_version,
        "token_type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str, user_type: UserType, token_version: int) -> str:
    return _create_token(
        subject,
        user_type,
        token_version,
        timedelta(minutes=settings.access_token_expire_minutes),
        "access",
    )


def create_refresh_token(subject: str, user_type: UserType, token_version: int) -> str:
    return _create_token(
        subject,
        user_type,
        token_version,
        timedelta(days=settings.refresh_token_expire_days),
        "refresh",
    )


def create_token_pair(
    subject: str, user_type: UserType, token_version: int
) -> dict[str, str]:
    """一次签发双 Token，登录/注册/刷新接口统一使用。"""
    return {
        "access_token": create_access_token(subject, user_type, token_version),
        "refresh_token": create_refresh_token(subject, user_type, token_version),
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
    }


# ============================================================
# Token 校验
# ============================================================


def _to_payload(claims: dict[str, Any]) -> TokenPayload:
    """把原始 claims 转成强类型载荷。字段非法一律 401。"""
    try:
        subject_id = uuid.UUID(str(claims["sub"]))
        user_type = str(claims["user_type"])
        token_version = int(claims["token_version"])
        token_type = str(claims.get("token_type", "access"))
    except (KeyError, ValueError, TypeError) as exc:
        raise UnauthorizedError("Token 载荷不合法") from exc

    if user_type not in ("user", "admin"):
        raise UnauthorizedError("Token 载荷不合法")
    if token_type not in ("access", "refresh"):
        raise UnauthorizedError("Token 载荷不合法")

    return TokenPayload(
        subject_id=subject_id,
        user_type=user_type,  # type: ignore[arg-type]
        token_version=token_version,
        token_type=token_type,  # type: ignore[arg-type]
    )


def decode_token(token: str, expected_type: TokenType) -> TokenPayload:
    """解码并校验 Token。任何异常都转成 401，不向外泄露细节。"""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Token 无效") from exc

    if header.get("alg") not in _ALGORITHM_WHITELIST:
        # 显式拒绝 alg=none 与算法混淆攻击
        raise UnauthorizedError("Token 算法不受支持")

    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": list(_REQUIRED_CLAIMS)},
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("登录已过期") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Token 无效") from exc

    payload = _to_payload(claims)

    if payload.token_type != expected_type:
        # 防止用 Refresh Token 直接访问业务接口
        raise UnauthorizedError("Token 类型不匹配")

    return payload


def verify_token_version(payload: TokenPayload, current_version: int | None) -> None:
    """比对 Token 与账号当前的 ``token_version``。

    ``current_version`` 为 ``None`` 表示账号不存在或已注销，同样视为无效。
    不一致说明用户登出、改密、被封禁或有新设备登录，旧 Token 必须失效。
    """
    if current_version is None:
        raise UnauthorizedError("账号不存在或已注销")
    if payload.token_version != current_version:
        raise UnauthorizedError("登录状态已失效，请重新登录")
