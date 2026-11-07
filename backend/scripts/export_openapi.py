"""导出 OpenAPI schema，供前端生成 TypeScript 类型。

用法：
    cd backend && uv run python scripts/export_openapi.py
产物：backend/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app  # noqa: E402


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "openapi.json"
    schema = create_app().openapi()
    output.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已导出 {output}，共 {len(schema['paths'])} 个路径")


if __name__ == "__main__":
    main()
