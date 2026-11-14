"""M12-T02 API Key 加解密的测试。

覆盖：
    - 往返正确（加密后能解回原文）
    - 密文不含明文（DoD：DB 中非明文）
    - 篡改检测
    - 空值/未知格式的边界
"""

from __future__ import annotations

import pytest

from app.modules.model_gateway.crypto import (
    CIPHER_VERSION,
    ApiKeyDecryptError,
    decrypt_api_key,
    encrypt_api_key,
    mask_api_key,
)


class TestRoundTrip:
    def test_encrypt_then_decrypt(self) -> None:
        plain = "sk-1234567890abcdef"
        cipher = encrypt_api_key(plain)
        assert decrypt_api_key(cipher) == plain

    def test_cipher_has_version_prefix(self) -> None:
        assert encrypt_api_key("abc").startswith(f"{CIPHER_VERSION}:")

    def test_cipher_does_not_contain_plaintext(self) -> None:
        """DoD：DB 中存的不是明文。"""
        plain = "sk-very-secret-key-value"
        cipher = encrypt_api_key(plain)
        assert plain not in cipher

    def test_same_plaintext_different_cipher(self) -> None:
        """Fernet 每次加密带随机 IV，同样明文得到不同密文。"""
        plain = "sk-same-value"
        assert encrypt_api_key(plain) != encrypt_api_key(plain)

    def test_unicode_roundtrip(self) -> None:
        plain = "密钥-中文-🎉"
        assert decrypt_api_key(encrypt_api_key(plain)) == plain

    def test_long_key(self) -> None:
        plain = "sk-" + "a" * 500
        assert decrypt_api_key(encrypt_api_key(plain)) == plain


class TestEmptyAndNone:
    def test_encrypt_empty_returns_empty(self) -> None:
        assert encrypt_api_key("") == ""

    def test_decrypt_none(self) -> None:
        assert decrypt_api_key(None) is None

    def test_decrypt_empty(self) -> None:
        assert decrypt_api_key("") is None


class TestErrorCases:
    def test_tampered_cipher_raises(self) -> None:
        """Fernet 带 HMAC 校验，篡改会被检测到。"""
        cipher = encrypt_api_key("sk-original")
        tampered = cipher[:-5] + "AAAAA"

        with pytest.raises(ApiKeyDecryptError):
            decrypt_api_key(tampered)

    def test_unknown_format_raises(self) -> None:
        with pytest.raises(ApiKeyDecryptError):
            decrypt_api_key("plaintext-not-encrypted")

    def test_wrong_version_raises(self) -> None:
        with pytest.raises(ApiKeyDecryptError):
            decrypt_api_key("v9:sometoken")


class TestMask:
    def test_mask_keeps_prefix_and_suffix(self) -> None:
        assert mask_api_key("sk-1234567890abcd") == "sk-****abcd"

    def test_mask_none(self) -> None:
        assert mask_api_key(None) is None

    def test_mask_empty(self) -> None:
        assert mask_api_key("") is None

    def test_mask_short_key_fully_hidden(self) -> None:
        """短密钥截取前后缀会泄露太多，整体打码。"""
        assert mask_api_key("short") == "*****"

    def test_mask_output_shorter_than_input(self) -> None:
        plain = "sk-1234567890abcdefghij"
        masked = mask_api_key(plain)
        assert masked is not None
        assert len(masked) < len(plain)
