"""pytest 全局夹具。

单元测试不依赖真实 PostgreSQL/Redis：若仓库下没有 ``backend/.env``，
这里注入一组占位配置，保证测试可在任何机器上直接跑。
存在 ``backend/.env`` 时以其为准，供集成测试连真实环境。
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

if not _ENV_FILE.exists():
    # 仅在没有真实配置时兜底，避免覆盖开发者的本地环境
    os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters-long")
    os.environ.setdefault("POSTGRES_PASSWORD", "test")
    os.environ.setdefault("NEO4J_PASSWORD", "test")
    os.environ.setdefault("MINIO_ACCESS_KEY", "test")
    os.environ.setdefault("MINIO_SECRET_KEY", "test")
    os.environ.setdefault("RABBITMQ_PASSWORD", "test")
    os.environ.setdefault("APP_ENV", "testing")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-destructive",
        action="store_true",
        default=False,
        help="执行会清空数据库的测试（标记为 destructive）",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """默认跳过 destructive 测试。

    这类测试会 ``DROP SCHEMA public CASCADE``，跑完整个库就空了。
    开发库同时承载本地联调数据，误执行一次要重新迁移 + 重新灌数，
    因此必须显式 ``--run-destructive`` 才执行。
    """
    if config.getoption("--run-destructive"):
        return

    skip = pytest.mark.skip(reason="destructive 测试需显式 --run-destructive")
    for item in items:
        if "destructive" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(create_app())
