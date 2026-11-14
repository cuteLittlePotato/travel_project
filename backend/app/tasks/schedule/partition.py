"""分区维护定时任务（M12-T01）。

每日检查 ``model_call_log`` 的分区是否覆盖「当月 + 未来 2 个月」，
缺哪个建哪个。**每日**执行而非每月：某月漏跑一次（部署中断、
worker 挂掉）也不至于让下月数据全落到 DEFAULT 分区。

幂等由 ``ensure_partitions`` 保证，重复执行不会重复建表。
"""

from __future__ import annotations

import logging

from app.db.session import SessionLocal
from app.modules.model_gateway.partition import ensure_partitions
from app.tasks.base import BaseTask
from app.tasks.celery_app import celery_app
from app.utils.async_runner import run_async

logger = logging.getLogger(__name__)


@celery_app.task(
    base=BaseTask,
    bind=True,
    name="app.tasks.schedule.partition.ensure_monthly_partitions",
)
def ensure_monthly_partitions(self) -> dict[str, list[str]]:
    """确保 ``model_call_log`` 的分区存在，返回新建的分区名。"""
    logger.info("分区维护开始 task_id=%s", self.request.id)

    async def _run() -> list[str]:
        async with SessionLocal() as session:
            return await ensure_partitions(session)

    created = run_async(_run())
    logger.info(
        "分区维护完成 task_id=%s created=%s", self.request.id, created
    )
    return {"created": created}
