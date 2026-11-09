"""第三方登录服务商封装。

统一入口 ``get_provider()``，业务层不需要知道具体实现。
"""

from __future__ import annotations

from app.infra.oauth.alipay import alipay_provider
from app.infra.oauth.base import (
    MockableOAuthProvider,
    OAuthCodeInvalidError,
    OAuthError,
    OAuthNotConfiguredError,
    OAuthProvider,
    OAuthUnavailableError,
    OAuthUserInfo,
)
from app.infra.oauth.wechat import wechat_provider
from app.infra.oauth.weibo import weibo_provider
from app.modules.account.constants import BindingProvider

#: 服务商注册表。新增服务商时在此登记即可
_PROVIDERS: dict[BindingProvider, OAuthProvider] = {
    BindingProvider.WECHAT: wechat_provider,
    BindingProvider.ALIPAY: alipay_provider,
    BindingProvider.WEIBO: weibo_provider,
}


def get_provider(provider: str | BindingProvider) -> OAuthProvider:
    """按名称取服务商实现。

    手机号/邮箱不是 OAuth 服务商，传进来会抛 ``OAuthError``。
    """
    try:
        key = BindingProvider(provider) if isinstance(provider, str) else provider
    except ValueError as exc:
        raise OAuthError(f"不支持的登录方式: {provider}") from exc

    instance = _PROVIDERS.get(key)
    if instance is None:
        raise OAuthError(f"{key.value} 不是第三方登录方式")
    return instance


def supported_providers() -> list[str]:
    """当前支持的第三方登录方式。"""
    return [p.value for p in _PROVIDERS]


__all__ = [
    "MockableOAuthProvider",
    "OAuthCodeInvalidError",
    "OAuthError",
    "OAuthNotConfiguredError",
    "OAuthProvider",
    "OAuthUnavailableError",
    "OAuthUserInfo",
    "alipay_provider",
    "get_provider",
    "supported_providers",
    "wechat_provider",
    "weibo_provider",
]
