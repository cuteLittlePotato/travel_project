"""业务异常与错误码。

错误码分段见 API 设计 §1.7。**任何新增错误码必须落在已定义的分段内**，
由 ``validate_error_code()`` 校验，模块定义常量时应在测试中调用它，
避免出现「各模块随手编号、码段逐渐失控」的情况。

职责边界：
- 本文件定义**通用错误码**与**语义化异常基类**。
- 各业务模块在 ``modules/<module>/constants.py`` 定义自己的错误码常量，
  并继承 ``NotFoundError`` / ``ConflictError`` 等基类以获得正确的 HTTP 状态码。
"""

from __future__ import annotations

from typing import Any, Final


class ErrorCodeSegment:
    """错误码分段（API 设计 §1.7）。"""

    SUCCESS: Final = (0, 0)
    COMMON: Final = (10000, 10999)  # 通用：参数、限流、系统
    ACCOUNT: Final = (11000, 11999)  # M01 认证与用户
    ATTRACTION: Final = (12000, 12999)  # M02 景点内容
    CHAT: Final = (13000, 13999)  # M03 对话交互
    TRIP_PLAN: Final = (14000, 14999)  # M04 旅游计划
    FOOTPRINT: Final = (15000, 15999)  # M05 足迹
    KNOWLEDGE_BASE: Final = (19000, 19999)  # M09 知识库
    KNOWLEDGE_GRAPH: Final = (20000, 20999)  # M10 知识图谱
    CATALOG: Final = (21000, 21999)  # M11 基础数据
    MODEL_GATEWAY: Final = (22000, 22999)  # M12 模型管理
    QUOTA: Final = (23000, 23999)  # M13 额度
    USER_OPS: Final = (24000, 24999)  # M14 用户运营
    SYSTEM: Final = (25000, 25999)  # M15 系统管理
    DASHBOARD: Final = (26000, 26999)  # M16 数据看板

    @classmethod
    def all_ranges(cls) -> list[tuple[int, int]]:
        return [
            value
            for name, value in vars(cls).items()
            if not name.startswith("_") and isinstance(value, tuple)
        ]


def validate_error_code(code: int) -> int:
    """校验错误码落在合法分段内，返回原值以便链式使用。

    在模块常量定义处的测试里调用，可在编码阶段拦住乱编号。
    """
    if code == 0:
        return code
    for low, high in ErrorCodeSegment.all_ranges():
        if low <= code <= high:
            return code
    raise ValueError(f"错误码 {code} 不属于任何已定义分段，请对照 API 设计 §1.7")


class ErrorCode:
    """通用错误码（10000-10999）与已确认的模块错误码。

    模块专属错误码在各自 ``constants.py`` 中定义，不在此堆积。
    """

    SUCCESS = 0

    # ---------- 10000-10999 通用 ----------
    VALIDATION_FAILED = 10001
    INTERNAL_ERROR = 10002
    RATE_LIMITED = 10003
    ROUTE_NOT_FOUND = 10004

    # ---------- 11000-11999 认证与用户（M01） ----------
    UNAUTHORIZED = 11001
    ACCOUNT_BANNED = 11002
    DUPLICATE_TARGET = 11003
    INVALID_VERIFY_CODE = 11004
    ACCOUNT_NOT_FOUND = 11005
    INVALID_CREDENTIAL = 11006
    ACCOUNT_DELETED = 11007
    TOO_MANY_LOGIN_ATTEMPTS = 11008
    OAUTH_ALREADY_BOUND = 11009
    REFRESH_TOKEN_REVOKED = 11010
    SAME_PASSWORD = 11011
    NOTIFICATION_NOT_FOUND = 11012
    #: 账号存在但从未设置密码（验证码注册 / 第三方登录创建）
    PASSWORD_NOT_SET = 11013

    # ---------- 25000-25999 系统管理（M15） ----------
    PERMISSION_DENIED = 25001


#: 错误码 -> HTTP 状态码。仅登记常用码；未登记的按异常类的默认状态码处理。
ERROR_HTTP_STATUS: dict[int, int] = {
    ErrorCode.VALIDATION_FAILED: 400,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.ROUTE_NOT_FOUND: 404,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.ACCOUNT_BANNED: 403,
    ErrorCode.DUPLICATE_TARGET: 409,
    ErrorCode.INVALID_VERIFY_CODE: 400,
    ErrorCode.ACCOUNT_NOT_FOUND: 404,
    ErrorCode.INVALID_CREDENTIAL: 401,
    ErrorCode.ACCOUNT_DELETED: 403,
    ErrorCode.TOO_MANY_LOGIN_ATTEMPTS: 429,
    ErrorCode.OAUTH_ALREADY_BOUND: 409,
    ErrorCode.REFRESH_TOKEN_REVOKED: 401,
    ErrorCode.PASSWORD_NOT_SET: 401,
    ErrorCode.SAME_PASSWORD: 400,
    ErrorCode.PERMISSION_DENIED: 403,
}


class BusinessError(Exception):
    """业务异常基类。

    业务代码只抛这个异常，由全局异常处理器转换为统一响应；
    **禁止在业务层直接抛 ``HTTPException``**（DoD 规范检查项）。

    状态码解析优先级：显式 ``http_status`` > ``ERROR_HTTP_STATUS`` 映射 >
    类属性 ``default_http_status``（默认 400）。
    """

    #: 子类的默认 HTTP 状态码，供未登记在映射表中的码段使用
    default_http_status: int = 400

    def __init__(
        self,
        code: int,
        message: str,
        *,
        data: Any = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data
        self.http_status = (
            http_status
            or ERROR_HTTP_STATUS.get(code)
            or self.default_http_status
        )


# ============================================================
# 语义化异常基类
# 模块继承这些类即可获得正确的 HTTP 状态码，无需关心映射表
# ============================================================


class ValidationError(BusinessError):
    """参数校验失败，携带字段级错误详情。"""

    default_http_status = 400

    def __init__(self, errors: list[dict[str, str]], message: str = "参数校验失败") -> None:
        super().__init__(
            ErrorCode.VALIDATION_FAILED,
            message,
            data={"errors": errors},
            http_status=400,
        )


class UnauthorizedError(BusinessError):
    default_http_status = 401

    def __init__(self, message: str = "未登录或登录已过期") -> None:
        super().__init__(ErrorCode.UNAUTHORIZED, message)


class ForbiddenError(BusinessError):
    default_http_status = 403

    def __init__(self, message: str = "无权访问") -> None:
        super().__init__(ErrorCode.PERMISSION_DENIED, message)


class NotFoundError(BusinessError):
    """资源不存在。

    模块应传入自己码段内的错误码，例如 M09 用 ``19001``。
    HTTP 状态码固定为 404，与 API §1.3 映射表一致。
    """

    default_http_status = 404

    def __init__(
        self,
        message: str = "资源不存在",
        *,
        code: int = ErrorCode.ROUTE_NOT_FOUND,
        data: Any = None,
    ) -> None:
        super().__init__(code, message, data=data, http_status=404)


class ConflictError(BusinessError):
    """资源冲突（唯一约束、状态冲突等）。"""

    default_http_status = 409

    def __init__(self, code: int, message: str, *, data: Any = None) -> None:
        super().__init__(code, message, data=data, http_status=409)


class RateLimitedError(BusinessError):
    default_http_status = 429

    def __init__(self, message: str = "请求过于频繁", *, code: int = ErrorCode.RATE_LIMITED) -> None:
        super().__init__(code, message, http_status=429)
