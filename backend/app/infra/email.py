"""邮件发送封装。

用于邮箱验证码（注册 / 登录 / 找回密码）。

发送方式：SMTP over SSL（默认 465 端口），兼容主流邮箱服务商。
开发期 ``EMAIL_ENABLED=false`` 时走 Mock，只记日志。

注意：SMTP 是同步阻塞协议，``smtplib`` 的调用放到线程池，
避免阻塞 FastAPI 的事件循环。
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import settings
from app.infra.exceptions import InfraError

logger = logging.getLogger(__name__)


class EmailUnavailableError(InfraError):
    """邮件服务不可用。"""

    def __init__(self, message: str = "邮件服务暂不可用") -> None:
        super().__init__("Email", message)


@dataclass(frozen=True, slots=True)
class EmailResult:
    success: bool
    #: 仅 Mock 模式有值
    debug_code: str | None = None


#: 验证码邮件模板。纯文本，避免被判定为垃圾邮件
_VERIFY_SUBJECT = "云游坊验证码"
_VERIFY_BODY = """您好，

您的云游坊验证码是：{code}

验证码 {minutes} 分钟内有效，请勿泄露给他人。
如非本人操作，请忽略此邮件。

—— 云游坊
"""


class EmailSender:
    def __init__(self) -> None:
        self.enabled = settings.email_enabled
        self.host = settings.email_smtp_host
        self.port = settings.email_smtp_port
        self.user = settings.email_smtp_user
        self.password = settings.email_smtp_password
        self.sender = settings.email_from or settings.email_smtp_user
        self.use_ssl = settings.email_use_ssl

    async def send_code(self, to_email: str, code: str, ttl_seconds: int = 300) -> EmailResult:
        """发送验证码邮件。"""
        if not self.enabled:
            return self._mock_send(to_email, code)
        return await self._send_real(to_email, code, ttl_seconds)

    def _mock_send(self, to_email: str, code: str) -> EmailResult:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Mock 邮件：%s -> 验证码 %s****", _mask_email(to_email), code[:2])
        return EmailResult(success=True, debug_code=code)

    async def _send_real(self, to_email: str, code: str, ttl_seconds: int) -> EmailResult:
        if not self.host or not self.user:
            raise EmailUnavailableError("邮件服务未配置")

        message = EmailMessage()
        message["Subject"] = _VERIFY_SUBJECT
        message["From"] = formataddr(("云游坊", self.sender))
        message["To"] = to_email
        message.set_content(_VERIFY_BODY.format(code=code, minutes=ttl_seconds // 60))

        try:
            # smtplib 是同步的，放到线程池
            await asyncio.to_thread(self._send_sync, message)
        except (smtplib.SMTPException, OSError) as exc:
            logger.error("邮件发送失败: %s", exc)
            raise EmailUnavailableError(str(exc)) from exc

        return EmailResult(success=True)

    def _send_sync(self, message: EmailMessage) -> None:
        if self.use_ssl:
            with smtplib.SMTP_SSL(self.host, self.port, timeout=10) as server:
                server.login(self.user, self.password)
                server.send_message(message)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=10) as server:
                server.starttls()
                server.login(self.user, self.password)
                server.send_message(message)


def _mask_email(email: str) -> str:
    """邮箱脱敏：us***@example.com。"""
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    keep = min(2, len(local))
    return f"{local[:keep]}***@{domain}"


email_sender = EmailSender()
