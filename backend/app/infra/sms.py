"""短信发送封装。

需求 §2.1.1：验证码短信。开发期可用 Mock。

**服务商未定**（M0 审查已确认）：配置里只保留 `SMS_ENABLED` / `SMS_BASE_URL` /
`SMS_API_KEY` / `SMS_SIGN_NAME` 四项占位。真实对接时只改本文件的 `_send_real()`，
业务代码无需改动。

失败处理：短信服务不可用时抛 ``SmsUnavailableError``，
由调用方决定是提示用户「稍后重试」还是降级。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.infra.exceptions import InfraError

logger = logging.getLogger(__name__)


class SmsUnavailableError(InfraError):
    """短信服务不可用。"""

    def __init__(self, message: str = "短信服务暂不可用") -> None:
        super().__init__("SMS", message)


@dataclass(frozen=True, slots=True)
class SmsResult:
    """发送结果。开发期 Mock 会把验证码回传，便于本地调试。"""

    success: bool
    #: 仅 Mock 模式有值。**生产环境必须为 None，否则验证码会泄露到日志/响应**
    debug_code: str | None = None


class SmsSender:
    """短信发送器。

    - ``enabled=false``：走 Mock，只记日志，不真的发短信
    - ``enabled=true``：调用 ``_send_real()``，服务商对接时实现该方法
    """

    def __init__(self) -> None:
        self.enabled = settings.sms_enabled
        self.base_url = settings.sms_base_url
        self.api_key = settings.sms_api_key
        self.sign_name = settings.sms_sign_name
        self.timeout = settings.sms_timeout_seconds

    async def send_code(self, phone: str, code: str) -> SmsResult:
        """发送验证码短信。"""
        if not self.enabled:
            return self._mock_send(phone, code)
        return await self._send_real(phone, code)

    def _mock_send(self, phone: str, code: str) -> SmsResult:
        """开发期 Mock。

        日志里**不打印完整手机号与验证码**——即使是开发环境，
        也可能被截图、贴进 issue。只在 DEBUG 级别打印掩码。
        """
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Mock 短信：%s -> 验证码 %s****",
                _mask_phone(phone),
                code[:2],
            )
        return SmsResult(success=True, debug_code=code)

    async def _send_real(self, phone: str, code: str) -> SmsResult:
        """真实服务商对接。

        TODO(服务商确定后): 按实际 API 实现。当前统一按「HTTP POST + JSON」
        的常见形式编写，若服务商协议不同再调整。
        """
        if not self.base_url or not self.api_key:
            raise SmsUnavailableError("短信服务未配置")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.base_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "phone": phone,
                        "sign_name": self.sign_name,
                        "template_params": {"code": code},
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("短信发送失败: %s", exc)
            raise SmsUnavailableError(str(exc)) from exc

        return SmsResult(success=True)


def _mask_phone(phone: str) -> str:
    """手机号脱敏：138****8888。"""
    if len(phone) >= 7:
        return f"{phone[:3]}****{phone[-4:]}"
    return "***"


sms_sender = SmsSender()
