"""M0-T03 统一响应与全局异常处理的测试。

覆盖 DoD 三项：
    1. 参数校验失败 -> HTTP 400 + code=10001 + data.errors[].field/reason
    2. 未捕获异常 -> HTTP 500 + code=10002，不泄露堆栈
    3. 业务代码不直接抛 HTTPException（静态检查）
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.error_handlers import register_exception_handlers
from app.core.exceptions import (
    BusinessError,
    ConflictError,
    ErrorCode,
    ErrorCodeSegment,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
    ValidationError,
    validate_error_code,
)

# ============================================================
# 测试用的最小应用
# ============================================================


class _Payload(BaseModel):
    phone: str = Field(min_length=11, max_length=11, pattern=r"^\d{11}$")
    age: int = Field(ge=18)


class _Nested(BaseModel):
    city: str = Field(min_length=1)


class _NestedPayload(BaseModel):
    address: _Nested


@pytest.fixture
def probe_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/validate")
    async def validate(payload: _Payload) -> dict[str, object]:
        return {"code": 0, "message": "ok", "data": payload.model_dump()}

    @app.post("/validate-nested")
    async def validate_nested(payload: _NestedPayload) -> dict[str, object]:
        return {"code": 0, "message": "ok", "data": {}}

    @app.get("/business")
    async def business() -> None:
        raise ValidationError([{"field": "phone", "reason": "手机号格式不正确"}])

    @app.get("/not-found")
    async def not_found() -> None:
        raise NotFoundError("景点不存在", code=12001)

    @app.get("/conflict")
    async def conflict() -> None:
        raise ConflictError(11003, "该手机号已注册")

    @app.get("/forbidden")
    async def forbidden() -> None:
        raise ForbiddenError("无权操作用户数据")

    @app.get("/unauthorized")
    async def unauthorized() -> None:
        raise UnauthorizedError()

    @app.get("/rate-limited")
    async def rate_limited() -> None:
        raise RateLimitedError("今日额度已用完", code=23001)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("数据库密码是 secret123")

    @app.get("/http-404")
    async def http_404() -> None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="资源不存在")

    return app


@pytest.fixture
def probe(probe_app: FastAPI) -> TestClient:
    return TestClient(probe_app, raise_server_exceptions=False)


# ============================================================
# DoD 1：参数校验失败
# ============================================================


class TestValidationErrorResponse:
    def test_returns_400_and_code_10001(self, probe: TestClient) -> None:
        response = probe.post("/validate", json={"phone": "123", "age": 10})
        assert response.status_code == 400

        body = response.json()
        assert body["code"] == ErrorCode.VALIDATION_FAILED == 10001
        assert body["message"] == "参数校验失败"
        assert isinstance(body["data"]["errors"], list)
        assert body["data"]["errors"], "必须返回字段级错误详情"

    def test_errors_contain_field_and_reason(self, probe: TestClient) -> None:
        response = probe.post("/validate", json={"phone": "123", "age": 10})
        errors = response.json()["data"]["errors"]

        for item in errors:
            assert set(item) == {"field", "reason"}, "每项必须且只含 field/reason"
            assert item["field"]
            assert item["reason"]

        fields = {item["field"] for item in errors}
        assert fields == {"phone", "age"}

    def test_field_name_excludes_location_prefix(self, probe: TestClient) -> None:
        """body/query 等位置前缀必须剔除，前端直接用 field 定位表单项。"""
        response = probe.post("/validate", json={"phone": "13800000000", "age": 10})
        fields = {item["field"] for item in response.json()["data"]["errors"]}
        assert fields == {"age"}
        assert not any(field.startswith("body.") for field in fields)

    def test_nested_field_uses_dot_notation(self, probe: TestClient) -> None:
        response = probe.post("/validate-nested", json={"address": {"city": ""}})
        fields = {item["field"] for item in response.json()["data"]["errors"]}
        assert "address.city" in fields

    def test_reason_is_chinese(self, probe: TestClient) -> None:
        """错误原因面向用户展示，不能直接透出 Pydantic 英文原文。"""
        response = probe.post("/validate", json={"phone": "123", "age": 10})
        reasons = " ".join(item["reason"] for item in response.json()["data"]["errors"])
        assert "String should" not in reasons
        assert "greater than" not in reasons

    def test_missing_body_is_reported(self, probe: TestClient) -> None:
        response = probe.post("/validate", json={})
        assert response.status_code == 400
        errors = response.json()["data"]["errors"]
        assert {item["field"] for item in errors} == {"phone", "age"}
        assert all(item["reason"] == "该字段为必填项" for item in errors)


# ============================================================
# DoD 2：未捕获异常不泄露内部信息
# ============================================================


class TestUnhandledException:
    def test_returns_500_and_code_10002(self, probe: TestClient) -> None:
        response = probe.get("/boom")
        assert response.status_code == 500
        assert response.json() == {
            "code": ErrorCode.INTERNAL_ERROR,
            "message": "服务端内部错误",
            "data": None,
        }

    def test_does_not_leak_stacktrace(self, probe: TestClient) -> None:
        body = probe.get("/boom").text
        assert "Traceback" not in body
        assert "RuntimeError" not in body

    def test_does_not_leak_internal_message(self, probe: TestClient) -> None:
        """异常原文可能含密钥、SQL、路径，一律不得出现在响应里。"""
        body = probe.get("/boom").text
        assert "secret123" not in body
        assert "数据库密码" not in body


# ============================================================
# 业务异常 -> HTTP 状态码映射（API §1.3）
# ============================================================


class TestBusinessErrorMapping:
    @pytest.mark.parametrize(
        ("path", "expected_status", "expected_code"),
        [
            ("/business", 400, 10001),
            ("/not-found", 404, 12001),
            ("/conflict", 409, 11003),
            ("/forbidden", 403, 25001),
            ("/unauthorized", 401, 11001),
            ("/rate-limited", 429, 23001),
        ],
    )
    def test_status_matches_api_spec(
        self, probe: TestClient, path: str, expected_status: int, expected_code: int
    ) -> None:
        response = probe.get(path)
        assert response.status_code == expected_status
        assert response.json()["code"] == expected_code

    def test_business_message_is_preserved(self, probe: TestClient) -> None:
        response = probe.get("/not-found")
        assert response.json()["message"] == "景点不存在"

    def test_not_uniform_200(self, probe: TestClient) -> None:
        """DoD：不得统一返回 200，HTTP 状态码必须语义化。"""
        for path in ("/business", "/not-found", "/conflict", "/forbidden", "/unauthorized"):
            assert probe.get(path).status_code != 200

    def test_framework_http_exception_uses_unified_shape(self, probe: TestClient) -> None:
        response = probe.get("/http-404")
        assert response.status_code == 404
        body = response.json()
        assert set(body) == {"code", "message", "data"}
        assert body["code"] == ErrorCode.ROUTE_NOT_FOUND
        assert body["message"] == "资源不存在", "业务 detail 应原样保留"


class TestRealApplicationStack:
    """在真实应用（含中间件栈）上验证，防止 BaseHTTPMiddleware 吞掉异常处理器。"""

    @pytest.fixture
    def real_client(self) -> TestClient:
        from app.main import create_app

        app = create_app()

        @app.get("/__test_boom")
        async def _boom() -> None:
            raise RuntimeError("内部细节不应泄露")

        return TestClient(app, raise_server_exceptions=False)

    def test_unhandled_exception_survives_middleware(self, real_client: TestClient) -> None:
        response = real_client.get("/__test_boom")
        assert response.status_code == 500
        assert response.json()["code"] == ErrorCode.INTERNAL_ERROR
        assert "内部细节不应泄露" not in response.text

    def test_unknown_route_has_unified_shape(self, real_client: TestClient) -> None:
        response = real_client.get("/api/v1/definitely-not-exists")
        assert response.status_code == 404
        body = response.json()
        assert body["code"] == ErrorCode.ROUTE_NOT_FOUND
        assert body["message"] == "接口不存在"

    def test_health_still_works(self, real_client: TestClient) -> None:
        assert real_client.get("/api/health").json()["code"] == 0


# ============================================================
# 错误码分段约束
# ============================================================


class TestErrorCodeSegments:
    def test_segments_cover_api_spec(self) -> None:
        """API §1.7 定义的全部码段都应存在。"""
        expected = [
            (0, 0),
            (10000, 10999),
            (11000, 11999),
            (12000, 12999),
            (13000, 13999),
            (14000, 14999),
            (15000, 15999),
            (19000, 19999),
            (20000, 20999),
            (21000, 21999),
            (22000, 22999),
            (23000, 23999),
            (24000, 24999),
            (25000, 25999),
            (26000, 26999),
        ]
        assert sorted(ErrorCodeSegment.all_ranges()) == sorted(expected)

    @pytest.mark.parametrize("code", [10001, 11001, 12001, 19001, 23001, 26001])
    def test_valid_codes_pass(self, code: int) -> None:
        assert validate_error_code(code) == code

    @pytest.mark.parametrize("code", [1, 9999, 16000, 18000, 27000])
    def test_codes_outside_segments_rejected(self, code: int) -> None:
        """16000-18999 与 27000+ 在 API §1.7 中未定义，应拒绝。"""
        with pytest.raises(ValueError, match="不属于任何已定义分段"):
            validate_error_code(code)

    def test_module_error_codes_are_within_their_segment(self) -> None:
        """已定义的模块错误码必须落在对应分段。"""
        from app.core.exceptions import ErrorCode as EC

        account_codes = [
            EC.UNAUTHORIZED,
            EC.ACCOUNT_BANNED,
            EC.DUPLICATE_TARGET,
            EC.INVALID_VERIFY_CODE,
            EC.ACCOUNT_NOT_FOUND,
            EC.INVALID_CREDENTIAL,
            EC.ACCOUNT_DELETED,
            EC.TOO_MANY_LOGIN_ATTEMPTS,
            EC.OAUTH_ALREADY_BOUND,
            EC.REFRESH_TOKEN_REVOKED,
            EC.SAME_PASSWORD,
        ]
        for code in account_codes:
            assert 11000 <= code <= 11999, f"{code} 不在 M01 码段内"

        assert 25000 <= EC.PERMISSION_DENIED <= 25999


# ============================================================
# DoD 3：业务代码不直接抛 HTTPException
# ============================================================


class TestNoHttpExceptionInBusinessCode:
    def test_business_code_does_not_raise_http_exception(self) -> None:
        """DoD 规范检查：除 core/ 外，业务代码不得直接抛 HTTPException。"""
        app_dir = Path(__file__).resolve().parents[2] / "app"
        offenders: list[str] = []

        for path in app_dir.rglob("*.py"):
            if "core" in path.relative_to(app_dir).parts:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "HTTPException(" in line and not line.lstrip().startswith("#"):
                    offenders.append(f"{path.relative_to(app_dir)}:{lineno}")

        assert not offenders, f"业务代码直接抛了 HTTPException: {offenders}"


class TestResponseHelpers:
    def test_success_shape(self) -> None:
        from app.core.response import success

        assert success({"id": 1}) == {"code": 0, "message": "ok", "data": {"id": 1}}

    def test_success_without_data(self) -> None:
        from app.core.response import success

        assert success() == {"code": 0, "message": "ok", "data": None}

    def test_error_shape(self) -> None:
        from app.core.response import error

        assert error(11002, "账号已封禁") == {
            "code": 11002,
            "message": "账号已封禁",
            "data": None,
        }

    def test_validation_error_shape(self) -> None:
        from app.core.response import validation_error

        payload = validation_error([{"field": "phone", "reason": "格式不正确"}])
        assert payload["code"] == 10001
        assert payload["data"]["errors"][0]["field"] == "phone"


class TestBusinessErrorConstruction:
    def test_default_status_is_400(self) -> None:
        assert BusinessError(10999, "自定义错误").http_status == 400

    def test_explicit_status_wins(self) -> None:
        assert BusinessError(10999, "x", http_status=422).http_status == 422

    def test_mapped_code_uses_table(self) -> None:
        assert BusinessError(ErrorCode.RATE_LIMITED, "限流").http_status == 429
