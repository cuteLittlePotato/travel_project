#!/usr/bin/env python3
"""检查本机到测试服务器各中间件的连通性。

在开发前跑一次，快速判断是「网络/端口不通」还是「代码问题」。

用法：
    python scripts/dev/check_remote_services.py
    python scripts/dev/check_remote_services.py --host 192.168.75.100
"""

from __future__ import annotations

import argparse
import socket

#: (名称, 端口, 说明)
SERVICES = [
    ("PostgreSQL", 15432, "业务主库"),
    ("Redis", 16379, "缓存 / Celery 结果"),
    ("Neo4j Bolt", 17687, "知识图谱"),
    ("Milvus", 19530, "向量检索"),
    ("Elasticsearch", 19200, "关键词检索"),
    ("MinIO API", 19000, "对象存储"),
    ("RabbitMQ", 5672, "Celery Broker"),
    ("LiteLLM", 14000, "模型网关"),
    ("Langfuse", 13000, "AI 链路追踪"),
]


def check(host: str, timeout: float) -> int:
    failures = 0
    print(f"目标 {host}\n")
    for name, port, note in SERVICES:
        sock = socket.socket()
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            print(f"  ✓ {name:<16} :{port:<6} {note}")
        except OSError as exc:
            failures += 1
            print(f"  ✗ {name:<16} :{port:<6} {note}  ({type(exc).__name__})")
        finally:
            sock.close()

    print()
    if failures:
        print(f"{failures} 个服务不可达。请确认：")
        print("  1. 服务器已启动：ssh root@<host> 'cd /opt/travel/deploy && docker compose ps'")
        print("  2. 服务端口已在 docker-compose 中映射到宿主机")
        print("  3. 防火墙放行对应端口")
    else:
        print("全部可达，可以开始本地开发。")
    return 0 if failures == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="检查远程中间件连通性")
    parser.add_argument("--host", default="192.168.75.100")
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()
    raise SystemExit(check(args.host, args.timeout))


if __name__ == "__main__":
    main()
