"""热度计算定时任务（数据管道）。

职责（评审 §Q5）：读取 user_event 聚合行为计数 → 调用 M17-T02 的纯算法 →
写入 popularity_stat。**算法公式不在本任务实现**。

当前为基础工程骨架，业务逻辑在 M11-T10 任务中实现。
"""

from __future__ import annotations

import logging

from app.tasks.base import BaseTask
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    base=BaseTask,
    bind=True,
    name="app.tasks.schedule.popularity.recalculate_popularity",
)
def recalculate_popularity(self) -> dict[str, int]:
    """每小时重算景点热度。幂等：重复执行结果一致。"""
    logger.info("热度计算开始 task_id=%s", self.request.id)
    # TODO(M11-T10): 聚合 user_event → 调用 popularity_algorithm → 写 popularity_stat
    updated = 0
    logger.info("热度计算完成 task_id=%s updated=%s", self.request.id, updated)
    return {"updated": updated}
