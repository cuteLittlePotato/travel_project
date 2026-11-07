#!/usr/bin/env python3
"""生成后端本地开发用的 backend/.env。

从测试服务器的 /opt/travel/deploy/.env 读取服务凭据，
写入本机 backend/.env，使本地 API / Celery 能连上远程中间件。

**由开发者本人执行**，脚本不会把凭据打印到终端。

用法：
    python scripts/dev/setup_local_env.py
    python scripts/dev/setup_local_env.py --host 192.168.75.100 --user root
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys
from pathlib import Path

try:
    import paramiko
except ImportError:
    sys.exit("缺少依赖：pip install paramiko")

TEMPLATE = Path(__file__).resolve().parents[2] / "backend" / ".env.example.local"
OUTPUT = Path(__file__).resolve().parents[2] / "backend" / ".env"

#: 服务端 .env 键 -> 本地 .env 键
KEY_MAP = {
    "POSTGRES_PASSWORD": "POSTGRES_PASSWORD",
    "REDIS_PASSWORD": "REDIS_PASSWORD",
    "RABBITMQ_PASSWORD": "RABBITMQ_PASSWORD",
    "LITELLM_MASTER_KEY": "LITELLM_MASTER_KEY",
}


def read_remote_env(host: str, user: str, password: str) -> dict[str, str]:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=15)
    try:
        _, stdout, _ = client.exec_command("cat /opt/travel/deploy/.env")
        raw = stdout.read().decode("utf-8", "ignore")
    finally:
        client.close()

    values: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def build_env(remote: dict[str, str]) -> str:
    content = TEMPLATE.read_text(encoding="utf-8")

    replacements = {local: remote.get(remote_key, "") for remote_key, local in KEY_MAP.items()}
    # MinIO 使用 ROOT 凭据
    replacements["MINIO_ACCESS_KEY"] = remote.get("MINIO_ROOT_USER", "")
    replacements["MINIO_SECRET_KEY"] = remote.get("MINIO_ROOT_PASSWORD", "")
    # Neo4j 凭据是 neo4j/<password> 形式
    neo4j_auth = remote.get("NEO4J_AUTH", "")
    replacements["NEO4J_PASSWORD"] = neo4j_auth.split("/", 1)[1] if "/" in neo4j_auth else ""

    for key, value in replacements.items():
        content = content.replace(f"{key}=__FILL_FROM_SERVER__", f"{key}={value}")

    # 本地开发使用独立 JWT 密钥，避免与服务器应用互相干扰
    content = content.replace(
        "JWT_SECRET_KEY=local-dev-only-secret-key-change-me-0123456789abcdef",
        f"JWT_SECRET_KEY={secrets.token_urlsafe(48)}",
    )

    missing = [k for k, v in replacements.items() if not v]
    if missing:
        print(f"⚠ 以下项未能从服务器读取，需手工填写：{', '.join(missing)}", file=sys.stderr)

    return content


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 backend/.env（本地混合开发）")
    parser.add_argument("--host", default="192.168.75.100")
    parser.add_argument("--user", default="root")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的 backend/.env")
    args = parser.parse_args()

    if OUTPUT.exists() and not args.force:
        sys.exit(f"{OUTPUT} 已存在，如需覆盖请加 --force")

    password = getpass.getpass(f"{args.user}@{args.host} 的密码：")
    remote = read_remote_env(args.host, args.user, password)
    OUTPUT.write_text(build_env(remote), encoding="utf-8")
    OUTPUT.chmod(0o600)

    print(f"✓ 已写入 {OUTPUT}")
    print("  下一步：cd backend && uv run uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
