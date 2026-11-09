"""昵称生成工具（M01-T06）。

自动注册（验证码登录时账号不存在）需要生成昵称，规则见 API §3.4：
    - 手机号：脱敏前缀 + 4 位十六进制后缀，如 ``138***a3f2``
    - 邮箱：用户名部分 + 4 位十六进制后缀，如 ``alice_a3f2``
    - 冲突时重新生成后缀，最多重试 3 次，仍冲突则追加序号

与 ``service.generate_default_nickname`` 的区别：
    - ``service`` 那个用于**显式注册**（用户可能自己填了昵称）
    - 本模块用于**自动注册**，严格按 API §3.4 的格式
"""

from __future__ import annotations

import secrets

from app.modules.account.constants import NICKNAME_MAX_LENGTH

#: 后缀长度（十六进制字符数）
SUFFIX_LENGTH = 4

#: 冲突时的最大重试次数
MAX_RETRY = 3


def _random_suffix() -> str:
    """生成 4 位十六进制后缀，如 ``a3f2``。"""
    return secrets.token_hex(SUFFIX_LENGTH // 2)


def _phone_prefix(phone: str) -> str:
    """手机号脱敏前缀：``13800138000`` -> ``138***``。"""
    return f"{phone[:3]}***"


def _email_prefix(email: str) -> str:
    """邮箱用户名部分：``alice@example.com`` -> ``alice``。

    去掉可能包含的非单词字符（如 ``user.name`` -> ``username``），
    保证符合 ``^\\w+_`` 的格式要求。
    """
    local = email.split("@", 1)[0]
    cleaned = "".join(ch for ch in local if ch.isalnum() or ch in "_-")
    return cleaned or "user"


def build_nickname_base(target: str) -> str:
    """按 target 生成昵称前缀（不含随机后缀）。"""
    if "@" in target:
        return _email_prefix(target)
    return _phone_prefix(target)


def generate_auto_nickname(target: str, *, attempt: int = 0) -> str:
    """生成自动注册的昵称。

    :param target: 手机号或邮箱
    :param attempt: 第几次尝试（0 表示首次）。冲突时递增

    格式：
        - 手机号：``138***a3f2``（``^\\d{3}\\*\\*\\*[0-9a-f]{4}$``）
        - 邮箱：``alice_a3f2``（``^\\w+_[0-9a-f]{4}$``）

    第 4 次及以后（``attempt >= MAX_RETRY``）追加序号：
        ``138***a3f2_1``、``alice_a3f2_1``
    """
    base = build_nickname_base(target)
    suffix = _random_suffix()

    if attempt >= MAX_RETRY:
        # 重试耗尽，追加序号保证唯一性
        nickname = f"{base}{suffix}_{attempt - MAX_RETRY + 1}"
    elif "@" in target:
        nickname = f"{base}_{suffix}"
    else:
        # 手机号：base 已含 ***，直接拼接后缀
        nickname = f"{base}{suffix}"

    # 兜底截断，避免超出 user.nickname 的 VARCHAR(50)
    return nickname[:NICKNAME_MAX_LENGTH]


def is_valid_auto_nickname(nickname: str, target: str) -> bool:
    """校验昵称是否符合自动生成的格式（供测试与自检使用）。"""
    import re

    if "@" in target:
        return bool(re.fullmatch(r"\w+_[0-9a-f]{4}(_\d+)?", nickname))
    return bool(re.fullmatch(r"\d{3}\*\*\*[0-9a-f]{4}(_\d+)?", nickname))
