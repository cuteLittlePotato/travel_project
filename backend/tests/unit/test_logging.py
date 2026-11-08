"""M0-T11 日志与请求追踪的测试。

覆盖 DoD：
    1. 每条日志含 request_id，同一请求的日志可串联
    2. 请求日志不含密码、Token 明文
    3. 日志级别可通过配置调整，生产环境不输出 DEBUG
"""

from __future__ import annotations

import json
import logging
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.middleware.logging import SLOW_REQUEST_THRESHOLD_MS, RequestContextMiddleware
from app.core.context import (
    get_request_id,
    new_request_id,
    reset_request_id,
    set_request_id,
)
from app.core.logging import (
    REDACTED,
    JsonFormatter,
    RedactionFilter,
    RequestIdFilter,
    TextFormatter,
    redact_message,
    redact_value,
    sanitize,
    setup_logging,
)

# ============================================================
# DoD 1：request_id 贯穿
# ============================================================


class TestRequestIdContext:
    def test_default_is_dash(self) -> None:
        assert get_request_id() == "-"

    def test_set_and_reset(self) -> None:
        token = set_request_id("req-abc")
        try:
            assert get_request_id() == "req-abc"
        finally:
            reset_request_id(token)
        assert get_request_id() == "-"

    def test_new_request_id_is_hex32(self) -> None:
        rid = new_request_id()
        assert len(rid) == 32
        assert re.fullmatch(r"[0-9a-f]{32}", rid)

    def test_reset_with_invalid_token_does_not_raise(self) -> None:
        """并发场景下 token 可能已被其他上下文重置，不能因此崩溃。"""
        reset_request_id(object())


class TestRequestIdFilter:
    def test_injects_request_id_into_record(self) -> None:
        token = set_request_id("req-xyz")
        try:
            record = logging.LogRecord(
                "test", logging.INFO, __file__, 1, "msg", (), None
            )
            RequestIdFilter().filter(record)
            assert record.request_id == "req-xyz"
        finally:
            reset_request_id(token)

    def test_logs_from_same_request_share_id(self) -> None:
        """同一次请求内的多条日志必须带同一个 request_id。"""
        token = set_request_id("req-shared")
        records: list[logging.LogRecord] = []

        class _Collector(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Collector()
        handler.addFilter(RequestIdFilter())
        logger = logging.getLogger("test.same_request")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            logger.info("第一条")
            logger.info("第二条")
            logger.info("第三条")
        finally:
            logger.removeHandler(handler)
            reset_request_id(token)

        assert len(records) == 3
        assert {r.request_id for r in records} == {"req-shared"}


class TestMiddlewareRequestId:
    @pytest.fixture
    def app(self) -> FastAPI:
        app = FastAPI()
        app.add_middleware(RequestContextMiddleware)

        @app.get("/ping")
        async def ping() -> dict[str, str]:
            return {"request_id": get_request_id()}

        return app

    @pytest.fixture
    def client(self, app: FastAPI) -> TestClient:
        return TestClient(app)

    def test_response_has_request_id_header(self, client: TestClient) -> None:
        response = client.get("/ping")
        assert response.status_code == 200
        assert "X-Request-ID" in response.headers

    def test_client_supplied_id_is_preserved(self, client: TestClient) -> None:
        """上游（Nginx / 前端）传入的 ID 应透传，便于跨服务追踪。"""
        response = client.get("/ping", headers={"X-Request-ID": "upstream-id-123"})
        assert response.headers["X-Request-ID"] == "upstream-id-123"

    def test_request_id_visible_inside_handler(self, client: TestClient) -> None:
        """处理函数内能取到同一个 ID，说明 ContextVar 正确传递。"""
        response = client.get("/ping", headers={"X-Request-ID": "in-handler"})
        assert response.json()["request_id"] == "in-handler"


# ============================================================
# DoD 2：敏感信息脱敏
# ============================================================


class TestRedaction:
    @pytest.mark.parametrize(
        "key",
        ["password", "Password", "user_password", "access_token", "api_key",
         "secret", "credential", "authorization", "cookie", "session_id"],
    )
    def test_sensitive_keys_redacted(self, key: str) -> None:
        assert redact_value(key, "真实值") == REDACTED

    @pytest.mark.parametrize("key", ["username", "page", "keyword", "status"])
    def test_normal_keys_pass_through(self, key: str) -> None:
        assert redact_value(key, "值") == "值"

    @pytest.mark.parametrize(
        ("message", "leaked"),
        [
            ("login password=Secret123", "Secret123"),
            ("token: abc123def456", "abc123def456"),
            ('{"api_key": "sk-1234567890"}', "sk-1234567890"),
            ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9", "eyJhbGciOiJIUzI1NiJ9"),
        ],
    )
    def test_message_body_redacted(self, message: str, leaked: str) -> None:
        """业务代码把密码拼进 message 时也要拦截。"""
        assert leaked not in redact_message(message)
        assert REDACTED in redact_message(message)

    def test_normal_message_unchanged(self) -> None:
        message = "用户登录成功 user_id=abc"
        assert redact_message(message) == message

    def test_nested_structure_redacted(self) -> None:
        payload = {
            "username": "alice",
            "password": "p@ss",
            "nested": {"access_token": "tok", "page": 1},
            "items": [{"api_key": "k1"}],
        }
        cleaned = sanitize(payload)

        assert cleaned["username"] == "alice"
        assert cleaned["password"] == REDACTED
        assert cleaned["nested"]["access_token"] == REDACTED
        assert cleaned["nested"]["page"] == 1
        assert cleaned["items"][0]["api_key"] == REDACTED

    def test_deep_nesting_is_capped(self) -> None:
        """超深结构截断，避免循环引用拖死日志。"""
        payload: dict = {}
        cursor = payload
        for _ in range(20):
            cursor["next"] = {}
            cursor = cursor["next"]
        assert sanitize(payload) is not None  # 不抛异常即通过

    def test_redaction_filter_cleans_extra_fields(self) -> None:
        record = logging.LogRecord(
            "test", logging.INFO, __file__, 1, "msg", (), None
        )
        record.extra_fields = {"password": "p@ss", "user": "alice"}
        RedactionFilter().filter(record)
        assert record.extra_fields["password"] == REDACTED
        assert record.extra_fields["user"] == "alice"

    def test_redaction_filter_cleans_message(self) -> None:
        record = logging.LogRecord(
            "test", logging.INFO, __file__, 1, "login password=abc123", (), None
        )
        RedactionFilter().filter(record)
        assert "abc123" not in record.getMessage()

    def test_json_output_contains_no_secret(self) -> None:
        """端到端：格式化后的 JSON 中不应出现明文密码。"""
        record = logging.LogRecord(
            "test", logging.INFO, __file__, 1, "login password=TopSecret!", (), None
        )
        record.request_id = "r1"
        record.extra_fields = {"access_token": "tok-abc-123", "user": "alice"}
        RedactionFilter().filter(record)

        output = JsonFormatter().format(record)
        assert "TopSecret!" not in output
        assert "tok-abc-123" not in output
        assert "alice" in output


# ============================================================
# DoD 3：日志级别可配置，生产不输出 DEBUG
# ============================================================


class TestLogLevelConfiguration:
    def test_level_from_config(self) -> None:
        setup_logging("WARNING", as_json=True)
        assert logging.getLogger().level == logging.WARNING

    def test_debug_allowed_in_dev(self) -> None:
        setup_logging("DEBUG", as_json=True, force_info=False)
        assert logging.getLogger().level == logging.DEBUG

    def test_debug_forced_to_info_in_production(self) -> None:
        """DoD：生产环境不输出 DEBUG。"""
        setup_logging("DEBUG", as_json=True, force_info=True)
        assert logging.getLogger().level == logging.INFO

    def test_notset_forced_to_info_in_production(self) -> None:
        setup_logging("NOTSET", as_json=True, force_info=True)
        assert logging.getLogger().level == logging.INFO

    def test_uvicorn_loggers_propagate_to_root(self) -> None:
        """uvicorn 自带 handler 会导致脱敏失效，必须清空并交给 root。"""
        setup_logging("INFO", as_json=True)
        for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
            logger = logging.getLogger(name)
            assert logger.handlers == []
            assert logger.propagate is True

    def test_sqlalchemy_sql_not_logged(self) -> None:
        """SQL 参数可能含敏感数据，不能以 DEBUG 级别输出。"""
        setup_logging("DEBUG", as_json=False)
        assert logging.getLogger("sqlalchemy.engine").level >= logging.WARNING


# ============================================================
# 格式化器
# ============================================================


class TestFormatters:
    def _record(self, message: str = "hello") -> logging.LogRecord:
        record = logging.LogRecord(
            "app.test", logging.INFO, __file__, 1, message, (), None
        )
        record.request_id = "abcd1234efgh"
        return record

    def test_json_formatter_outputs_valid_json(self) -> None:
        output = JsonFormatter().format(self._record())
        payload = json.loads(output)
        assert payload["message"] == "hello"
        assert payload["level"] == "INFO"
        assert payload["request_id"] == "abcd1234efgh"

    def test_json_formatter_single_line(self) -> None:
        """必须是单行，否则日志采集器无法按行解析。"""
        output = JsonFormatter().format(self._record("多行\n消息"))
        assert "\n" not in output

    def test_json_formatter_includes_exception(self) -> None:
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = self._record()
            record.exc_info = sys.exc_info()
            output = JsonFormatter().format(record)
            assert "ValueError" in output
            assert "boom" in output

    def test_text_formatter_shows_short_request_id(self) -> None:
        output = TextFormatter("%(message)s").format(self._record())
        assert "abcd1234" in output
        assert "hello" in output

    def test_text_formatter_skips_empty_request_id(self) -> None:
        record = self._record()
        record.request_id = "-"
        assert TextFormatter("%(message)s").format(record) == "hello"


# ============================================================
# 请求日志（边界）
# ============================================================


class TestAccessLog:
    def test_health_path_not_logged(self) -> None:
        """探针高频调用，不应刷屏。"""
        from app.api.middleware.logging import SKIP_PATHS

        assert "/api/health" in SKIP_PATHS

    def test_body_content_not_logged(self) -> None:
        """边界：大请求体不打印全文，只记 content-length。"""
        import inspect

        source = inspect.getsource(
            __import__(
                "app.api.middleware.logging", fromlist=["RequestContextMiddleware"]
            ).RequestContextMiddleware._log_request
        )
        assert "content_length" in source
        # 不应出现读取请求体的调用
        assert "await request.body()" not in source
        assert "request.body()" not in source

    def test_slow_threshold_defined(self) -> None:
        assert SLOW_REQUEST_THRESHOLD_MS > 0


# ============================================================
# 与 Langfuse 的职责分离
# ============================================================


class TestSeparationFromLangfuse:
    def test_logging_module_does_not_import_langfuse(self) -> None:
        """可观测性分层：Langfuse 管 AI 追踪，业务日志不应耦合它。

        只检查 import 语句——模块文档字符串里会解释「为什么不用 Langfuse」，
        按全文匹配会误判。
        """
        from pathlib import Path

        module = Path(__file__).resolve().parents[2] / "app" / "core" / "logging.py"
        code_lines = [
            line
            for line in module.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith(("#", "*", '"""', "'''"))
        ]
        code = "\n".join(code_lines).lower()

        assert "import langfuse" not in code
        assert "from langfuse" not in code
