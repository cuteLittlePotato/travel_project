"""操作日志的自动记录（M15-T06，评审 §Q13）。

**只记增删改与登录登出，不记查询**——DDL 注释的明确取舍。
查询占 B 端请求的绝大多数，记下来会把真正需要审计的写操作淹没。
``operation_log.action`` 的 CHECK 约束也据此只允许六个值。

记录方式：**响应后异步写入**，不阻塞主流程。
    写日志失败绝不能影响业务结果——用户已经看到「保存成功」，
    却因为日志写不进去而收到 500，是最糟糕的体验。

失败处理：
    日志写入失败只记 warning，不抛异常。审计日志缺失是可以接受的
    运维事件，业务失败不是。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.system.constants import OperationAction
from app.modules.system.models import OperationLog
from app.utils.ids import uuid7

logger = logging.getLogger(__name__)

#: 需要记录日志的 HTTP 方法 → 操作类型。
#: **GET / HEAD / OPTIONS 不在其中**——查询不记日志（评审 §Q13）。
METHOD_TO_ACTION: dict[str, str] = {
    "POST": OperationAction.CREATE.value,
    "PUT": OperationAction.UPDATE.value,
    "PATCH": OperationAction.UPDATE.value,
    "DELETE": OperationAction.DELETE.value,
}

#: 路径首段 → 模块名。用于日志的 ``module`` 字段。
#: 未命中的走 ``unknown``，便于发现新接口漏登记。
PATH_MODULE_MAP: dict[str, str] = {
    "regions": "catalog",
    "attraction-categories": "catalog",
    "attractions": "catalog",
    "restaurants": "catalog",
    "hotels": "catalog",
    "transports": "catalog",
    "activities": "catalog",
    "models": "model",
    "system": "system",
    "knowledge-bases": "knowledge_base",
    "knowledge-graph": "knowledge_graph",
    "featured-knowledge-graphs": "knowledge_graph",
    "users": "user_ops",
    "quota": "quota",
    "dashboard": "dashboard",
}

#: 这些路径段是动作后缀，不是资源名
_ROUTE_SUFFIXES = frozenset(
    {"status", "default", "password", "permissions", "categories", "publish"}
)


def resolve_module(path: str) -> str:
    """从请求路径推断模块名。

    ``/api/v1/admin/attractions/xxx`` → ``catalog``
    """
    parts = [p for p in path.split("/") if p]
    # 跳过 api / v1 / admin
    try:
        idx = parts.index("admin")
    except ValueError:
        return "unknown"

    for segment in parts[idx + 1 :]:
        if segment in PATH_MODULE_MAP:
            return PATH_MODULE_MAP[segment]

    return "unknown"


def resolve_target(path: str) -> tuple[str | None, uuid.UUID | None]:
    """从路径推断目标类型与 ID。

    ``/api/v1/admin/attractions/{uuid}`` → ``("attractions", UUID)``
    """
    parts = [p for p in path.split("/") if p]
    try:
        idx = parts.index("admin")
    except ValueError:
        return None, None

    rest = parts[idx + 1 :]
    if not rest:
        return None, None

    target_type = rest[0]
    for segment in rest[1:]:
        if segment in _ROUTE_SUFFIXES:
            break
        try:
            return target_type, uuid.UUID(segment)
        except ValueError:
            continue

    return target_type, None


def should_log(method: str) -> bool:
    """是否需要记录日志。

    只有增删改才记（评审 §Q13）。GET 一律不记。
    """
    return method.upper() in METHOD_TO_ACTION


def build_log_entity(
    *,
    admin_id: uuid.UUID,
    request: Request,
    is_success: bool,
    detail: dict[str, Any] | None = None,
) -> OperationLog:
    """构造一条操作日志实体（**不落库**）。"""
    method = request.method.upper()
    path = request.url.path
    target_type, target_id = resolve_target(path)

    return OperationLog(
        id=uuid7(),
        admin_user_id=admin_id,
        module=resolve_module(path),
        action=METHOD_TO_ACTION.get(method, method.lower()),
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:500] or None,
        is_success=is_success,
    )


def _client_ip(request: Request) -> str | None:
    """取真实客户端 IP。

    Nginx 反代后 ``request.client`` 是反代地址，需读
    ``X-Forwarded-For`` 的第一段（最初的客户端）。
    列宽 45，IPv6 也放得下。
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first[:45]

    if request.client:
        return request.client.host[:45]

    return None


async def write_operation_log(
    session: AsyncSession,
    *,
    admin_id: uuid.UUID,
    request: Request,
    is_success: bool,
    detail: dict[str, Any] | None = None,
) -> None:
    """写入一条操作日志。

    失败只记 warning，**绝不向上抛**——日志写不进去不能影响业务。
    独立的 session 提交，避免与业务事务互相拖累。
    """
    try:
        log = build_log_entity(
            admin_id=admin_id,
            request=request,
            is_success=is_success,
            detail=detail,
        )
        session.add(log)
        await session.commit()
    except Exception:
        logger.warning(
            "操作日志写入失败 path=%s method=%s",
            request.url.path,
            request.method,
            exc_info=True,
        )


LogAction = Literal["create", "update", "delete", "export", "login", "logout"]

__all__ = [
    "METHOD_TO_ACTION",
    "PATH_MODULE_MAP",
    "LogAction",
    "build_log_entity",
    "resolve_module",
    "resolve_target",
    "should_log",
    "write_operation_log",
]
