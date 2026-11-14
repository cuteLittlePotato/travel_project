"""C 端景点内容路由（API §4.1 / §4.2 / §4.6 / §4.9）。

全部**公开无需认证**（API §16.3 权限矩阵）：景点浏览是 C 端的核心
体验，要求登录会阻断转化。未登录用户也能看，登录后才解锁对话、
计划、足迹等能力。
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.middleware.auth import OptionalUserDep
from app.core.deps import DBSession
from app.core.response import success
from app.modules.attraction import service
from app.modules.recommend import event_recorder

logger = logging.getLogger(__name__)

router = APIRouter()


def _parse_category_ids(raw: str | None) -> list[uuid.UUID] | None:
    """解析逗号分隔的分类 ID。

    非法 UUID 直接忽略而非报错——这类参数来自前端筛选器，
    传坏了最多筛不出来，不该让整个列表 400。
    """
    if not raw:
        return None

    parsed: list[uuid.UUID] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            parsed.append(uuid.UUID(part))
        except ValueError:
            logger.debug("忽略非法的分类 ID: %s", part)
            continue

    return parsed or None


@router.get("/attractions", summary="景点列表", response_model=None)
async def list_attractions(
    session: DBSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: Annotated[str | None, Query(max_length=50)] = None,
    city_id: Annotated[uuid.UUID | None, Query()] = None,
    province_id: Annotated[uuid.UUID | None, Query()] = None,
    category_ids: Annotated[str | None, Query(max_length=500)] = None,
    sort_by: Annotated[
        str, Query(pattern="^(popularity|created_at|ticket_price)$")
    ] = "popularity",
    sort_order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
) -> dict[str, object]:
    """景点列表（API §4.1）。

    - 仅返回已上架景点
    - ``category_ids`` 逗号分隔，多个为「且」关系
    - 热度排序时，无统计记录的景点回退 ``base_popularity``
    """
    return success(
        await service.list_attractions(
            session,
            keyword=keyword,
            city_id=city_id,
            province_id=province_id,
            category_ids=_parse_category_ids(category_ids),
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/attractions/suggestions", summary="搜索建议", response_model=None)
async def suggest(
    session: DBSession,
    keyword: Annotated[str, Query(min_length=1, max_length=50)],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> dict[str, object]:
    """搜索建议（API §4.9）。

    返回景点与地区（省 + 市）混合列表，前缀匹配优先。
    """
    return success(await service.suggest(session, keyword=keyword, limit=limit))


@router.get(
    "/attractions/{attraction_id}", summary="景点详情", response_model=None
)
async def get_attraction(
    attraction_id: uuid.UUID,
    session: DBSession,
    current: OptionalUserDep,
) -> dict[str, object]:
    """景点详情（API §4.2）。

    未上架景点视同不存在，返回 12001（404）。

    **浏览埋点**（M02-T13）：记录 ``view`` 事件并累加
    ``popularity_stat.view_count``。未登录用户也记录（``user_id`` 为空）。

    埋点在响应组装**之后**触发，失败不影响返回——
    用户是来看景点的，不是来给系统记数据的。
    """
    detail = await service.get_attraction_detail(
        session, attraction_id=attraction_id
    )

    # 埋点在这里再包一层 try：`record_event_safe` 内部已吞掉异常，
    # 但如果它自己被替换/损坏（如测试注入故障），不应连累详情返回。
    # 「埋点失败不影响主流程」这条约定，在调用方也要成立。
    try:
        event_recorder.record_attraction_view(
            attraction_id,
            user_id=current.user_id if current else None,
        )
    except Exception:
        logger.warning("浏览埋点触发失败 attraction_id=%s", attraction_id, exc_info=True)

    return success(detail)


@router.get(
    "/attraction-categories", summary="景点分类列表", response_model=None
)
async def list_categories(session: DBSession) -> dict[str, object]:
    """分类列表（API §4.6）。按 ``theme`` / ``level`` 分组返回。"""
    return success(await service.list_categories(session))
