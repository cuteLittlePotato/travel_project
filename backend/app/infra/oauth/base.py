"""第三方登录的公共抽象。

三个服务商的协议差异很大（微信是 JSON、支付宝是表单签名、微博是表单），
但业务只需要两个东西：``openid``（唯一标识）和可选的 ``union_id`` / 昵称、头像。

因此抽象成 ``OAuthProvider``，子类只实现 ``_exchange_code()``。

**当前状态（M01-T07）**：服务商凭证尚未申请，三个实现都是「占位」——
``enabled=False`` 时抛 ``OAuthNotConfiguredError``，提示运维配置。
业务逻辑与测试通过 Mock 覆盖，真实对接时只改 ``_exchange_code()``。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.config import settings
from app.core.exceptions import BusinessError
from app.modules.account.constants import BindingProvider


class OAuthError(BusinessError):
    """第三方登录失败。

    与 ``SmsUnavailableError`` 等不同，这里用 400 而非 503——
    绝大多数失败是「授权码无效」这类客户端问题。
    """

    def __init__(self, message: str = "第三方登录失败") -> None:
        super().__init__(10002, message, http_status=400)


class OAuthNotConfiguredError(OAuthError):
    """服务商未配置（AppID/AppSecret 为空）。"""

    def __init__(self, provider: str) -> None:
        super().__init__(f"{provider} 登录暂未开放")


class OAuthCodeInvalidError(OAuthError):
    """授权码无效或已过期。"""

    def __init__(self, provider: str) -> None:
        super().__init__(f"{provider} 授权码无效或已过期，请重新授权")


class OAuthUnavailableError(OAuthError):
    """第三方服务不可达。"""

    def __init__(self, provider: str, detail: str = "") -> None:
        super().__init__(f"{provider} 服务暂不可用" + (f"：{detail}" if detail else ""))


@dataclass(frozen=True, slots=True)
class OAuthUserInfo:
    """第三方返回的用户信息。

    :param provider_uid: 唯一标识。微信是 ``openid``，支付宝是 ``user_id``，微博是 ``uid``
    :param union_id: 微信开放平台的跨应用唯一标识（可选）。
                     本项目只有单应用，暂不使用；保留字段供后续接入小程序时使用
    :param nickname: 第三方昵称（可选，用于新用户默认昵称）
    :param avatar_url: 头像（可选）
    :param raw: 原始响应，便于排查
    """

    provider_uid: str
    union_id: str | None = None
    nickname: str | None = None
    avatar_url: str | None = None
    raw: dict | None = None


class OAuthProvider(ABC):
    """第三方登录服务商基类。"""

    #: 对应的 ``BindingProvider`` 枚举值
    provider: BindingProvider

    #: 展示名称，用于错误提示
    display_name: str

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """是否已配置 AppID / AppSecret。"""

    @abstractmethod
    async def _exchange_code(self, code: str) -> OAuthUserInfo:
        """用授权码换取用户信息。子类实现具体的协议。"""

    async def exchange_code(self, code: str) -> OAuthUserInfo:
        """统一入口：配置检查 + 调用子类实现 + 异常归一。

        子类抛出的任何异常在这里转成 ``OAuthError`` 的具体子类，
        业务层只需捕获 ``OAuthError``。
        """
        if not self.enabled:
            raise OAuthNotConfiguredError(self.display_name)

        if not code or not code.strip():
            raise OAuthCodeInvalidError(self.display_name)

        try:
            info = await self._exchange_code(code.strip())
        except OAuthError:
            raise
        except Exception as exc:
            raise OAuthUnavailableError(self.display_name, str(exc)[:200]) from exc

        if not info.provider_uid:
            raise OAuthCodeInvalidError(self.display_name)

        return info


class MockableOAuthProvider(OAuthProvider):
    """可 Mock 的基类，供测试与开发环境使用。

    真实实现继承本类，只需覆盖 ``_exchange_code``。
    测试中通过 ``set_mock_response()`` 注入固定返回值，无需真实网络。
    """

    def __init__(self) -> None:
        self._mock_response: OAuthUserInfo | None = None
        self._mock_error: Exception | None = None

    @property
    def enabled(self) -> bool:
        """开发/测试环境视为已启用，便于本地联调。"""
        return True

    def set_mock_response(self, info: OAuthUserInfo) -> None:
        self._mock_response = info

    def set_mock_error(self, error: Exception) -> None:
        self._mock_error = error

    def clear_mock(self) -> None:
        self._mock_response = None
        self._mock_error = None

    async def _exchange_code(self, code: str) -> OAuthUserInfo:
        if self._mock_error is not None:
            raise self._mock_error
        if self._mock_response is not None:
            return self._mock_response
        return await self._real_exchange(code)

    async def _real_exchange(self, code: str) -> OAuthUserInfo:
        """真实对接。默认实现提示未接入。"""
        raise OAuthNotConfiguredError(self.display_name)


def is_production() -> bool:
    return settings.app_env == "production"
