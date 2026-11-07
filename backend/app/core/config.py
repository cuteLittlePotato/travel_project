"""云游坊后端配置中心。

所有配置项从环境变量加载，缺失必填项时启动即失败，不做静默兜底。
环境变量命名统一为大写下划线形式，与本类的字段名一一对应（大小写不敏感）。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置。字段按依赖的外部服务分组。"""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 应用 ----------
    app_env: Literal["development", "testing", "production"] = "development"
    app_name: str = "云游坊"
    app_debug: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    api_prefix: str = "/api/v1"
    # 逗号分隔，避免 pydantic-settings 对 list 字段强制 JSON 解析
    cors_origins_raw: str = Field(default="", alias="CORS_ORIGINS")

    # ---------- 安全 ----------
    jwt_secret_key: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=1)
    refresh_token_expire_days: int = Field(default=7, ge=1)
    # Refresh Token 存放的 Cookie 属性（评审 §Q1：Access 存内存 + Refresh 存 httpOnly Cookie）
    refresh_cookie_name: str = "travel_refresh_token"
    refresh_cookie_secure: bool = True
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    refresh_cookie_path: str = "/api/v1/auth"

    # ---------- PostgreSQL ----------
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "travel"
    postgres_user: str = "travel"
    postgres_password: str = Field(min_length=1)
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=20, ge=0)
    db_pool_timeout: int = Field(default=30, ge=1)
    db_echo: bool = False

    # ---------- Redis ----------
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db_business: int = 0  # 业务库
    redis_db_langfuse: int = 1  # 被 Langfuse 占用，业务代码禁止访问
    redis_max_connections: int = Field(default=50, ge=1)

    # ---------- Milvus ----------
    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19530
    milvus_user: str = ""
    milvus_password: str = ""

    # ---------- Neo4j ----------
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = Field(min_length=1)
    neo4j_database: str = "neo4j"

    # ---------- Elasticsearch ----------
    # 逗号分隔的地址列表，如 http://host:9200
    es_hosts_raw: str = Field(default="http://127.0.0.1:9200", alias="ES_HOSTS")
    es_index_prefix: str = "travel"

    # ---------- MinIO ----------
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = Field(min_length=1)
    minio_secret_key: str = Field(min_length=1)
    minio_secure: bool = False
    minio_bucket_documents: str = "travel-documents"
    minio_presign_expire_seconds: int = Field(default=3600, ge=60)

    # ---------- RabbitMQ / Celery ----------
    rabbitmq_host: str = "127.0.0.1"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "travel"
    rabbitmq_password: str = Field(min_length=1)
    rabbitmq_vhost: str = "/"
    celery_task_time_limit: int = Field(default=300, ge=1)
    celery_task_soft_time_limit: int = Field(default=240, ge=1)
    celery_max_retries: int = Field(default=3, ge=0)

    # ---------- LiteLLM ----------
    litellm_base_url: str = "http://127.0.0.1:4000"
    litellm_master_key: str = ""

    # ---------- Langfuse ----------
    langfuse_host: str = "http://127.0.0.1:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # ---------- 日志 ----------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True

    @property
    def cors_origins(self) -> list[str]:
        return self._split(self.cors_origins_raw)

    @property
    def es_hosts(self) -> list[str]:
        return self._split(self.es_hosts_raw)

    @staticmethod
    def _split(raw: str) -> list[str]:
        """逗号分隔字符串转列表，忽略空项。"""
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def alembic_url(self) -> str:
        """Alembic 异步迁移使用的连接串（与业务连接串一致）。"""
        return self.database_url

    @property
    def celery_broker_url(self) -> str:
        return (
            f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}"
            f"@{self.rabbitmq_host}:{self.rabbitmq_port}/{self.rabbitmq_vhost.lstrip('/')}"
        )

    @property
    def celery_result_backend(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db_business}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
