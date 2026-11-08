"""导出 OpenAPI schema，供前端生成 TypeScript 类型。

特点：
    - **不需要启动服务**：直接调用 `create_app().openapi()` 在内存中生成
    - **输出稳定**：固定字段排序与缩进，重复执行产物无 diff（DoD 要求）
    - **自检**：导出前校验 schema 基本结构，避免把损坏的 schema 传给前端

用法：
    cd backend && uv run python scripts/export_openapi.py
    cd backend && uv run python scripts/export_openapi.py --output /tmp/oa.json

产物：backend/openapi.json（已加入 .gitignore，不入库）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app


def _validate(schema: dict) -> None:
    """导出前自检，坏 schema 应在源头报错而不是让前端生成出乱七八糟的类型。"""
    if "paths" not in schema or not isinstance(schema["paths"], dict):
        raise SystemExit("OpenAPI schema 缺少 paths 字段")
    if "openapi" not in schema:
        raise SystemExit("OpenAPI schema 缺少版本号")

    for path, methods in schema["paths"].items():
        if not path.startswith("/"):
            raise SystemExit(f"非法路径（必须以 / 开头）: {path}")
        for method in methods:
            if method not in {
                "get", "post", "put", "patch", "delete", "head", "options", "trace"
            }:
                raise SystemExit(f"非法 HTTP 方法: {method} @ {path}")


def export(output: Path) -> dict:
    """生成并写入 openapi.json。

    排序策略：``sort_keys=True`` 保证同一份代码多次导出的键顺序一致，
    否则前端每次 `git diff` 都会看到大量无关变动。
    """
    schema = create_app().openapi()
    _validate(schema)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return schema


def main(argv: list[str] | None = None) -> int:
    default_output = Path(__file__).resolve().parents[1] / "openapi.json"

    parser = argparse.ArgumentParser(description="导出后端 OpenAPI schema")
    parser.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help=f"输出路径，默认 {default_output}",
    )
    args = parser.parse_args(argv)

    schema = export(args.output)

    path_count = len(schema["paths"])
    schema_count = len(schema.get("components", {}).get("schemas", {}))
    print(f"已导出 {args.output}")
    print(f"  路径 {path_count} 个，数据模型 {schema_count} 个，OpenAPI {schema['openapi']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
