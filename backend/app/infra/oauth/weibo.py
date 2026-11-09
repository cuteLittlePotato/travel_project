"""微博登录。

协议（微博开放平台）：
    1. 前端跳转 ``https://api.weibo.com/oauth2/authorize?...``
    2. 回调带 ``code``
    3. 后端 POST ``https://api.weibo.com/oauth2/access_token`` 换
       ``access_token`` + ``uid``
    4. GET ``https://api.weibo.com/2/users/show.json`` 拉用户信息

**与微信的差异**：微博用表单 POST 而非 GET 传参。

真实对接时替换 ``_real_exchange()``。
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings
from app.infra.oauth.base import MockableOAuthProvider, OAuthCodeInvalidError, OAuthUserInfo
from app.modules.account.constants import BindingProvider

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://api.weibo.com/oauth2/access_token"
_USERINFO_URL = "https://api.weibo.com/2/users/show.json"


class WeiboOAuthProvider(MockableOAuthProvider):
    provider = BindingProvider.WEIBO
    display_name = "微博"

    @property
    def enabled(self) -> bool:
        from app.infra.oauth.base import is_production

        if not is_production():
            return True
        return bool(settings.weibo_oauth_app_id and settings.weibo_oauth_app_secret)

    async def _real_exchange(self, code: str) -> OAuthUserInfo:
        """真实对接。微博用表单 POST 换 token。"""
        if not settings.weibo_oauth_app_id:
            from app.infra.oauth.base import OAuthNotConfiguredError

            raise OAuthNotConfiguredError(self.display_name)

        async with httpx.AsyncClient(timeout=settings.oauth_timeout_seconds) as client:
            token_resp = await client.post(
                _TOKEN_URL,
                data={
                    "client_id": settings.weibo_oauth_app_id,
                    "client_secret": settings.weibo_oauth_app_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": "",  # 需与开放平台配置一致
                },
            )
            token_data = token_resp.json()

            if "error" in token_data or "uid" not in token_data:
                logger.warning("微博换 token 失败: %s", token_data)
                raise OAuthCodeInvalidError(self.display_name)

            uid = str(token_data["uid"])
            access_token = token_data["access_token"]

            nickname = None
            avatar_url = None
            try:
                info_resp = await client.get(
                    _USERINFO_URL, params={"access_token": access_token, "uid": uid}
                )
                info = info_resp.json()
                if "error" not in info:
                    nickname = info.get("screen_name")
                    avatar_url = info.get("avatar_large")
            except Exception:
                logger.warning("微博拉取用户信息失败，跳过", exc_info=True)

        return OAuthUserInfo(
            provider_uid=uid,
            nickname=nickname,
            avatar_url=avatar_url,
            raw=token_data,
        )


weibo_provider = WeiboOAuthProvider()
