"""UUIDv7 生成。

项目统一使用 UUIDv7 作为主键：时间有序，索引局部性好于 UUIDv4。
"""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """生成 RFC 9562 UUIDv7。

    结构：48 位毫秒时间戳 + 4 位版本 + 12 位随机 + 2 位变体 + 62 位随机。
    """
    unix_ms = int(time.time() * 1000)
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFF_FFFF_FFFF_FFFF

    value = (unix_ms & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76
    value |= rand_a << 64
    value |= 0b10 << 62
    value |= rand_b

    return uuid.UUID(int=value)
