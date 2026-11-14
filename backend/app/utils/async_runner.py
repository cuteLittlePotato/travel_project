"""在同步上下文中运行异步代码。

Celery 任务是同步的，但项目的数据库/Redis 客户端都是 async。
直接 ``asyncio.run()`` 在大多数情况下可用，但在**已经存在事件循环**的
上下文（如测试里被 async 夹具包住的任务调用）会抛
``RuntimeError: asyncio.run() cannot be called from a running event loop``。

``run_async`` 的处理：
    - 当前线程没有运行中的循环 → ``asyncio.run``
    - 当前线程已有运行中的循环 → 在新线程里跑（避免阻塞/嵌套）
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import Any


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """同步地等待协程完成并返回结果。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # 没有运行中的循环——常规路径
        return asyncio.run(coro)

    # 已有运行中的循环：另起线程跑，避免嵌套循环
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
