"""微信登录。

协议（微信开放平台 / 公众平台网页授权）：
    1. 前端引导用户跳转 ``https://open.weixin.qq.com/connect/qrconnect?...``
    2. 用户授权后回调带 ``code``
    3. 后端用 ``code`` 换 ``access_token`` + ``openid``
    4. 再用 ``access_token`` + ``openid`` 拉取用户信息

**当前未接入真实接口**（AppID/AppSecret 未申请）。
真实对接时只需替换 ``_real_exchange()``，业务代码不动。

接口文档：
    - 换取 access_token: GET https://api.weixin.qq.com/sns/oauth2/access_token
    - 拉取用户信息:     GET https://api.weixin.qq.com/sns/userinfo
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings
from app.infra.oauth.base import (
    MockableOAuthProvider,
    OAuthCodeInvalidError,
    OAuthUserInfo,
)
from app.modules.account.constants import BindingProvider

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://api.weixin.qq.com/sns/oauth2/access_token"
_USERINFO_URL = "https://api.weixin.qq.com/sns/userinfo"


class WechatOAuthProvider(MockableOAuthProvider):
    provider = BindingProvider.WECHAT
    display_name = "微信"

    @property
    def enabled(self) -> bool:
        """生产环境要求真实配置；开发/测试环境视为启用，便于 Mock。"""
        from app.infra.oauth.base import is_production

        if not is_production():
            return True
        return bool(settings.wechat_oauth_app_id and settings.wechat_oauth_app_secret)

    async def _real_exchange(self, code: str) -> OAuthUserInfo:
        """真实对接。

        微信的错误响应是 HTTP 200 + ``{"errcode": 40029, "errmsg": "invalid code"}``，
        因此不能只看 HTTP 状态码，必须检查 ``errcode``。
        """
        if not settings.wechat_oauth_app_id:
            from app.infra.oauth.base import OAuthNotConfiguredError

            raise OAuthNotConfiguredError(self.display_name)

        async with httpx.AsyncClient(timeout=settings.oauth_timeout_seconds) as client:
            # 1. code -> access_token + openid
            token_resp = await client.get(
                _TOKEN_URL,
                params={
                    "appid": settings.wechat_oauth_app_id,
                    "secret": settings.wechat_oauth_app_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
            token_data = token_resp.json()

            if token_data.get("errcode"):
                logger.warning("微信换 token 失败: %s", token_data)
                raise OAuthCodeInvalidError(self.display_name)

            access_token = token_data["access_token"]
            openid = token_data["openid"]
            union_id = token_data.get("unionid")

            # 2. 拉用户信息（失败不阻塞登录，昵称头像只是锦上添花）
            nickname = None
            avatar_url = None
            try:
                info_resp = await client.get(
                    _USERINFO_URL,
                    params={"access_token": access_token, "openid": openid, "lang": "zh_CN"},
                )
                info = info_resp.json()
                if not info.get("errcode"):
                    nickname = info.get("nickname")
                    avatar_url = info.get("headimgurl")
            except Exception:
                logger.warning("微信拉取用户信息失败，跳过", exc_info=True)

        return OAuthUserInfo(
            provider_uid=openid,
            union_id=union_id,
            nickname=nickname,
            avatar_url=avatar_url,
            raw=token_data,
        )


wechat_provider = WechatOAuthProvider()
