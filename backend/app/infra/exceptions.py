"""基础设施层异常。

设计目标（M0-T06 边界与异常）：各服务不可达时给出**可区分**的错误，
而不是笼统的 500。调用方据此决定重试、降级还是直接失败。

继承关系：
    InfraError                    基础设施异常基类（HTTP 503）
    ├── MilvusUnavailableError    Milvus 不可达
    ├── Neo4jUnavailableError     Neo4j 不可达
    │   └── Neo4jNodeNotFoundError   节点/关系不存在
    ├── ElasticsearchUnavailableError
    └── StorageUnavailableError   MinIO 不可达
        ├── ObjectNotFoundError       对象不存在
        └── BucketNotFoundError       桶不存在
"""

from __future__ import annotations

from app.core.exceptions import BusinessError

#: 基础设施不可用统一使用 10002（服务端内部错误）+ HTTP 503。
#: 不用 23001 等业务码，因为这些是系统层故障，不属于任何业务模块。
INFRA_ERROR_CODE = 10002


class InfraError(BusinessError):
    """基础设施异常基类。

    ``service`` 用于日志与前端提示区分故障来源，如 ``"milvus"``。
    """

    default_http_status = 503

    def __init__(self, service: str, message: str) -> None:
        self.service = service
        super().__init__(
            INFRA_ERROR_CODE,
            f"{service} 服务异常：{message}",
            http_status=503,
        )


# ---------------- Milvus ----------------


class MilvusUnavailableError(InfraError):
    def __init__(self, message: str = "连接失败") -> None:
        super().__init__("Milvus", message)


# ---------------- Neo4j ----------------


class Neo4jUnavailableError(InfraError):
    def __init__(self, message: str = "连接失败") -> None:
        super().__init__("Neo4j", message)


class Neo4jNodeNotFoundError(InfraError):
    """图谱节点或关系不存在。HTTP 404，与「服务不可用」区分开。"""

    def __init__(self, message: str = "节点不存在") -> None:
        BusinessError.__init__(self, INFRA_ERROR_CODE, f"Neo4j 服务异常：{message}", http_status=404)
        self.service = "Neo4j"


# ---------------- Elasticsearch ----------------


class ElasticsearchUnavailableError(InfraError):
    def __init__(self, message: str = "连接失败") -> None:
        super().__init__("Elasticsearch", message)


class ElasticsearchIndexNotFoundError(InfraError):
    def __init__(self, index: str) -> None:
        BusinessError.__init__(
            self, INFRA_ERROR_CODE, f"Elasticsearch 索引不存在：{index}", http_status=404
        )
        self.service = "Elasticsearch"


# ---------------- 对象存储 ----------------


class StorageUnavailableError(InfraError):
    def __init__(self, message: str = "连接失败") -> None:
        super().__init__("MinIO", message)


class ObjectNotFoundError(InfraError):
    """对象不存在。HTTP 404，调用方可用于区分「没上传」与「存储挂了」。"""

    def __init__(self, object_key: str) -> None:
        BusinessError.__init__(
            self, INFRA_ERROR_CODE, f"对象不存在：{object_key}", http_status=404
        )
        self.service = "MinIO"


class BucketNotFoundError(InfraError):
    def __init__(self, bucket: str) -> None:
        BusinessError.__init__(
            self, INFRA_ERROR_CODE, f"存储桶不存在：{bucket}", http_status=404
        )
        self.service = "MinIO"
