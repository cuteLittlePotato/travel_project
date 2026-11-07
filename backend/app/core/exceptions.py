"""业务异常与错误码。

错误码按 API 设计 §1.7 分段，任何新增错误码必须归入已有分段。
"""

from __future__ import annotations

from typing import Any


class ErrorCode:
    """通用错误码。模块专属错误码在各业务模块的 constants.py 中定义。"""

    SUCCESS = 0

    # 10000-10999 通用
    VALIDATION_FAILED = 10001
    INTERNAL_ERROR = 10002
    RATE_LIMITED = 10003
    NOT_FOUND = 10004

    # 11000-11999 认证与用户（M01）
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

    # 25000-25999 系统管理（M15）
    PERMISSION_DENIED = 25001


#: 业务码 -> HTTP 状态码。未列出的业务码默认 400。
ERROR_HTTP_STATUS: dict[int, int] = {
    ErrorCode.VALIDATION_FAILED: 400,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.NOT_FOUND: 404,
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
    ErrorCode.SAME_PASSWORD: 400,
    ErrorCode.PERMISSION_DENIED: 403,
}


class BusinessError(Exception):
    """业务异常基类。

    业务代码只抛这个异常，由全局异常处理器转换为统一响应；
    禁止在业务层直接抛 ``HTTPException``。
    """

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
        self.http_status = http_status or ERROR_HTTP_STATUS.get(code, 400)


class ValidationError(BusinessError):
    """参数校验失败，携带字段级错误详情。"""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__(
            ErrorCode.VALIDATION_FAILED,
            "参数校验失败",
            data={"errors": errors},
        )


class UnauthorizedError(BusinessError):
    def __init__(self, message: str = "未登录或登录已过期") -> None:
        super().__init__(ErrorCode.UNAUTHORIZED, message)


class PermissionDeniedError(BusinessError):
    def __init__(self, message: str = "无权限访问") -> None:
        super().__init__(ErrorCode.PERMISSION_DENIED, message)


class NotFoundError(BusinessError):
    def __init__(self, message: str = "资源不存在", code: int = ErrorCode.NOT_FOUND) -> None:
        super().__init__(code, message)
