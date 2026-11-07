"""pytest 全局夹具。

默认用测试替身配置启动应用，不依赖真实的 PostgreSQL/Redis，
保证单元测试可在无外部服务的机器上执行。
"""

from __future__ import annotations

import os

# 必须先于 app 导入设置，Settings 在模块导入时实例化
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters-long")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("NEO4J_PASSWORD", "test")
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "test")
os.environ.setdefault("RABBITMQ_PASSWORD", "test")
os.environ.setdefault("APP_ENV", "testing")

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(create_app())
