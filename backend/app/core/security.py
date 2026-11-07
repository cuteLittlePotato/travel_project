"""JWT 签发校验与密码哈希。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import UnauthorizedError

UserType = Literal["user", "admin"]

_ALGORITHM_WHITELIST = {"HS256", "HS384", "HS512"}


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # 哈希格式非法时按校验失败处理，不向外抛出
        return False


def _create_token(
    subject: str,
    user_type: UserType,
    token_version: int,
    expires_delta: timedelta,
    token_type: Literal["access", "refresh"],
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


def decode_token(token: str, expected_type: Literal["access", "refresh"]) -> dict[str, Any]:
    """解码并校验 Token。任何异常都转成 401，不向外泄露细节。"""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Token 无效") from exc

    if header.get("alg") not in _ALGORITHM_WHITELIST:
        # 显式拒绝 alg=none 与算法混淆
        raise UnauthorizedError("Token 算法不受支持")

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "user_type", "token_version"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("登录已过期") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Token 无效") from exc

    if payload.get("token_type") != expected_type:
        raise UnauthorizedError("Token 类型不匹配")

    return payload
