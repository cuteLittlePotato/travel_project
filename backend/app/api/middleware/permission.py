"""B 端权限项校验（M15-T05，API §16.3）。

设计要点（评审 §Q13：权限数据驱动）：

1. **不硬编码角色判断**。接口声明「需要哪个权限项」，而不是
   「需要哪个角色」。加角色只需配置数据，不改代码。

2. **超级管理员用「拥有全部权限项」表达，不用 if 判断**。
   种子数据（M15-T02）已把全部权限项授予超管角色，校验时它
   天然通过——不需要通配符记录，也不需要判断角色。
   这样「超管能做什么」是数据，而不是散落在代码里的分支。

3. **权限集合缓存在 Redis**，键为 ``travel:perm:{admin_id}``。
   权限校验在**每个** B 端请求上执行，直查数据库会让每个请求
   多 3 次 JOIN。缓存后是一次 Redis GET。

   失效策略：角色/权限变更时删除受影响管理员的缓存键。具体见
   ``invalidate_admin_permissions``。缓存本身设 TTL 兜底，
   即使漏删也会在 ``PERMISSION_CACHE_TTL`` 秒后自动恢复。

4. **Redis 不可用时降级直查数据库**。权限校验是安全边界，
   宁可慢也不能因为缓存不可用就放行或全部拒绝。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.admin_auth import CurrentAdmin, require_admin
from app.core.deps import DBSession
from app.core.exceptions import BusinessError
from app.infra import redis as redis_infra

logger = logging.getLogger(__name__)

#: 权限集合的缓存键前缀
PERMISSION_CACHE_PREFIX = "perm:"

#: 空权限集合的占位成员。
#: Redis 的 Set 为空时键不存在，无法区分「没缓存」与「缓存了空集合」，
#: 结果是没角色的管理员每个请求都回源查库。
EMPTY_PERMISSION_MARKER = "__empty__"

#: 缓存 TTL（秒）。权限变更会主动删键，TTL 只是兜底。
PERMISSION_CACHE_TTL = 300


class PermissionDeniedError(BusinessError):
    """权限不足（API §16.3，25001 / HTTP 403）。"""

    def __init__(self, permission: str | None = None) -> None:
        message = "权限不足"
        if permission:
            message = f"权限不足，需要权限项：{permission}"
        super().__init__(25001, message, http_status=403)


#: 权限集合解析器。测试可替换以绕过 Redis。
PermissionResolver = Callable[[AsyncSession, uuid.UUID], Awaitable[set[str]]]


def _decode_cached(raw: set[str]) -> set[str]:
    """把缓存里的成员还原成权限集合，剔除空集合占位符。"""
    return {code for code in raw if code != EMPTY_PERMISSION_MARKER}


def _cache_key(admin_id: uuid.UUID) -> str:
    from app.core.config import settings

    return f"{settings.redis_key_prefix}:{PERMISSION_CACHE_PREFIX}{admin_id}"


async def _load_from_db(session: AsyncSession, admin_id: uuid.UUID) -> set[str]:
    """从数据库加载管理员的全部权限编码（多角色取并集）。

    超级管理员在种子数据里已关联全部权限项，因此这里
    **不需要任何角色特判**——它拿到的是完整集合，校验时自然通过。
    """
    result = await session.execute(
        text(
            """
            SELECT DISTINCT p.code
            FROM permission p
            JOIN role_permission rp ON rp.permission_id = p.id
            JOIN admin_user_role aur ON aur.role_id = rp.role_id
            WHERE aur.admin_user_id = :admin_id
            """
        ),
        {"admin_id": admin_id},
    )
    return {row[0] for row in result.all()}


async def resolve_permissions(
    session: AsyncSession, admin_id: uuid.UUID
) -> set[str]:
    """取得管理员的权限集合，优先读缓存。

    Redis 不可用时**降级直查数据库**——权限校验是安全边界，
    不能因为缓存故障就放行或全部拒绝。

    **空集合必须缓存**：新管理员还没分配角色时权限集合为空，
    如果空集合不缓存，每个请求都会回源查库。空集合用一个
    占位成员 ``__empty__`` 表示——Redis 空的 Set 不存在，
    无法区分「没缓存」与「缓存了空集合」。
    """
    key = _cache_key(admin_id)

    try:
        cached = await redis_infra.get_client().smembers(key)
        if cached:
            return _decode_cached(cached)
    except Exception:
        logger.warning("权限缓存读取失败，降级查库 admin_id=%s", admin_id, exc_info=True)
        return await _load_from_db(session, admin_id)

    codes = await _load_from_db(session, admin_id)

    try:
        client = redis_infra.get_client()
        pipe = client.pipeline()
        # 先删再写——避免残留旧权限
        pipe.delete(key)
        pipe.sadd(key, *(codes or {EMPTY_PERMISSION_MARKER}))
        pipe.expire(key, PERMISSION_CACHE_TTL)
        await pipe.execute()
    except Exception:
        # 写缓存失败不影响本次校验结果
        logger.warning("权限缓存写入失败 admin_id=%s", admin_id, exc_info=True)

    return codes


async def invalidate_admin_permissions(admin_id: uuid.UUID) -> None:
    """删除某个管理员的权限缓存。

    调用时机：
        - 管理员角色变更
        - 角色权限变更（需遍历持有该角色的管理员）
        - 角色删除
        - 管理员删除

    失败不抛异常——缓存只是加速层，TTL 会兜底。
    """
    try:
        await redis_infra.get_client().delete(_cache_key(admin_id))
    except Exception:
        logger.warning(
            "权限缓存失效失败 admin_id=%s（将由 TTL 兜底）", admin_id, exc_info=True
        )


async def invalidate_role_permissions(session: AsyncSession, role_id: uuid.UUID) -> None:
    """角色权限变更后，失效所有持有该角色的管理员的缓存。"""
    result = await session.execute(
        text("SELECT admin_user_id FROM admin_user_role WHERE role_id = :role_id"),
        {"role_id": role_id},
    )
    for (admin_id,) in result.all():
        await invalidate_admin_permissions(admin_id)


def get_permission_resolver() -> PermissionResolver:
    return resolve_permissions


def require_permission(code: str) -> Callable[..., Awaitable[CurrentAdmin]]:
    """依赖工厂：声明接口所需的权限项。

    用法::

        @router.get("/attractions")
        async def list_attractions(
            _: Annotated[CurrentAdmin, Depends(require_permission("catalog.attraction.read"))],
        ): ...

    校验逻辑：
        1. 取到当前管理员（``require_admin`` 已完成身份校验）
        2. 取权限集合（缓存优先）
        3. 命中所需权限项 → 放行，否则 403 / 25001

    **没有通配符分支**：超管在种子数据里拥有全部权限项，
    直接命中即可。引入通配符反而会让「超管到底有哪些权限」
    变成代码里的隐式规则，与数据驱动的目标背道而驰。
    """

    async def _checker(
        current: Annotated[CurrentAdmin, Depends(require_admin)],
        session: DBSession,
        resolver: Annotated[PermissionResolver, Depends(get_permission_resolver)],
    ) -> CurrentAdmin:
        codes = await resolver(session, current.admin_id)

        if code in codes:
            return current

        raise PermissionDeniedError(code)

    # 给依赖函数一个可读的名字，便于 OpenAPI 与日志排查
    _checker.__name__ = f"require_permission_{code.replace('.', '_')}"
    return _checker


def RequirePermission(code: str):
    """``Annotated`` 形式的便捷封装。

    用法::

        async def handler(_: RequirePermission("model.model.read")): ...
    """
    return Annotated[CurrentAdmin, Depends(require_permission(code))]


__all__ = [
    "PERMISSION_CACHE_PREFIX",
    "PERMISSION_CACHE_TTL",
    "PermissionDeniedError",
    "RequirePermission",
    "get_permission_resolver",
    "invalidate_admin_permissions",
    "invalidate_role_permissions",
    "require_permission",
    "resolve_permissions",
]
