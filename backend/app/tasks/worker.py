"""Celery worker 启动入口。

用法：
    # 默认队列
    uv run python -m app.tasks.worker

    # 指定并发与队列
    uv run python -m app.tasks.worker --concurrency 8 --queues default,document

    # 生产环境推荐直接用 celery 命令（可配合 supervisor/systemd）
    celery -A app.tasks.celery_app.celery_app worker -l info -Q default
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.core.config import settings
from app.core.logging import setup_logging
from app.tasks.celery_app import TASK_MODULES, celery_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动 Celery worker")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=settings.celery_worker_concurrency,
        help="并发 worker 数，默认取 CELERY_WORKER_CONCURRENCY",
    )
    parser.add_argument(
        "--queues",
        default=settings.celery_default_queue,
        help=(
            "消费的队列，逗号分隔。本地开发时建议用独立队列（如 local），"
            "避免与测试服务器上的 worker 抢同一批消息"
        ),
    )
    parser.add_argument("--loglevel", default=settings.log_level.lower())
    args = parser.parse_args(argv)

    # worker 进程有自己的日志体系，复用应用的结构化日志配置
    setup_logging(settings.log_level, settings.log_json)
    logger = logging.getLogger(__name__)
    logger.info(
        "启动 Celery worker queues=%s concurrency=%s tasks=%s",
        args.queues,
        args.concurrency,
        TASK_MODULES,
    )

    celery_app.worker_main(
        argv=[
            "worker",
            f"--loglevel={args.loglevel}",
            f"--concurrency={args.concurrency}",
            f"--queues={args.queues}",
            "--pool=solo" if sys.platform == "win32" else "--pool=prefork",
        ]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
