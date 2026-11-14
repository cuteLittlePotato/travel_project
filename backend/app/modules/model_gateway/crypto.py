"""模型 API Key 的加解密（M12-T02）。

用 Fernet（AES-128-CBC + HMAC-SHA256），特征是**带完整性校验**：
密文被篡改时解密直接失败，而不是解出一段垃圾数据。

密钥来源：
    - 优先 ``settings.model_api_key_secret``
    - 未配置时从 ``settings.jwt_secret_key`` 派生（PBKDF2）

为什么生产环境要单独配置：
    JWT 密钥按安全实践应定期轮换，若 API Key 也用它加密，
    轮换后所有已存的模型密钥都解不开，只能逐个重填。
    单独配置的密钥可以只在需要时轮换。

密文格式：``v1:<fernet_token>``
    前缀是为了给未来换算法留余地——看到 ``v1`` 才知道用哪套逻辑解，
    不至于把历史密文当成新格式误解析。
"""

from __future__ import annotations

import base64
import logging

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.config import settings

logger = logging.getLogger(__name__)

#: 密文格式前缀
CIPHER_VERSION = "v1"

#: PBKDF2 的固定盐。
#: 固定盐而不是随机盐，是因为只需要「从 JWT 密钥派生出稳定的加密密钥」，
#: 不是在存储口令哈希——随机盐会导致每次启动派生出不同密钥，历史密文全废。
_KDF_SALT = b"travel-model-api-key-v1"
_KDF_ITERATIONS = 480_000


class ApiKeyDecryptError(Exception):
    """密文损坏或密钥不匹配。"""


def _derive_key(secret: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        iterations=_KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))


def _get_fernet() -> Fernet:
    secret = settings.model_api_key_secret or settings.jwt_secret_key
    return Fernet(_derive_key(secret))


def encrypt_api_key(plain: str) -> str:
    """加密 API Key。空字符串视为「无密钥」，返回空串。"""
    if not plain:
        return ""
    token = _get_fernet().encrypt(plain.encode("utf-8")).decode("ascii")
    return f"{CIPHER_VERSION}:{token}"


def decrypt_api_key(cipher: str | None) -> str | None:
    """解密 API Key。

    ``None`` / 空串返回 ``None``——区分「没有密钥」与「解密失败」：
    前者是正常状态（部分模型确实不需要密钥，如本地 Ollama）。
    """
    if not cipher:
        return None

    if not cipher.startswith(f"{CIPHER_VERSION}:"):
        # 未知格式：可能是手工写库的数据，不猜测，交给调用方处理
        raise ApiKeyDecryptError("不支持的密文格式")

    token = cipher[len(CIPHER_VERSION) + 1 :]
    try:
        return _get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ApiKeyDecryptError("API Key 解密失败，密钥可能已轮换") from exc


def mask_api_key(plain: str | None) -> str | None:
    """给前端展示用的掩码，如 ``sk-****abcd``。

    **只在确实需要回显时才用**。API 设计的列表/详情接口完全不返回
    密钥字段，这个函数留给「编辑时提示当前已配置」的场景。
    """
    if not plain:
        return None
    if len(plain) <= 8:
        return "*" * len(plain)
    return f"{plain[:3]}{'*' * 4}{plain[-4:]}"


__all__ = [
    "CIPHER_VERSION",
    "ApiKeyDecryptError",
    "decrypt_api_key",
    "encrypt_api_key",
    "mask_api_key",
]
