"""站点配置的读写（M15-T07，API §14.12 / §14.13）。

存储形式与接口形式不同：
    - **存储**：``site_setting`` 是键值对表（``setting_key`` + JSONB）
    - **接口**：固定的四个字段

这层差异由本模块吸收——路由层拿到的直接是固定字段的 dict。

为什么不直接把键值对返回给前端：
    固定字段是**契约**，前端可以直接绑定；键值对需要前端自己
    维护 key 常量，改个配置项就得两边同步。键值对的价值在**存储侧**：
    新增配置项不用改表结构。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.system.models import SiteSetting
from app.modules.system.repository import SiteSettingRepository

logger = logging.getLogger(__name__)

#: 配置项默认值（API §14.12 的响应示例）。
#: 库里没有记录时返回这些值，而不是报错——站点配置是「有默认值的
#: 可选项」，不是「必须初始化的数据」。
DEFAULT_SETTINGS: dict[str, Any] = {
    "site_name": "云游坊",
    "site_description": "智能旅游规划平台",
    "allow_registration": True,
    "allow_content_review": True,
}

#: 配置项的中文说明，写入时一并存进 ``description`` 字段，
#: 便于运维直接查库时知道这一行是什么。
SETTING_DESCRIPTIONS: dict[str, str] = {
    "site_name": "站点名称",
    "site_description": "站点描述",
    "allow_registration": "是否允许新用户注册",
    "allow_content_review": "是否开启内容审核",
}

#: 缓存键（Redis）
SETTINGS_CACHE_KEY_SUFFIX = "settings:site"

#: 缓存 TTL（秒）。配置变更主动失效，TTL 只是兜底。
SETTINGS_CACHE_TTL = 600


def _cache_key() -> str:
    from app.core.config import settings

    return f"{settings.redis_key_prefix}:{SETTINGS_CACHE_KEY_SUFFIX}"


async def get_settings(session: AsyncSession) -> dict[str, Any]:
    """读取站点配置（API §14.12）。

    返回值一定包含全部四个字段——库里缺哪个就用默认值补哪个。
    这样前端不必处理「字段可能不存在」的情况。

    边界：配置读取有缓存，更新后失效。
    """
    import json

    from app.infra import redis as redis_infra

    # 先试缓存
    try:
        cached = await redis_infra.get_client().get(_cache_key())
        if cached:
            return json.loads(cached)
    except Exception:
        logger.warning("站点配置缓存读取失败，降级查库", exc_info=True)

    repo = SiteSettingRepository(session)
    rows = await repo.list_all()
    stored = {row.setting_key: row.setting_value for row in rows}

    # 默认值打底，库里的值覆盖——新增配置项时不用改这里
    result = {**DEFAULT_SETTINGS, **stored}

    # 只返回已知的四个字段，避免库里的历史遗留键泄漏到接口
    result = {key: result[key] for key in DEFAULT_SETTINGS if key in result}

    try:
        await redis_infra.get_client().set(
            _cache_key(),
            json.dumps(result, ensure_ascii=False),
            ex=SETTINGS_CACHE_TTL,
        )
    except Exception:
        logger.warning("站点配置缓存写入失败", exc_info=True)

    return result


async def update_settings(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    updated_by: uuid.UUID,
) -> None:
    """更新站点配置（API §14.13）。

    只写传入的字段——PATCH 语义。没传的配置项保持原值。

    首次写入某个配置项时新建记录，之后更新。
    """
    repo = SiteSettingRepository(session)

    for key, value in payload.items():
        if key not in DEFAULT_SETTINGS:
            # 未知配置项直接忽略而非报错——接口契约是固定四字段，
            # Pydantic 已经挡住了额外字段，这里是防御性处理
            logger.warning("忽略未知的配置项 key=%s", key)
            continue

        existing = await repo.get_by_key(key)
        if existing is None:
            from app.utils.ids import uuid7

            repo.add(
                SiteSetting(
                    id=uuid7(),
                    setting_key=key,
                    setting_value=value,
                    description=SETTING_DESCRIPTIONS.get(key),
                    updated_by=updated_by,
                )
            )
        else:
            existing.setting_value = value
            existing.updated_by = updated_by

    await repo.flush()
    await session.commit()

    # 更新后必须失效缓存，否则下一次读还会拿到旧值
    await invalidate_settings_cache()

    logger.info("更新站点配置 keys=%s by=%s", list(payload.keys()), updated_by)


async def invalidate_settings_cache() -> None:
    """删除站点配置缓存。失败不抛——TTL 会兜底。"""
    from app.infra import redis as redis_infra

    try:
        await redis_infra.get_client().delete(_cache_key())
    except Exception:
        logger.warning("站点配置缓存失效失败（将由 TTL 兜底）", exc_info=True)


__all__ = [
    "DEFAULT_SETTINGS",
    "SETTINGS_CACHE_KEY_SUFFIX",
    "SETTINGS_CACHE_TTL",
    "SETTING_DESCRIPTIONS",
    "get_settings",
    "invalidate_settings_cache",
    "update_settings",
]
