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


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(create_app())
