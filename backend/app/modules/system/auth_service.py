"""M15 管理员认证的业务逻辑（API §14.14 ~ §14.16）。

与 C 端认证（``modules.account``）完全独立——管理员与用户是两套账号
体系（评审 §Q10），Token 的 ``user_type`` 不同，互不通用。

三个接口：
    - 登录（§14.14）：用户名 + 密码，返回 ``user_type='admin'`` 的 Token
    - 登出（§14.15）：全端登出，``token_version`` 自增
    - 改密（§14.16）：校验原密码，成功后自增 ``token_version``
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError
from app.core.security import create_token_pair, hash_password, verify_password
from app.modules.system.constants import (
    ERROR_OLD_PASSWORD_INVALID,
    ERROR_SAME_PASSWORD,
)
from app.modules.system.repository import AdminRoleRepository, AdminUserRepository

logger = logging.getLogger(__name__)


# ============================================================
# 异常
# ============================================================


class AdminLoginFailedError(BusinessError):
    """用户名或密码错误（API §14.14）。

    **不区分「用户不存在」与「密码错误」**——区分会让人可以
    枚举系统里有哪些管理员账号。统一提示，攻击者无从判断。
    """

    def __init__(self) -> None:
        super().__init__(11006, "用户名或密码错误", http_status=401)


class AdminDisabledError(BusinessError):
    """账号已禁用（API §14.14 边界：禁用后无法登录）。"""

    def __init__(self) -> None:
        super().__init__(11002, "账号已被禁用，请联系超级管理员", http_status=403)


class OldPasswordInvalidError(BusinessError):
    """原密码错误（API §14.16，25007 / HTTP 400）。"""

    def __init__(self) -> None:
        super().__init__(ERROR_OLD_PASSWORD_INVALID, "原密码不正确", http_status=400)


class SamePasswordError(BusinessError):
    """新密码与原密码相同（API §14.16，25008 / HTTP 400）。"""

    def __init__(self) -> None:
        super().__init__(ERROR_SAME_PASSWORD, "新密码不能与原密码相同", http_status=400)


# ============================================================
# 登录
# ============================================================


async def authenticate_admin(
    session: AsyncSession, *, username: str, password: str
) -> dict[str, object]:
    """校验用户名密码，返回管理员信息（不含 Token）。

    流程：
        1. 查账号——不存在时仍跑一次 bcrypt 校验（防时序侧信道）
        2. 校验密码
        3. 检查状态

    **关于时序防护**：账号不存在时直接返回会让攻击者通过响应时间
    判断用户名是否存在（存在时多一次 bcrypt 计算，明显更慢）。
    这里用一个固定的假哈希跑一次校验，让两种情况耗时接近。
    """
    repo = AdminUserRepository(session)
    admin = await repo.get_by_username(username)

    if admin is None:
        # 跑一次无意义的校验，保持耗时一致
        verify_password(password, _DUMMY_HASH)
        raise AdminLoginFailedError()

    if not verify_password(password, admin.password_hash):
        raise AdminLoginFailedError()

    if admin.status != "active":
        raise AdminDisabledError()

    return {
        "id": admin.id,
        "username": admin.username,
        "real_name": admin.real_name,
        "status": admin.status,
        "token_version": admin.token_version,
    }


async def issue_admin_tokens(
    session: AsyncSession, *, admin_id: uuid.UUID
) -> dict[str, object]:
    """为管理员签发双 Token，并记录最后登录时间。

    Token 的 ``user_type`` 固定为 ``admin``——B 端与 C 端的 Token
    互不通用（``require_admin`` 会拒绝 ``user_type='user'`` 的 Token）。
    """
    repo = AdminUserRepository(session)
    role_repo = AdminRoleRepository(session)

    admin = await repo.get_by_id(admin_id)
    if admin is None:
        raise AdminLoginFailedError()

    tokens = create_token_pair(
        subject=str(admin.id),
        user_type="admin",
        token_version=admin.token_version,
    )

    from datetime import UTC, datetime

    admin.last_login_at = datetime.now(UTC)
    await repo.flush()
    await session.commit()

    roles = await role_repo.list_roles_of(admin_id)

    return {
        **tokens,
        "admin": {
            "id": str(admin.id),
            "username": admin.username,
            "real_name": admin.real_name,
            "roles": [{"id": str(r.id), "code": r.code, "name": r.name} for r in roles],
        },
    }


# ============================================================
# 登出
# ============================================================


async def logout_admin(session: AsyncSession, *, admin_id: uuid.UUID) -> None:
    """全端登出（API §14.15）。

    自增 ``token_version`` 让该管理员**所有设备**上已签发的 Token
    立即失效。这是「全端登出」而非「单端登出」的取舍（评审 §Q2
    对 C 端也是同样策略）。

    Refresh Token 的黑名单在 ``token_service``，这里只处理版本号——
    版本号一变，所有 Refresh 也都换不出新的 Access。
    """
    repo = AdminUserRepository(session)
    await repo.increment_token_version(admin_id)
    await session.commit()
    logger.info("管理员登出 id=%s（全端）", admin_id)


# ============================================================
# 修改自己的密码
# ============================================================


async def change_own_password(
    session: AsyncSession,
    *,
    admin_id: uuid.UUID,
    old_password: str,
    new_password: str,
) -> None:
    """修改自己的密码（API §14.16）。

    与「超管重置他人密码」（``service.reset_password``）的区别：
    本接口**必须校验原密码**——修改自己的凭据要证明自己是本人。

    成功后自增 ``token_version``：改密码就应假设旧凭据可能已泄露，
    所有设备需重新登录。
    """
    repo = AdminUserRepository(session)

    admin = await repo.get_by_id(admin_id)
    if admin is None:
        # 正常不会发生（已通过 require_admin），防御性处理
        raise AdminLoginFailedError()

    if not verify_password(old_password, admin.password_hash):
        raise OldPasswordInvalidError()

    if verify_password(new_password, admin.password_hash):
        raise SamePasswordError()

    admin.password_hash = hash_password(new_password)
    await repo.increment_token_version(admin_id)
    await repo.flush()
    await session.commit()

    logger.info("管理员修改自己的密码 id=%s", admin_id)


#: 用于时序防护的假哈希。
#: 内容无关紧要，只要是一个合法的 bcrypt 串，让校验过程真正跑起来。
_DUMMY_HASH = "$2b$12$" + "x" * 53


__all__ = [
    "AdminDisabledError",
    "AdminLoginFailedError",
    "OldPasswordInvalidError",
    "SamePasswordError",
    "authenticate_admin",
    "change_own_password",
    "issue_admin_tokens",
    "logout_admin",
]


# ============================================================
# 刷新 Token（B 端独立实现）
# ============================================================


class AdminRefreshRevokedError(BusinessError):
    """Refresh Token 无效或已使用（轮换机制）。"""

    def __init__(self, message: str = "刷新令牌无效，请重新登录") -> None:
        super().__init__(11010, message, http_status=401)


async def refresh_admin_tokens(
    session: AsyncSession, *, refresh_token: str
) -> dict[str, object]:
    """刷新 B 端双 Token。

    **为什么不复用 C 端的 ``token_service.refresh_tokens``**：
    它内部查的是 ``user`` 表、判的是 C 端状态枚举（banned/deleted），
    B 端是 ``admin_user`` 与 active/disabled。硬塞一个 user_type 参数
    会让那个函数变成两个模块的混合体，改一边容易碰坏另一边。

    但**轮换机制复用同一套 Redis jti 黑名单**——这部分与账号体系无关，
    键的设计与 C 端一致（``verify:revoked:{jti}`` 前缀不同而已）。

    流程：
        1. 解析 Refresh Token
        2. 原子占用 jti（防重放）
        3. 查管理员，校验状态
        4. 校验 token_version（登出/改密后旧 Refresh 也失效）
        5. 签发新双 Token
    """
    import time

    from app.core.security import decode_token, verify_token_version
    from app.modules.account.token_service import _consume_jti, _decode_claims

    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except BusinessError:
        raise AdminRefreshRevokedError() from None

    if payload.user_type != "admin":
        raise AdminRefreshRevokedError()

    claims = _decode_claims(refresh_token)
    jti = claims.get("jti")
    if not jti:
        raise AdminRefreshRevokedError()

    exp = int(claims.get("exp", 0))
    remaining = max(exp - int(time.time()), 1)

    if not await _consume_jti(jti, remaining):
        logger.warning("B 端 Refresh Token 重放 admin_id=%s", payload.subject_id)
        raise AdminRefreshRevokedError()

    repo = AdminUserRepository(session)
    admin = await repo.get_by_id(payload.subject_id)
    if admin is None:
        raise AdminRefreshRevokedError()
    if admin.status != "active":
        raise AdminDisabledError()

    try:
        verify_token_version(payload, admin.token_version)
    except BusinessError as exc:
        raise AdminRefreshRevokedError() from exc

    tokens = create_token_pair(
        subject=str(admin.id),
        user_type="admin",
        token_version=admin.token_version,
    )
    tokens["user_type"] = "admin"

    roles = await AdminRoleRepository(session).list_roles_of(admin.id)
    tokens["admin"] = {
        "id": str(admin.id),
        "username": admin.username,
        "real_name": admin.real_name,
        "roles": [{"id": str(r.id), "code": r.code, "name": r.name} for r in roles],
    }

    return tokens
