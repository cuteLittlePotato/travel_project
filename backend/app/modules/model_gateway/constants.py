"""M12 模型管理的枚举与常量。

与 ``scripts/sql/schema.sql`` 的 CHECK 约束一一对应。
"""

from __future__ import annotations

from enum import StrEnum


class ModelCategory(StrEnum):
    """模型类别（``model.category``）。

    五类模型的调用方式相同（OpenAI 兼容接口），差别在使用场景：
        - ``chat``：文本对话，M03/M06 使用
        - ``vision``：图片理解，用于识别用户上传的图片
        - ``embedding``：向量化，M09 知识库切片入库与检索
        - ``rerank``：重排序，M08 检索结果精排
        - ``ocr``：OCR 解析，M09 文档解析

    **无 ``vector_dim`` 字段**——向量维度由配置文件控制（需求 2.2.5.2）。
    """

    CHAT = "chat"
    VISION = "vision"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    OCR = "ocr"


class CallerType(StrEnum):
    """调用来源（``model_call_log.caller_type``）。

    区分依据是**是否计入用户额度**：
        - ``user_chat``：C 端对话，计入用户额度（M13）
        - ``system_document``：B 端文档处理，不计入用户额度
    """

    USER_CHAT = "user_chat"
    SYSTEM_DOCUMENT = "system_document"


class CallErrorType(StrEnum):
    """调用失败类型（``model_call_log.error_type``）。

    数据库该字段是自由文本（``VARCHAR(50)``），没有 CHECK 约束。
    这里定义枚举是为了**统一应用层写日志的取值**，便于统计聚合。
    """

    TIMEOUT = "timeout"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    FORMAT_INVALID = "format_invalid"


#: 默认超时秒数（``model.timeout_seconds`` 的 DDL 默认值）
DEFAULT_TIMEOUT_SECONDS = 60

#: 类别 → 中文显示名（API §10.11）。
#: 顺序即前端下拉框的展示顺序：文本类在前，处理类在后。
MODEL_CATEGORY_LABELS: dict[str, str] = {
    "chat": "文本对话",
    "vision": "图片理解",
    "embedding": "向量化",
    "rerank": "重排序",
    "ocr": "OCR解析",
}

# ============================================================
# M12 错误码（码段 22000-22999）
# ============================================================

#: 同类别下 model_code + base_url 重复（API §10.2，HTTP 409）
ERROR_MODEL_DUPLICATE = 22001

#: category 不可修改（API §10.4，HTTP 400）
ERROR_MODEL_CATEGORY_IMMUTABLE = 22002

#: 该模型是类别默认，不能禁用/删除（API §10.5 / §10.7，HTTP 409）
ERROR_MODEL_IS_DEFAULT = 22003

#: 被知识库引用，不能禁用（API §10.5，HTTP 409）
ERROR_MODEL_REFERENCED_DISABLE = 22004

#: 模型未启用（API §10.6，不能设为默认）
ERROR_MODEL_NOT_ENABLED = 22005

#: 被知识库引用，不能删除（API §10.7，HTTP 409）
ERROR_MODEL_REFERENCED_DELETE = 22006

#: 模型不存在（M12-T02 补充；API 文档未定义，22000 段内自定义）
ERROR_MODEL_NOT_FOUND = 22007


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "ERROR_MODEL_CATEGORY_IMMUTABLE",
    "ERROR_MODEL_DUPLICATE",
    "ERROR_MODEL_IS_DEFAULT",
    "ERROR_MODEL_NOT_ENABLED",
    "ERROR_MODEL_NOT_FOUND",
    "ERROR_MODEL_REFERENCED_DELETE",
    "ERROR_MODEL_REFERENCED_DISABLE",
    "CallErrorType",
    "CallerType",
    "MODEL_CATEGORY_LABELS",
    "ModelCategory",
]
