"""M01 用户与账户的业务逻辑。

**事务边界（M0-T02 确认）**：本层负责 ``commit``。
一次业务操作内的多次写入要么全成功、要么全回滚——
例如注册时要同时建 user + oauth_binding + user_profile + user_setting，
任何一步失败都不能留下半个账号。
"""

from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.core.security import create_token_pair, hash_password, verify_password
from app.infra import redis as redis_infra
from app.modules.account.constants import (
    LOGIN_FAIL_LIMIT,
    LOGIN_LOCK_SECONDS,
    BindingProvider,
    UserStatus,
    VerifyScene,
    Visibility,
)
from app.modules.account.models import OAuthBinding, User, UserProfile, UserSetting
from app.modules.account.repository import AccountRepository
from app.modules.account.verification import (
    InvalidVerifyCodeError,
    detect_target_type,
    verify_code,
)
from app.utils.ids import uuid7

logger = logging.getLogger(__name__)


# ============================================================
# 异常
# ============================================================


class PasswordNotSetError(BusinessError):
    """账号存在但从未设置密码（API §3.3）。

    验证码注册与第三方登录创建的账号 ``credential`` 为空，
    用密码登录必然失败。此时提示「请用验证码登录或先设置密码」
    比笼统的「密码错误」更有用。
    """

    def __init__(self) -> None:
        super().__init__(
            ErrorCode.PASSWORD_NOT_SET,
            "该账号尚未设置密码，请使用验证码登录，或登录后在个人中心设置密码",
            http_status=401,
        )


class DuplicateTargetError(BusinessError):
    """手机号/邮箱已被注册。HTTP 409 + 11003。"""

    def __init__(self, message: str = "该手机号或邮箱已被注册") -> None:
        super().__init__(ErrorCode.DUPLICATE_TARGET, message, http_status=409)


class AccountNotFoundError(BusinessError):
    def __init__(self, message: str = "账号不存在") -> None:
        super().__init__(ErrorCode.ACCOUNT_NOT_FOUND, message, http_status=404)


class AccountBannedError(BusinessError):
    def __init__(self, message: str = "该账号已被封禁") -> None:
        super().__init__(ErrorCode.ACCOUNT_BANNED, message, http_status=403)


class AccountDeletedError(BusinessError):
    def __init__(self, message: str = "该账号已注销") -> None:
        super().__init__(ErrorCode.ACCOUNT_DELETED, message, http_status=403)


# ============================================================
# 结果对象
# ============================================================


@dataclass(frozen=True, slots=True)
class AuthResult:
    """注册/登录成功的结果。"""

    user_id: uuid.UUID
    access_token: str
    refresh_token: str
    expires_in: int


# ============================================================
# 工具
# ============================================================


def generate_default_nickname(target: str) -> str:
    """按 target 生成默认昵称。

    需求 §2.1.1：昵称默认取 target 前缀。为避免撞名，追加 4 位十六进制后缀。
    """
    if "@" in target:
        base = target.split("@", 1)[0][:20]
        return f"{base}_{secrets.token_hex(2)}"
    # 手机号：138****8888 形式，保留可识别性
    masked = f"{target[:3]}***{target[-4:]}" if len(target) >= 11 else target
    return masked


def generate_unique_username(target: str) -> str:
    """生成唯一的 ``user.username``。

    ``username`` 是用户表上的唯一索引，必须保证不冲突。
    做法：以 target 的 hash 前缀 + 随机后缀，避免暴露手机号/邮箱。
    """
    import hashlib

    digest = hashlib.sha256(target.encode()).hexdigest()[:12]
    return f"u_{digest}_{secrets.token_hex(2)}"


# ============================================================
# 注册
# ============================================================


async def register(
    session: AsyncSession,
    *,
    target: str,
    verify_code_str: str,
    nickname: str | None = None,
) -> AuthResult:
    """用户注册（API §3.2）。

    流程：
        1. 识别 target 类型并校验格式
        2. 检查 target 是否已注册（快速失败，避免白耗验证码）
        3. 校验验证码（成功即删除，一次性使用）
        4. 事务内创建 user + oauth_binding + user_profile + user_setting
        5. 签发双 Token

    边界：验证码在步骤 3 被消费。若步骤 4 失败（如唯一约束冲突），
    验证码已失效，用户需重新获取——这是刻意的，避免验证码被反复利用。
    """
    repo = AccountRepository(session)
    provider = detect_target_type(target)

    # ---------- 1. 快速查重 ----------
    if await repo.bindings.exists_by_provider(provider, target):
        raise DuplicateTargetError()

    # ---------- 2. 校验验证码 ----------
    await verify_code(VerifyScene.REGISTER, target, verify_code_str)

    # ---------- 3. 事务内创建 ----------
    user = User(
        id=uuid7(),
        username=generate_unique_username(target),
        nickname=nickname or generate_default_nickname(target),
        status=UserStatus.ACTIVE.value,
        token_version=0,
    )
    repo.users.add(user)

    # 手机号与邮箱都支持密码登录，故 credential 写入 bcrypt 哈希。
    # 第三方 OAuth 的 credential 存 access_token，由 M01-T07 处理。
    repo.bindings.add(
        OAuthBinding(
            id=uuid7(),
            user_id=user.id,
            provider=provider.value,
            provider_uid=target,
            # 注册不设密码（需求 2.1.1）：credential 留空，
            # 用户之后可在个人中心设置（change_password 支持首次设置）
            credential=None,
            is_primary=True,
        )
    )

    repo.profiles.add(_default_profile(user.id))
    repo.settings.add(_default_setting(user.id))

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # 唯一约束冲突：并发注册同一 target
        # （查重与插入之间有时间窗，靠数据库唯一索引兜底）
        logger.warning("注册唯一约束冲突 target=%s: %s", provider.value, exc)
        raise DuplicateTargetError() from exc
    except Exception:
        await session.rollback()
        raise

    # ---------- 4. 签发 Token ----------
    tokens = create_token_pair(str(user.id), "user", user.token_version)
    logger.info("用户注册成功 user_id=%s provider=%s", user.id, provider.value)

    return AuthResult(
        user_id=user.id,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens["expires_in"],
    )


def _default_profile(user_id: uuid.UUID):
    from app.modules.account.models import UserProfile

    return UserProfile(id=uuid7(), user_id=user_id)


def _default_setting(user_id: uuid.UUID):
    from app.modules.account.models import UserSetting

    return UserSetting(id=uuid7(), user_id=user_id)


# ============================================================
# 密码登录
# ============================================================


class InvalidCredentialError(BusinessError):
    """账号不存在或密码错误。

    **安全约定（2026-11-08 确认）**：``message`` 与 HTTP 状态码对这两种情况
    完全一致，只有 ``code`` 不同（11005 / 11006）。
    这样前端可区分场景做埋点，而攻击者无法通过响应枚举已注册的手机号。
    """

    def __init__(self, code: int = ErrorCode.INVALID_CREDENTIAL) -> None:
        super().__init__(code, "账号或密码错误", http_status=401)


class AccountLockedError(BusinessError):
    """密码错误次数过多，账号临时锁定。HTTP 429 + 11008。"""

    def __init__(self, remaining_seconds: int) -> None:
        super().__init__(
            ErrorCode.TOO_MANY_LOGIN_ATTEMPTS,
            f"密码错误次数过多，请 {remaining_seconds // 60 + 1} 分钟后再试",
            data={"retry_after": remaining_seconds},
            http_status=429,
        )


def _login_fail_key(target: str) -> str:
    return redis_infra.make_key("login", "fail", target)


async def _check_lock(target: str) -> None:
    """检查是否处于锁定期。"""
    client = redis_infra.get_client()
    attempts_raw = await client.get(_login_fail_key(target))
    attempts = int(attempts_raw) if attempts_raw else 0

    if attempts >= LOGIN_FAIL_LIMIT:
        ttl = await client.ttl(_login_fail_key(target))
        raise AccountLockedError(max(ttl, 1))


async def _record_failure(target: str) -> None:
    """记录一次密码错误。达到阈值后 key 保留至锁定结束。"""
    client = redis_infra.get_client()
    key = _login_fail_key(target)
    attempts = await client.incr(key)

    if attempts == 1:
        # 首次失败即设置锁定窗口；未达阈值时这只是保持计数的 TTL
        await client.expire(key, LOGIN_LOCK_SECONDS)
    elif attempts >= LOGIN_FAIL_LIMIT:
        # 达到阈值，重置 TTL 为完整锁定窗口（从最后一次失败算起）
        await client.expire(key, LOGIN_LOCK_SECONDS)

    logger.info("登录失败 target=%s attempts=%s", _mask_target(target), attempts)


async def _clear_failures(target: str) -> None:
    """登录成功后清空失败计数。"""
    await redis_infra.get_client().delete(_login_fail_key(target))


def _mask_target(target: str) -> str:
    """日志中脱敏 target，避免手机号/邮箱明文进日志。"""
    if "@" in target:
        local, _, domain = target.partition("@")
        return f"{local[:2]}***@{domain}"
    if len(target) >= 11:
        return f"{target[:3]}****{target[-4:]}"
    return target[:2] + "***"


async def _find_binding_account(
    session: AsyncSession, target: str
) -> tuple[User, OAuthBinding] | None:
    """按 target 找账号与绑定。

    支持三种登录标识：手机号、邮箱、用户名。
    前两者查 ``oauth_binding``，用户名查 ``user.username``。

    用户名登录时返回该用户的**主绑定**（``is_primary=True``），
    以便后续统一从 binding 取 credential。
    """
    repo = AccountRepository(session)

    # 先按手机号/邮箱查
    for provider in (BindingProvider.PHONE, BindingProvider.EMAIL):
        binding = await repo.bindings.get_by_provider(provider, target)
        if binding is not None:
            user = await repo.users.get_by_id(binding.user_id)
            if user is not None:
                return user, binding

    # 再按用户名查
    user = await repo.users.get_by_username(target)
    if user is None:
        return None

    bindings = await repo.bindings.list_by_user(user.id)
    if not bindings:
        return None

    primary = next((b for b in bindings if b.is_primary), bindings[0])
    return user, primary


async def authenticate(
    session: AsyncSession, *, target: str, password: str
) -> AuthResult:
    """密码登录（API §3.3）。

    流程：
        1. 检查是否处于锁定期（锁定期内不查库，直接拒绝）
        2. 按 target 查账号
        3. 校验账号状态（封禁 / 注销）
        4. 校验密码
        5. 成功则清空失败计数、更新 last_login_at、签发双 Token

    安全：
        - 「账号不存在」与「密码错误」返回相同的 message 与 HTTP 401，
          只有业务码不同（11005 / 11006），避免账号枚举
        - 连续 5 次失败锁定 15 分钟（Redis 计数，按 target）
    """
    # ---------- 1. 锁定检查 ----------
    await _check_lock(target)

    # ---------- 2. 查账号 ----------
    found = await _find_binding_account(session, target)
    if found is None:
        # 记录失败但返回 11005 语义的通用提示，避免暴露「账号不存在」
        await _record_failure(target)
        raise InvalidCredentialError(ErrorCode.ACCOUNT_NOT_FOUND)

    user, binding = found

    # ---------- 3. 账号状态 ----------
    if user.status == UserStatus.BANNED:
        raise AccountBannedError()
    if user.status == UserStatus.DELETED:
        raise AccountDeletedError()

    # ---------- 4. 校验密码 ----------
    # 未设置密码的账号（验证码自动注册、第三方登录创建的）单独报错，
    # 否则用户会一直以为是自己密码输错了——而他从来没有设置过密码。
    #
    # 关于账号枚举：注册接口已经通过 ``11003 该账号已注册`` 暴露了
    # 账号是否存在，登录接口再隐藏这一点已无意义。这里选择给出
    # 可执行的指引，而不是让用户对着「密码错误」干瞪眼。
    if not binding.credential:
        await _record_failure(target)
        raise PasswordNotSetError()

    if not verify_password(password, binding.credential):
        await _record_failure(target)
        raise InvalidCredentialError(ErrorCode.INVALID_CREDENTIAL)

    # ---------- 5. 成功 ----------
    await _clear_failures(target)

    from datetime import UTC, datetime

    user.last_login_at = datetime.now(UTC)
    await session.commit()

    tokens = create_token_pair(str(user.id), "user", user.token_version)
    logger.info("用户登录成功 user_id=%s", user.id)

    return AuthResult(
        user_id=user.id,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens["expires_in"],
    )


async def get_login_fail_count(target: str) -> int:
    """当前失败次数，供测试与运维查询。"""
    raw = await redis_infra.get_client().get(_login_fail_key(target))
    return int(raw) if raw else 0




# ============================================================
# 验证码登录（自动注册）
# ============================================================


@dataclass(frozen=True, slots=True)
class CodeLoginResult:
    """验证码登录结果。

    ``is_new_user`` 标识本次是否为自动创建，前端据此展示引导。
    """

    user_id: uuid.UUID
    access_token: str
    refresh_token: str
    expires_in: int
    is_new_user: bool


async def _release_binding_identifier(
    session: AsyncSession, *, user_id: uuid.UUID
) -> None:
    """把账号的登录标识改写为匿名值，释放原邮箱/手机号。

    注销与「注销后重新注册」共用这段逻辑——两处的语义完全一致，
    分开写迟早会漂移。

    改写后的格式：``deleted_{时间戳}_{provider}_{随机8位}``。
    保留「曾经绑定过某个标识」的记录形态（审计与统计需要计数），
    同时释放原标识供新账号使用。
    """
    from datetime import UTC, datetime

    from sqlalchemy import text

    released_at = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    await session.execute(
        text(
            """
            UPDATE oauth_binding
            SET provider_uid = 'deleted_' || :ts || '_' || provider || '_'
                               || substr(md5(random()::text), 1, 8),
                credential = NULL
            WHERE user_id = :uid
            """
        ),
        {"ts": released_at, "uid": user_id},
    )
    await session.commit()


async def login_or_register_by_code(
    session: AsyncSession, *, target: str, verify_code_str: str
) -> CodeLoginResult:
    """验证码登录，账号不存在时自动注册（API §3.4）。

    流程：
        1. 识别 target 类型并校验格式
        2. 校验验证码（成功即删除，一次性使用）
        3. 查账号：存在则登录，不存在则自动注册
        4. 状态检查（封禁 / 注销）
        5. 签发双 Token

    自动注册的账号 ``credential = NULL``（无密码），
    用户可通过「修改密码」接口设置。

    与 ``register()`` 的区别：
        - 不要求密码
        - 昵称按 API §3.4 的规则生成
        - 响应多一个 ``is_new_user``
    """
    from app.utils.nickname import MAX_RETRY, generate_auto_nickname

    repo = AccountRepository(session)
    provider = detect_target_type(target)

    # ---------- 1. 校验验证码 ----------
    await verify_code(VerifyScene.LOGIN, target, verify_code_str)

    # ---------- 2. 查账号 ----------
    binding = await repo.bindings.get_by_provider(provider, target)
    is_new_user = False

    user = None
    if binding is not None:
        user = await repo.users.get_by_id(binding.user_id)
        if user is None:
            # 绑定存在但用户不存在：数据不一致，按不存在处理
            raise AccountNotFoundError()

        # **已注销账号：释放标识并重新注册**（2026-11-09 规则）。
        # 按钮写的是「登录 / 注册」，用户点它就该得到其中一个结果。
        # 销毁的账号既登不进去、又被唯一约束挡着注册不了，是死路。
        #
        # 释放旧标识 → 走自动注册 → 得到全新账号。旧账号的匿名化
        # 记录保持不动，两者互相独立。
        if user.status == UserStatus.DELETED:
            logger.info(
                "验证码登录遇到已注销账号，重新注册 target=%s", target
            )
            await _release_binding_identifier(session, user_id=user.id)
            binding = None
            user = None

    if user is None:
        # ---------- 3. 自动注册 ----------
        user, binding = await _auto_register(
            repo, provider, target, MAX_RETRY, generate_auto_nickname
        )
        is_new_user = True

    # ---------- 4. 状态检查 ----------
    if user.status == UserStatus.BANNED:
        raise AccountBannedError()

    # ---------- 5. 提交并签发 ----------
    from datetime import UTC, datetime

    user.last_login_at = datetime.now(UTC)
    try:
        await session.commit()
    except IntegrityError as exc:
        # 并发场景：另一个请求刚创建了同一 target
        await session.rollback()
        logger.warning("验证码登录并发冲突 target=%s", provider.value)
        raise DuplicateTargetError("请重试") from exc

    tokens = create_token_pair(str(user.id), "user", user.token_version,
                               )
    logger.info(
        "验证码登录成功 user_id=%s is_new_user=%s", user.id, is_new_user
    )

    return CodeLoginResult(
        user_id=user.id,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens["expires_in"],
        is_new_user=is_new_user,
    )


async def _auto_register(
    repo: AccountRepository,
    provider: BindingProvider,
    target: str,
    max_retry: int,
    generate_nickname,
) -> tuple[User, OAuthBinding]:
    """自动注册账号。昵称冲突时重试。"""
    # 昵称重试：user.nickname 没有唯一约束，理论上不会冲突，
    # 但 API 文档要求「冲突时重试」，这里按 username 的唯一性做真实检查
    nickname = generate_nickname(target)
    for attempt in range(max_retry + 1):
        candidate = generate_nickname(target, attempt=attempt)
        # nickname 无唯一约束，用 username 保证唯一即可
        # 但仍按文档要求检查昵称重复，避免大量同名
        exists = await _nickname_exists(repo.session, candidate)
        if not exists:
            nickname = candidate
            break
    else:
        # 全部重试仍冲突，直接用带序号的版本（必不冲突概率极高）
        nickname = generate_nickname(target, attempt=max_retry + 1)

    user = User(
        id=uuid7(),
        username=generate_unique_username(target),
        nickname=nickname,
        status=UserStatus.ACTIVE.value,
        token_version=0,
    )
    repo.users.add(user)

    binding = OAuthBinding(
        id=uuid7(),
        user_id=user.id,
        provider=provider.value,
        provider_uid=target,
        credential=None,  # 自动注册的账号无密码
        is_primary=True,
    )
    repo.bindings.add(binding)

    repo.profiles.add(_default_profile(user.id))
    repo.settings.add(_default_setting(user.id))

    await repo.session.flush()
    return user, binding


async def _nickname_exists(session: AsyncSession, nickname: str) -> bool:
    """检查昵称是否已被占用。

    ``user.nickname`` 没有唯一约束，这里只做「减少同名」的软检查，
    不作为正确性保证。
    """
    from sqlalchemy import func, select

    result = await session.execute(
        select(func.count()).select_from(User).where(User.nickname == nickname)
    )
    return result.scalar_one() > 0




# ============================================================
# 第三方登录
# ============================================================


async def login_by_oauth(
    session: AsyncSession, *, provider: str, code: str
) -> CodeLoginResult:
    """第三方登录（API §3.5）。

    流程：
        1. 用授权码向第三方换取用户信息（openid）
        2. 查绑定：存在则登录，不存在则自动创建账号并绑定
        3. 状态检查
        4. 签发双 Token

    **关于 state 的说明（2026-11-08 确认）**：后端不校验 state。
    state 由前端生成与比对（跳转前存 localStorage，回调后比对），
    后端只接收回调结果。这样后端保持无状态，也无需新增「获取授权 URL」接口。

    **关于 11009「同一第三方账号绑定多个平台账号」**：该场景被
    唯一索引 ``uk_oauth_provider_uid (provider, provider_uid)`` 禁止，无法发生。
    错误码保留定义，代码中不需处理。
    """
    from app.infra.oauth import get_provider

    oauth = get_provider(provider)
    user_info = await oauth.exchange_code(code)

    repo = AccountRepository(session)
    provider_enum = oauth.provider

    binding = await repo.bindings.get_by_provider(provider_enum, user_info.provider_uid)
    is_new_user = False

    if binding is not None:
        user = await repo.users.get_by_id(binding.user_id)
        if user is None:
            # 绑定存在但用户已删除：数据不一致，清理后重新创建
            await session.delete(binding)
            binding = None
        else:
            # 顺带更新第三方侧变更的昵称/头像（不覆盖用户自己改过的）
            if user_info.avatar_url and not user.avatar_url:
                user.avatar_url = user_info.avatar_url

    if binding is None:
        user, binding = await _auto_register_oauth(
            repo, provider_enum, user_info
        )
        is_new_user = True

    if user.status == UserStatus.BANNED:
        raise AccountBannedError()
    if user.status == UserStatus.DELETED:
        raise AccountDeletedError()

    from datetime import UTC, datetime

    user.last_login_at = datetime.now(UTC)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        logger.warning("第三方登录并发冲突 provider=%s", provider_enum.value)
        raise DuplicateTargetError("请重试") from exc

    tokens = create_token_pair(str(user.id), "user", user.token_version)
    logger.info(
        "第三方登录成功 user_id=%s provider=%s is_new_user=%s",
        user.id,
        provider_enum.value,
        is_new_user,
    )

    return CodeLoginResult(
        user_id=user.id,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens["expires_in"],
        is_new_user=is_new_user,
    )


async def _auto_register_oauth(
    repo: AccountRepository, provider: BindingProvider, user_info
) -> tuple[User, OAuthBinding]:
    """第三方首次登录的自动建号。

    昵称优先用第三方昵称；没有则用「服务商名 + 随机后缀」。
    """
    nickname = _oauth_nickname(provider, user_info)

    user = User(
        id=uuid7(),
        username=generate_unique_username(f"{provider.value}:{user_info.provider_uid}"),
        nickname=nickname,
        avatar_url=user_info.avatar_url,
        status=UserStatus.ACTIVE.value,
        token_version=0,
    )
    repo.users.add(user)

    binding = OAuthBinding(
        id=uuid7(),
        user_id=user.id,
        provider=provider.value,
        provider_uid=user_info.provider_uid,
        # 第三方登录的 credential 存 access_token（用于后续调第三方 API），
        # 不是密码哈希。密码登录时会因无法比对 bcrypt 而失败，符合预期。
        credential=None,
        extra_data={"union_id": user_info.union_id} if user_info.union_id else None,
        is_primary=True,
    )
    repo.bindings.add(binding)

    repo.profiles.add(_default_profile(user.id))
    repo.settings.add(_default_setting(user.id))

    await repo.session.flush()
    return user, binding


def _oauth_nickname(provider: BindingProvider, user_info) -> str:
    """第三方账号的默认昵称。

    优先用第三方昵称（需清理与截断），否则用「服务商名_随机后缀」。
    """
    raw = user_info.nickname
    if raw:
        cleaned = "".join(ch for ch in raw.strip() if ch.isprintable())[:40]
        if cleaned:
            return cleaned

    display = {
        BindingProvider.WECHAT: "微信用户",
        BindingProvider.ALIPAY: "支付宝用户",
        BindingProvider.WEIBO: "微博用户",
    }.get(provider, "用户")
    return f"{display}_{secrets.token_hex(2)}"


# ============================================================
# 登出（全端登出）
# ============================================================


async def invalidate_all_tokens(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    """使该用户所有已签发的 Token 失效（API §3.7）。

    实现：``user.token_version`` 原子自增。所有 Token 的载荷里都带着签发时的
    ``token_version``，校验时与数据库比对，不一致即拒绝。

    为什么用版本号而不是黑名单：
        - 无需为每个 Token 存一条记录，不新增表
        - 无需定期清理过期记录
        - 校验开销是一次主键查询（M0-T05 已确认每次请求都查）

    **注意**：这是**全端登出**——用户在多设备登录时，任一端登出会导致所有端退出。
    这是评审 §17.4 的决策，若后续需要单端登出，需新增 Refresh Token 存储表。

    :return: 自增后的 token_version
    :raises AccountNotFoundError: 用户不存在
    """
    repo = AccountRepository(session)
    new_version = await repo.users.increment_token_version(user_id)
    if new_version is None:
        raise AccountNotFoundError()

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    logger.info("用户登出（全端）user_id=%s new_token_version=%s", user_id, new_version)
    return new_version




# ============================================================
# 用户资料
# ============================================================


def mask_provider_uid(provider: str, uid: str) -> str:
    """脱敏第三方/登录标识（DoD 要求）。

    - 手机号：``13800138000`` -> ``138****8000``
    - 邮箱：``user@example.com`` -> ``us***@example.com``
    - 第三方 openid：保留前 4 位 + ``***`` + 后 4 位

    注意：手机号脱敏是**中间四位**（API §3.8 的示例是 ``138****8888``），
    即保留前 3 位与后 4 位。
    """
    if provider == BindingProvider.PHONE.value:
        if len(uid) >= 11:
            return f"{uid[:3]}****{uid[-4:]}"
        return "***"

    if provider == BindingProvider.EMAIL.value:
        local, _, domain = uid.partition("@")
        if not domain:
            return "***"
        keep = min(2, len(local))
        return f"{local[:keep]}***@{domain}"

    # 第三方 openid / uid
    if len(uid) > 8:
        return f"{uid[:4]}***{uid[-4:]}"
    return "***"


async def get_me(session: AsyncSession, *, user_id: uuid.UUID) -> dict:
    """查询当前用户资料（API §3.8）。

    返回 ``user`` 字段 + 脱敏后的 ``bindings`` 列表。
    **不含** ``credential``、``token_version``。

    抛错：
        ``AccountNotFoundError``  用户不存在
        ``AccountDeletedError``   已注销（不应再展示资料）
    """
    repo = AccountRepository(session)
    user = await repo.users.get_by_id(user_id)
    if user is None:
        raise AccountNotFoundError()
    if user.status == UserStatus.DELETED:
        raise AccountDeletedError()

    bindings = await repo.bindings.list_by_user(user_id)

    # 把编码解析成名称——前端不该自己维护这张映射表
    region = (
        await repo.resolve_region(user.region_code) if user.region_code else None
    )

    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "avatar_url": user.avatar_url,
        "gender": user.gender,
        "region_code": user.region_code,
        "region": region,
        "status": user.status,
        "created_at": user.created_at,
        "bindings": [
            {
                "provider": b.provider,
                "provider_uid": mask_provider_uid(b.provider, b.provider_uid),
                "is_primary": b.is_primary,
            }
            for b in bindings
        ],
    }


async def update_me(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    nickname: str | None = None,
    avatar_url: str | None = None,
    gender: str | None = None,
    region_code: str | None = None,
    fields_set: set[str] | None = None,
) -> dict:
    """更新当前用户资料（API §3.9）。

    **部分更新语义**：只更新 ``fields_set`` 中出现的字段。
    这样能区分「未传」与「传了 null」——后者表示要清空该字段。

    :param fields_set: 请求体中实际出现的字段名集合。
        为 None 时按「非 None 即更新」处理（兼容简单调用）
    """
    repo = AccountRepository(session)
    user = await repo.users.get_by_id(user_id)
    if user is None:
        raise AccountNotFoundError()
    if user.status == UserStatus.BANNED:
        raise AccountBannedError()
    if user.status == UserStatus.DELETED:
        raise AccountDeletedError()

    updates: dict[str, object] = {
        "nickname": nickname,
        "avatar_url": avatar_url,
        "gender": gender,
        "region_code": region_code,
    }

    to_apply: dict[str, object] = {}
    for key, value in updates.items():
        if fields_set is not None:
            if key in fields_set:
                to_apply[key] = value
        elif value is not None:
            to_apply[key] = value

    if to_apply:
        # nickname 不允许置空（数据库 NOT NULL）
        if "nickname" in to_apply and not to_apply["nickname"]:
            to_apply.pop("nickname")

        for key, value in to_apply.items():
            setattr(user, key, value)

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    await session.refresh(user)
    logger.info("用户资料更新 user_id=%s fields=%s", user_id, sorted(to_apply))
    return await get_me(session, user_id=user_id)




# ============================================================
# 修改密码
# ============================================================


class SamePasswordError(BusinessError):
    """新密码与原密码相同。HTTP 400 + 11011。"""

    def __init__(self) -> None:
        super().__init__(
            ErrorCode.SAME_PASSWORD, "新密码不能与原密码相同", http_status=400
        )


class InvalidOldPasswordError(BusinessError):
    """原密码错误。HTTP 400 + 11006。"""

    def __init__(self) -> None:
        super().__init__(ErrorCode.INVALID_CREDENTIAL, "原密码错误", http_status=400)


async def change_password(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    old_password: str | None,
    new_password: str,
) -> int:
    """修改密码（API §3.10）。

    **首次设置密码的例外（2026-11-08 确认）**：
    自动注册/第三方登录创建的账号 ``credential`` 为空，
    此时 ``old_password`` 可为空，直接设置新密码。
    已设置过密码的账号必须校验原密码。

    成功后 ``token_version`` 自增，使所有已签发的 Token 失效（需重新登录）。

    :return: 自增后的 token_version
    :raises InvalidOldPasswordError: 原密码错误（已有密码时）
    :raises SamePasswordError: 新旧密码相同
    """
    repo = AccountRepository(session)
    user = await repo.users.get_by_id(user_id)
    if user is None:
        raise AccountNotFoundError()
    if user.status == UserStatus.BANNED:
        raise AccountBannedError()
    if user.status == UserStatus.DELETED:
        raise AccountDeletedError()

    # 找到承载密码的绑定（phone/email 的主绑定）
    bindings = await repo.bindings.list_by_user(user_id)
    if not bindings:
        raise AccountNotFoundError("账号缺少登录方式")

    primary = next((b for b in bindings if b.is_primary), bindings[0])

    has_password = bool(primary.credential)

    if has_password:
        # 已有密码：必须校验原密码
        if not old_password:
            raise InvalidOldPasswordError()
        if not verify_password(old_password, primary.credential):
            raise InvalidOldPasswordError()
        # 新旧相同检查（只有能校验时才做）
        if verify_password(new_password, primary.credential):
            raise SamePasswordError()
    # 无密码账号：跳过原密码校验，直接设置

    primary.credential = hash_password(new_password)

    # 密码变更使所有 Token 失效
    new_version = await repo.users.increment_token_version(user_id)
    if new_version is None:
        raise AccountNotFoundError()

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    logger.info(
        "密码修改成功 user_id=%s first_time=%s", user_id, not has_password
    )
    return new_version




# ============================================================
# 旅游偏好
# ============================================================


async def get_profile(session: AsyncSession, *, user_id: uuid.UUID) -> dict:
    """查询旅游偏好（API §3.11）。

    记录不存在时返回空默认值，而不是 404——用户刚注册时
    ``user_profile`` 已由注册流程创建，但若数据缺失也不应报错。
    """
    repo = AccountRepository(session)
    profile = await repo.profiles.get_by_user_id(user_id)
    if profile is None:
        return {
            "travel_types": [],
            "travel_styles": [],
            "budget_level": None,
            "companion_type": None,
            "preferred_seasons": [],
            "departure_city_code": None,
            "departure_city_info": None,
        }

    # 编码 → 名称。**与 user.region_code 同一套处理**：
    # 前端不该自己维护「编码→名称」的映射表。
    departure_city = (
        await repo.resolve_region(profile.departure_city_code)
        if profile.departure_city_code
        else None
    )

    return {
        "travel_types": profile.travel_types or [],
        "travel_styles": profile.travel_styles or [],
        "budget_level": profile.budget_level,
        "companion_type": profile.companion_type,
        "preferred_seasons": profile.preferred_seasons or [],
        "departure_city_code": profile.departure_city_code,
        #: 城市信息（code + name），编码在地区表中不存在时为 null。
        #: 命名带 ``_info`` 后缀，避免与 ``departure_city_code`` 混淆。
        "departure_city_info": departure_city,
    }


async def update_profile(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    travel_types: list[str] | None = None,
    travel_styles: list[str] | None = None,
    budget_level: str | None = None,
    companion_type: str | None = None,
    preferred_seasons: list[str] | None = None,
    departure_city_code: str | None = None,
    fields_set: set[str] | None = None,
) -> dict:
    """更新旅游偏好（API §3.12）。

    **整体替换语义**（API 明确要求）：请求体中**未出现的字段会被重置为 null**。
    这与 ``PATCH /users/me`` 的部分更新语义相反，是刻意的——

    原因：偏好是一组结构化选择，前端以「表单整体提交」的方式使用。
    若某次用户清空了「旅游类型」，不重置就永远删不掉。

    ``fields_set`` 为 None 时（直接调用），按「全部字段参与替换」处理。
    """
    repo = AccountRepository(session)
    profile = await repo.profiles.get_by_user_id(user_id)
    if profile is None:
        profile = repo.profiles.add(UserProfile(id=uuid7(), user_id=user_id))

    # 整体替换：未传的字段一律置为 None
    source: dict[str, object] = {
        "travel_types": travel_types,
        "travel_styles": travel_styles,
        "budget_level": budget_level,
        "companion_type": companion_type,
        "preferred_seasons": preferred_seasons,
        "departure_city_code": departure_city_code,
    }

    for key, value in source.items():
        if fields_set is not None and key not in fields_set:
            # 未出现在请求体中 → 整体替换语义下置空
            setattr(profile, key, None)
        else:
            setattr(profile, key, value)

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    logger.info("旅游偏好更新 user_id=%s", user_id)
    return await get_profile(session, user_id=user_id)




# ============================================================
# 隐私与通知设置
# ============================================================


async def get_settings(session: AsyncSession, *, user_id: uuid.UUID) -> dict:
    """查询隐私与通知设置（API §3.13）。

    记录不存在时返回默认值（全部 public / 允许推荐与通知）。
    """
    repo = AccountRepository(session)
    setting = await repo.settings.get_by_user_id(user_id)
    if setting is None:
        return {
            "profile_visibility": Visibility.PUBLIC.value,
            "footprint_visibility": Visibility.PUBLIC.value,
            "plan_visibility": Visibility.PUBLIC.value,
            "allow_recommendation": True,
            "allow_notification": True,
        }

    return {
        "profile_visibility": setting.profile_visibility,
        "footprint_visibility": setting.footprint_visibility,
        "plan_visibility": setting.plan_visibility,
        "allow_recommendation": setting.allow_recommendation,
        "allow_notification": setting.allow_notification,
    }


async def update_settings(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    profile_visibility: str | None = None,
    footprint_visibility: str | None = None,
    plan_visibility: str | None = None,
    allow_recommendation: bool | None = None,
    allow_notification: bool | None = None,
    fields_set: set[str] | None = None,
) -> dict:
    """更新隐私设置（API §3.14）。

    **部分更新语义（PATCH）**：只更新请求体中出现的字段。

    布尔字段必须用 ``fields_set`` 判断而非 ``value is not None``——
    否则 ``allow_recommendation=false`` 会被误判为「未传」而忽略。
    这是本任务最关键的边界（任务描述已明确要求）。

    ``fields_set`` 为 None 时按「非 None 即更新」处理（兼容直接调用）。
    """
    repo = AccountRepository(session)
    setting = await repo.settings.get_by_user_id(user_id)
    if setting is None:
        setting = repo.settings.add(UserSetting(id=uuid7(), user_id=user_id))

    source: dict[str, object] = {
        "profile_visibility": profile_visibility,
        "footprint_visibility": footprint_visibility,
        "plan_visibility": plan_visibility,
        "allow_recommendation": allow_recommendation,
        "allow_notification": allow_notification,
    }

    applied: list[str] = []
    for key, value in source.items():
        should_update = (
            key in fields_set if fields_set is not None else value is not None
        )
        if should_update and value is not None:
            setattr(setting, key, value)
            applied.append(key)

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    logger.info("隐私设置更新 user_id=%s fields=%s", user_id, applied)
    return await get_settings(session, user_id=user_id)




# ============================================================
# 通知
# ============================================================


class NotificationNotFoundError(BusinessError):
    """通知不存在或不属于当前用户。HTTP 404。"""

    def __init__(self) -> None:
        super().__init__(
            ErrorCode.NOTIFICATION_NOT_FOUND, "通知不存在", http_status=404
        )


def _serialize_notification(notification) -> dict:
    """序列化单条通知。

    ``related_type`` / ``related_id`` 供前端点击跳转使用，
    如 ``{"related_type": "trip_plan", "related_id": "..."}``。
    """
    return {
        "id": notification.id,
        "notification_type": notification.notification_type,
        "title": notification.title,
        "content": notification.content,
        "related_type": notification.related_type,
        "related_id": notification.related_id,
        "is_read": notification.is_read,
        "read_at": notification.read_at,
        "created_at": notification.created_at,
    }


async def list_notifications(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    page: int = 1,
    page_size: int = 20,
    is_read: bool | None = None,
    notification_type: str | None = None,
) -> dict:
    """通知列表（API §3.15）。

    返回分页数据 + ``unread_count``。

    **``unread_count`` 是整个账号的未读数，不受筛选条件影响**（DoD 要求）——
    前端的角标显示需要这个总数，若跟着筛选走会显示错误。
    """
    repo = AccountRepository(session)
    offset = (page - 1) * page_size

    items, total = await repo.notifications.list_by_user(
        user_id,
        offset=offset,
        limit=page_size,
        is_read=is_read,
        notification_type=notification_type,
    )
    unread_count = await repo.notifications.count_unread(user_id)

    from app.schemas.pagination import build_page

    result = build_page(
        items=[_serialize_notification(n) for n in items],
        total=total,
        page=page,
        page_size=page_size,
    )
    result["unread_count"] = unread_count
    return result


async def get_unread_count(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    """未读数（API §3.16）。供前端轮询或角标显示。"""
    repo = AccountRepository(session)
    return await repo.notifications.count_unread(user_id)


async def mark_notification_read(
    session: AsyncSession, *, user_id: uuid.UUID, notification_id: uuid.UUID
) -> None:
    """标记单条已读（API §3.17）。

    **幂等**：已读的通知再次标记仍返回成功，且不更新 ``read_at``
    （保留首次阅读时间，用于分析用户何时看到通知）。

    越权保护：按 (id, user_id) 查询，他人的通知一律 404，
    不区分「不存在」与「不属于你」——避免探测通知 ID 是否有效。
    """
    repo = AccountRepository(session)
    notification = await repo.notifications.get_by_id(notification_id, user_id)
    if notification is None:
        raise NotificationNotFoundError()

    if not notification.is_read:
        notification.mark_read()
        await session.commit()
        logger.info("通知已读 user_id=%s notification_id=%s", user_id, notification_id)


async def mark_all_notifications_read(
    session: AsyncSession, *, user_id: uuid.UUID
) -> int:
    """全部标记已读（API §3.18）。

    :return: 本次更新条数（已读的不会被重复计数）
    """
    repo = AccountRepository(session)
    updated = await repo.notifications.mark_all_read(user_id)
    await session.commit()
    logger.info("全部通知已读 user_id=%s updated=%s", user_id, updated)
    return updated


# ============================================================
# 查询工具（供中间件与后续任务使用）
# ============================================================


async def resolve_user_token_version(
    session: AsyncSession, user_id: uuid.UUID
) -> int | None:
    """供 ``api/middleware/auth.py`` 的依赖注入使用。

    返回 None 表示账号不存在或已注销，Token 应失效。
    """
    repo = AccountRepository(session)
    return await repo.get_token_version(user_id)


async def resolve_admin_token_version(
    session: AsyncSession, admin_id: uuid.UUID
) -> int | None:
    """供 ``api/middleware/admin_auth.py`` 使用。"""
    repo = AccountRepository(session)
    return await repo.get_admin_token_version(admin_id)


__all__: list[str] = [
    "AccountBannedError",
    "AccountDeletedError",
    "AccountLockedError",
    "AccountNotFoundError",
    "AuthResult",
    "DuplicateTargetError",
    "InvalidCredentialError",
    "InvalidVerifyCodeError",
    "authenticate",
    "generate_default_nickname",
    "generate_unique_username",
    "get_login_fail_count",
    "register",
    "resolve_admin_token_version",
    "resolve_user_token_version",
    "update_me",
    "update_profile",
    "update_settings",
]


# ============================================================
# 账号注销（API §3.19）
# ============================================================


class InvalidIdentityError(BusinessError):
    """注销时的身份验证失败。

    与密码错误（11006）同码——注销场景不区分「密码错」与「没设密码」，
    统一要求用户走验证码，避免复杂的双路径。
    """

    def __init__(self) -> None:
        super().__init__(
            ErrorCode.INVALID_CREDENTIAL,
            "身份验证失败，请确认密码后重试",
            http_status=401,
        )


#: 注销时要清理的表（数据库设计 §4.3）。
#: **保留**：``footprint``（匿名化保留）、``operation_log``、``user_event``
_DELETE_ON_DEACTIVATE: tuple[str, ...] = (
    "chat_pending_interaction",
    "chat_message",
    "chat_session",
    "memory_long_term",
    "user_quota",
)


async def deactivate_account(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    password: str | None,
) -> None:
    """注销账号（API §3.19）。

    处理规则（数据库设计 §4.3「用户注销」）：
        - **软删除**：``user.status = 'deleted'``，记录保留用于审计
        - **清理**：长期记忆、会话（含消息与待提交交互）、限额记录
        - **保留**：足迹（匿名化，作者显示「已注销用户」）、操作日志

    **身份验证**：
        有密码的账号必须提供正确的密码；无密码账号（验证码注册）
        拒绝注销并提示先用验证码登录——注销是破坏性操作，
        不能仅凭一个可能被盗用的 Access Token 就执行。

    **Token 失效**：``token_version`` 自增，所有设备立即掉线。
    """
    repo = AccountRepository(session)

    user = await repo.users.get_by_id(user_id)
    if user is None:
        raise AccountNotFoundError()
    if user.status == UserStatus.DELETED:
        # 幂等：已注销再调一次不报错
        return

    bindings = await repo.bindings.list_by_user(user_id)
    primary = next((b for b in bindings if b.is_primary), bindings[0] if bindings else None)

    if primary is None or not primary.credential:
        raise BusinessError(
            ErrorCode.PASSWORD_NOT_SET,
            "该账号未设置密码，无法验证身份。请先在个人中心设置密码后再注销",
            http_status=400,
        )

    if not password or not verify_password(password, primary.credential):
        raise InvalidIdentityError()

    # ---------- 清理关联数据 ----------
    # 用原生 SQL：这些表分属 M03/M07/M13，导入它们的模型会形成跨模块耦合。
    # 表可能尚未建立（模块未开发），逐个 try 保证部分失败不阻断注销。
    from sqlalchemy import text

    for table in _DELETE_ON_DEACTIVATE:
        try:
            await session.execute(
                text(f"DELETE FROM {table} WHERE user_id = :uid"),
                {"uid": user_id},
            )
        except Exception:
            # 表不存在或结构不同 → 跳过，注销本身必须能完成
            await session.rollback()
            logger.debug("注销清理跳过 table=%s", table, exc_info=True)

    # ---------- 软删除 + 匿名化 ----------
    user.status = UserStatus.DELETED.value
    # 昵称匿名化：保留记录但不再指向具体个人（数据库设计 §4.3）
    user.nickname = "已注销用户"
    user.avatar_url = None

    # ---------- 释放登录标识 ----------
    # ``oauth_binding`` 有 ``uk_oauth_provider_uid (provider, provider_uid)``
    # 唯一约束。不改写的话，这个邮箱/手机号会被永久占用——用户注销后
    # 再想用同一个邮箱注册会被「已注册」挡住，而他自己也不知道为什么。
    #
    # 改写为带时间戳的匿名值：保留「曾经绑定过某个标识」的记录形态
    # （审计与统计需要计数），同时释放原标识供新账号使用。
    #
    # 旧账号的匿名化足迹不会关联到新账号——它们本来就是两个账号。
    # 释放登录标识，允许用户之后用同一邮箱/手机号重新注册。
    # 与「验证码登录遇到已注销账号」共用同一函数，避免两处逻辑漂移。
    await _release_binding_identifier(session, user_id=user_id)

    # ---------- 使所有 Token 失效 ----------
    await repo.users.increment_token_version(user_id)

    await session.commit()
    logger.info("账号已注销 user_id=%s（登录标识已释放）", user_id)
