"""支付宝登录。

协议（支付宝开放平台）：
    1. 前端引导跳转支付宝授权页
    2. 回调带 ``auth_code``
    3. 后端调 ``alipay.system.oauth.token`` 换 ``access_token`` + ``user_id``
    4. 可选调 ``alipay.user.info.share`` 拉用户信息

**协议特点**：支付宝用 RSA2 签名，不是简单的 Bearer。真实对接需要
``alipay-sdk-python`` 或自行实现签名。当前未接入。

真实对接时替换 ``_real_exchange()``，建议引入官方 SDK 处理签名与验签。
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.infra.oauth.base import MockableOAuthProvider, OAuthUserInfo
from app.modules.account.constants import BindingProvider

logger = logging.getLogger(__name__)


class AlipayOAuthProvider(MockableOAuthProvider):
    provider = BindingProvider.ALIPAY
    display_name = "支付宝"

    @property
    def enabled(self) -> bool:
        from app.infra.oauth.base import is_production

        if not is_production():
            return True
        return bool(settings.alipay_oauth_app_id and settings.alipay_oauth_app_secret)

    async def _real_exchange(self, code: str) -> OAuthUserInfo:
        """真实对接。

        TODO(凭证申请后): 用 ``alipay-sdk-python`` 实现。
        支付宝的 ``alipay.system.oauth.token`` 返回 ``user_id``（即 openid），
        需要 RSA2 签名，不适合用裸 httpx 手写。

        实现要点：
            1. 构造 ``grant_type=authorization_code`` + ``code``
            2. SDK 自动签名
            3. 从响应取 ``user_id`` / ``access_token``
            4. 可选调 ``alipay.user.info.share`` 取昵称头像
        """
        from app.infra.oauth.base import OAuthNotConfiguredError

        raise OAuthNotConfiguredError(self.display_name)


alipay_provider = AlipayOAuthProvider()
