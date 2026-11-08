"""定时任务注册入口。

**新增定时任务的两步**：
    1. 在 ``celery_app.py`` 的 ``TASK_MODULES`` 中加入模块路径
    2. 在 ``celery_app.conf.beat_schedule`` 中加入调度配置

本模块统一导出已登记的定时任务，便于测试与运维核对。

当前登记的定时任务：
    - ``popularity-hourly``  每小时重算景点热度（M11-T10）
"""

from __future__ import annotations

# 导入即注册：这些模块内的 @celery_app.task 装饰器在 import 时生效
from app.tasks.schedule import popularity

__all__ = ["popularity"]
