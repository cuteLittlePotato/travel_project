"""请求上下文。

用 ContextVar 保存请求级信息，供日志、异常处理、审计等跨层读取，
避免把 ``request_id`` 一路作为参数往下传。

注意：``ContextVar`` 在 asyncio 任务间**自动继承**，因此 ``asyncio.create_task``
派生的子任务也能拿到同一个 ``request_id``，日志可正确串联。
"""

from __future__ import annotations

import contextlib
import uuid
from contextvars import ContextVar

#: 请求追踪 ID，默认 "-" 表示不在请求上下文中（如定时任务、启动期）
_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    return _request_id_ctx.get()


def set_request_id(request_id: str) -> object:
    """设置并返回 token，供 ``reset_request_id`` 恢复。"""
    return _request_id_ctx.set(request_id)


def reset_request_id(token: object) -> None:
    """恢复上下文。

    token 非法或已在其他上下文重置过时静默忽略——
    清理失败不应影响请求本身的结果。
    """
    with contextlib.suppress(ValueError, RuntimeError, TypeError):
        _request_id_ctx.reset(token)  # type: ignore[arg-type]


def new_request_id() -> str:
    """生成新的追踪 ID（32 位十六进制，无连字符）。"""
    return uuid.uuid4().hex
