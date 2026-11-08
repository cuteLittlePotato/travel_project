"""UUIDv7 生成。

项目统一使用 UUIDv7 作为主键：时间有序，索引局部性好于 UUIDv4。

实现遵循 RFC 9562 §6.2 Method 1（单调随机）：
同一毫秒内通过 12 位计数器递增，保证同毫秒生成的 ID 也严格递增，
避免批量插入时 B-tree 页分裂。
"""

from __future__ import annotations

import os
import threading
import time
import uuid

#: 上次使用的时间戳（毫秒）与计数器，均在进程内维护
_last_ms: int = 0
_counter: int = 0
_lock = threading.Lock()

_COUNTER_MAX = 0x0FFF  # 12 位
_RAND_B_MAX = 0x3FFF_FFFF_FFFF_FFFF  # 62 位


def uuid7() -> uuid.UUID:
    """生成 RFC 9562 UUIDv7，同一毫秒内严格单调递增。

    结构：48 位毫秒时间戳 + 4 位版本 + 12 位计数器 + 2 位变体 + 62 位随机。
    计数器溢出时借用下一毫秒，保证不产生回退。
    """
    global _last_ms, _counter

    with _lock:
        now_ms = int(time.time() * 1000)

        if now_ms > _last_ms:
            _last_ms = now_ms
            # 新的一毫秒，计数器从随机值起步，降低可预测性
            _counter = int.from_bytes(os.urandom(2), "big") & _COUNTER_MAX
        else:
            # 同一毫秒或时钟回拨：沿用上次时间戳并递增计数器
            _counter += 1
            if _counter > _COUNTER_MAX:
                _counter = 0
                _last_ms += 1

        timestamp = _last_ms
        counter = _counter

    rand_b = int.from_bytes(os.urandom(8), "big") & _RAND_B_MAX

    value = (timestamp & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76
    value |= counter << 64
    value |= 0b10 << 62
    value |= rand_b

    return uuid.UUID(int=value)
