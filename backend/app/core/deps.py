"""依赖注入入口。

所有跨模块共享的依赖集中在此声明，路由层从这里导入，避免各处重复写 ``Depends(...)``。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.infra.redis import get_redis

#: 数据库会话（每请求一个，异常自动回滚）
DBSession = Annotated[AsyncSession, Depends(get_db)]

#: 全局配置
SettingsDep = Annotated[Settings, Depends(get_settings)]

#: Redis 客户端（业务 DB 0）
RedisDep = Annotated[Redis, Depends(get_redis)]
