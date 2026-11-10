"""C 端行为埋点（M02-T13，数据库设计 §3.9）。

职责：
    1. 写 ``user_event``（行为明细，M17 热度计算与 M16 看板的原始数据）
    2. 累加 ``popularity_stat`` 的计数字段（避免每次统计都扫全表事件）

**埋点绝不能影响主流程**。用户打开详情页是为了看景点，不是为了
给系统记数据；埋点失败就丢弃，主流程照常返回。

**未登录用户也要记录**（``user_id`` 为空）：游客浏览同样反映景点热度，
只是不计入个性化推荐。

**异步化**：当前用 ``asyncio.create_task`` 在响应返回后写入。
后续可替换为 Redis 缓冲 + Celery 批量落库（任务卡的「高频写入」边界），
接口契约不变——调用方只管调 ``record_*``。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.utils.ids import uuid7

logger = logging.getLogger(__name__)


# ============================================================
# 事件类型（数据库设计 §3.9）
# ============================================================

EVENT_VIEW = "view"
EVENT_CLICK = "click"
EVENT_SHARE = "share"
EVENT_CREATE_PLAN = "create_plan"
EVENT_COMPLETE_PLAN = "complete_plan"
EVENT_CHAT_SEND = "chat_send"
EVENT_GRAPH_VIEW = "graph_view"

#: 需要累加哪个计数字段（值为 ``popularity_stat`` 的列名）
_EVENT_TO_COUNTER: dict[str, str] = {
    EVENT_VIEW: "view_count",
    EVENT_CLICK: "click_count",
    EVENT_CREATE_PLAN: "plan_count",
}


# ============================================================
# 核心写入
# ============================================================


async def record_event(
    session: AsyncSession,
    *,
    event_type: str,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    session_uid: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """写入一条行为事件，并按需累加计数字段。

    调用方应保证本函数抛出的异常不会影响业务——见 ``record_*_safe``。
    """
    await session.execute(
        text(
            """
            INSERT INTO user_event
                (id, user_id, event_type, target_type, target_id,
                 session_id, metadata, created_at)
            VALUES
                (:id, :user_id, :event_type, :target_type, :target_id,
                 :session_id, CAST(:metadata AS jsonb), NOW())
            """
        ),
        {
            "id": uuid7(),
            "user_id": user_id,
            "event_type": event_type,
            "target_type": target_type,
            "target_id": target_id,
            "session_id": session_uid,
            "metadata": _json_dumps(metadata),
        },
    )

    counter = _EVENT_TO_COUNTER.get(event_type)
    if counter and target_type == "attraction" and target_id is not None:
        await _increment_counter(session, target_id, counter)

    await session.commit()


async def _increment_counter(
    session: AsyncSession, attraction_id: uuid.UUID, column: str
) -> None:
    """原子累加 ``popularity_stat`` 的计数字段。

    **记录不存在时创建**：景点刚上线时还没有统计行，
    直接 UPDATE 会命中 0 行，计数就丢了。
    用 ``ON CONFLICT DO UPDATE`` 一次完成「有则加、无则建」。

    ``column`` 来自内部映射表，不是用户输入——不存在注入风险。
    """
    await session.execute(
        text(
            f"""
            INSERT INTO popularity_stat (id, attraction_id, {column}, updated_at)
            VALUES (gen_random_uuid(), :aid, 1, NOW())
            ON CONFLICT (attraction_id)
            DO UPDATE SET {column} = popularity_stat.{column} + 1, updated_at = NOW()
            """
        ),
        {"aid": attraction_id},
    )


def _json_dumps(value: dict[str, Any] | None) -> str | None:
    import json

    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        logger.debug("埋点 metadata 无法序列化，已丢弃", exc_info=True)
        return None


# ============================================================
# 安全包装：失败不影响主流程
# ============================================================


def record_event_safe(
    *,
    event_type: str,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    session_uid: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """记录事件的「发射后不管」版本。

    用独立 session + ``create_task``：不占用请求的数据库会话
    （那个会话在响应返回时就关闭了），也不让埋点的耗时拖慢响应。

    **任何异常都在任务内捕获并记 warning**——埋点失败是运维事件，
    不是业务失败。
    """

    async def _run() -> None:
        try:
            async with SessionLocal() as session:
                await record_event(
                    session,
                    event_type=event_type,
                    target_type=target_type,
                    target_id=target_id,
                    user_id=user_id,
                    session_uid=session_uid,
                    metadata=metadata,
                )
        except Exception:
            logger.warning(
                "埋点写入失败 event=%s target=%s:%s",
                event_type,
                target_type,
                target_id,
                exc_info=True,
            )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 没有事件循环（如同步测试上下文）→ 直接跳过，不阻塞调用方
        logger.debug("无运行中的事件循环，跳过埋点 %s", event_type)
        return

    task = loop.create_task(_run())
    # 持有引用直到完成，否则任务可能被 GC 回收
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


#: 持有后台任务引用，避免被垃圾回收打断
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


# ============================================================
# 便捷函数
# ============================================================


def record_attraction_view(
    attraction_id: uuid.UUID, *, user_id: uuid.UUID | None = None
) -> None:
    """记录景点被浏览（详情页打开）。"""
    record_event_safe(
        event_type=EVENT_VIEW,
        target_type="attraction",
        target_id=attraction_id,
        user_id=user_id,
    )


def record_attraction_click(
    attraction_id: uuid.UUID, *, user_id: uuid.UUID | None = None
) -> None:
    """记录景点被点击（列表卡片）。"""
    record_event_safe(
        event_type=EVENT_CLICK,
        target_type="attraction",
        target_id=attraction_id,
        user_id=user_id,
    )


def record_graph_view(
    attraction_id: uuid.UUID, *, user_id: uuid.UUID | None = None
) -> None:
    """记录知识图谱被查看（M10 接口用）。"""
    record_event_safe(
        event_type=EVENT_GRAPH_VIEW,
        target_type="attraction",
        target_id=attraction_id,
        user_id=user_id,
    )


async def flush_background_tasks() -> None:
    """等待所有后台埋点任务完成。

    仅测试使用——生产环境不需要等，响应返回即可。
    """
    if _BACKGROUND_TASKS:
        await asyncio.gather(*_BACKGROUND_TASKS, return_exceptions=True)


__all__ = [
    "EVENT_CHAT_SEND",
    "EVENT_CLICK",
    "EVENT_COMPLETE_PLAN",
    "EVENT_CREATE_PLAN",
    "EVENT_GRAPH_VIEW",
    "EVENT_SHARE",
    "EVENT_VIEW",
    "flush_background_tasks",
    "record_attraction_click",
    "record_attraction_view",
    "record_event",
    "record_event_safe",
    "record_graph_view",
]
