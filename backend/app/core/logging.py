"""结构化日志与请求追踪。

可观测性分层（架构 §2.1）：
    - **Langfuse**：LLM 调用、Agent 图执行、Prompt/Token 追踪
    - **本模块**：业务日志、请求链路、错误堆栈

两者职责不重叠。业务代码用 ``logging.getLogger(__name__)`` 记录即可，
只有需要追踪模型调用时才走 ``infra/langfuse``。

关键约定：
    - 每条日志自动带 ``request_id``（来自 ContextVar，无需手动传）
    - 敏感字段在**格式器层**统一脱敏，业务代码不必逐个处理
    - 生产环境强制不低于 INFO，避免 DEBUG 日志泄露内部细节
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

from app.core.context import get_request_id

# ============================================================
# 脱敏
# ============================================================

#: 键名命中这些片段即脱敏（不区分大小写）
SENSITIVE_KEY_PATTERNS = (
    "password",
    "passwd",
    "token",
    "secret",
    "api_key",
    "apikey",
    "credential",
    "authorization",
    "cookie",
    "session_id",
    "private_key",
    "access_key",
)

#: 消息正文中的敏感片段。用于捕获「日志里直接拼了密码」这类写法
_MESSAGE_PATTERNS = (
    # password=xxx / password: xxx / "password": "xxx" / 'api_key': 'xxx'
    # 键名允许被引号包裹（JSON 风格），值也允许被引号包裹
    re.compile(
        r"(?i)[\"']?\b(password|passwd|token|secret|api[_-]?key|credential)\b[\"']?"
        r"\s*[=:]\s*[\"']?([^\s,\"'&}]{3,})",
    ),
    # Bearer xxx
    re.compile(r"(?i)\bBearer\s+([A-Za-z0-9\-_.]{10,})"),
)

REDACTED = "***"


def redact_value(key: str, value: Any) -> Any:
    """按键名判断是否脱敏。"""
    lowered = key.lower()
    if any(pattern in lowered for pattern in SENSITIVE_KEY_PATTERNS):
        return REDACTED
    return value


def redact_message(message: str) -> str:
    """脱敏消息正文中的敏感片段。

    业务代码若把密码直接拼进日志（``logger.info(f"login pwd={pwd}")``），
    仅靠键名判断无法拦截，这里做正则兜底。
    """
    result = message
    for pattern in _MESSAGE_PATTERNS:
        def _replace(match: re.Match[str]) -> str:
            # 保留键名，只替换值
            groups = match.groups()
            if len(groups) == 2:
                return f"{groups[0]}={REDACTED}"
            return f"Bearer {REDACTED}"

        result = pattern.sub(_replace, result)
    return result


def sanitize(data: Any, *, depth: int = 0) -> Any:
    """递归脱敏嵌套结构（dict / list）。

    ``depth`` 限制递归层数，防止循环引用或超深结构拖慢日志。
    """
    if depth > 6:
        return "<max-depth>"

    if isinstance(data, dict):
        return {
            key: REDACTED if _is_sensitive_key(str(key)) else sanitize(value, depth=depth + 1)
            for key, value in data.items()
        }
    if isinstance(data, (list, tuple)):
        return [sanitize(item, depth=depth + 1) for item in data]
    return data


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(pattern in lowered for pattern in SENSITIVE_KEY_PATTERNS)


# ============================================================
# 请求追踪
# ============================================================


class RequestIdFilter(logging.Filter):
    """把 ``request_id`` 注入每条日志记录。

    用 Filter 而非 Formatter 内部读取的原因：其他 Handler（如文件、
    日志采集器）也能拿到该字段，不必重复实现。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()  # type: ignore[attr-defined]
        return True


class RedactionFilter(logging.Filter):
    """在日志记录进入 Handler 前完成脱敏。

    放在 Filter 层而非 Formatter，保证任何 Handler（控制台、文件、
    采集器）拿到的都已是脱敏后的内容。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # 消息正文
        try:
            record.msg = redact_message(record.getMessage())
            record.args = ()
        except Exception:
            pass

        # 结构化字段
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            record.extra_fields = sanitize(extra)  # type: ignore[attr-defined]

        return True


# ============================================================
# 格式化
# ============================================================


class JsonFormatter(logging.Formatter):
    """单行 JSON 输出，便于日志系统解析。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", None) or "-",
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)

        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """人类可读格式，本地开发用。"""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        request_id = getattr(record, "request_id", None)
        if request_id and request_id != "-":
            return f"[{request_id[:8]}] {base}"
        return base


# ============================================================
# 配置入口
# ============================================================


def setup_logging(level: str = "INFO", as_json: bool = True, force_info: bool = False) -> None:
    """初始化日志。

    :param level: 日志级别
    :param as_json: True 输出 JSON（生产/容器），False 输出可读文本（本地）
    :param force_info: 强制不低于 INFO。生产环境应传 True，避免 DEBUG 泄露
    """
    resolved_level = level.upper()
    if force_info and resolved_level in ("DEBUG", "NOTSET"):
        resolved_level = "INFO"

    handler = logging.StreamHandler(sys.stdout)
    formatter: logging.Formatter
    if as_json:
        formatter = JsonFormatter()
    else:
        formatter = TextFormatter("%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
    handler.setFormatter(formatter)

    # 顺序重要：先补 request_id，再脱敏
    handler.addFilter(RequestIdFilter())
    handler.addFilter(RedactionFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(resolved_level)

    # uvicorn 自带 handler 会导致重复输出与脱敏失效，统一交给 root
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # SQLAlchemy 的 DEBUG 会打印全部 SQL 与绑定参数（可能含手机号、密码哈希），
    # 因此无论什么环境都固定为 WARNING；排查 SQL 时需显式临时调低
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """统一获取 logger 的入口。"""
    return logging.getLogger(name)
