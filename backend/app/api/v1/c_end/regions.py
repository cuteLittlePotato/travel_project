"""C 端地区字典（API §4.7）。

公开接口，无需认证——地区列表是筛选项与个人资料都要用的公共数据，
要求登录才能看会带来无谓的耦合。

**只暴露 id / name / code / level / heat_score**：
``parent_id`` 也有用（前端做级联），但没必要暴露 ``sort_weight``
这类运营配置字段。
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import DBSession
from app.core.response import success
from app.modules.attraction.repository import AttractionQueryRepository

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/regions", summary="地区列表", response_model=None)
async def list_regions(
    session: DBSession,
    level: Annotated[int | None, Query(ge=1, le=2)] = None,
    parent_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, object]:
    """地区列表（API §4.7）。

    - ``level=1`` 查省份，``level=2`` 查城市
    - ``parent_id`` 查某省下的城市
    - 两者都不传返回全部（省份在前）

    个人资料的「常驻地区」选择器用它做省市级联。
    """
    repo = AttractionQueryRepository(session)
    regions = await repo.list_regions(level=level, parent_id=parent_id)

    return success(
        {
            "items": [
                {
                    "id": region.id,
                    "parent_id": region.parent_id,
                    "name": region.name,
                    "code": region.code,
                    "level": region.level,
                    "heat_score": region.heat_score,
                }
                for region in regions
            ]
        }
    )
