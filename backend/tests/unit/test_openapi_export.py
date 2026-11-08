"""M0-T10 OpenAPI 导出链路的测试。

覆盖 DoD：
    1. `gen:api` 可重复执行且产物稳定（无 diff）
    2. 生成的类型可被 tsc 通过（由 CI 或手工执行验证）
    3. 规范检查：生成产物含 auto-generated 标记
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

import export_openapi  # noqa: E402


class TestExport:
    def test_schema_is_valid(self) -> None:
        """导出的 schema 必须通过结构自检。"""
        schema = export_openapi.create_app().openapi()
        export_openapi._validate(schema)  # 不抛异常即通过

    def test_paths_have_leading_slash(self) -> None:
        schema = export_openapi.create_app().openapi()
        for path in schema["paths"]:
            assert path.startswith("/"), f"路径必须以 / 开头: {path}"

    def test_rejects_schema_without_paths(self) -> None:
        with pytest.raises(SystemExit, match="缺少 paths"):
            export_openapi._validate({"openapi": "3.1.0"})

    def test_rejects_invalid_method(self) -> None:
        with pytest.raises(SystemExit, match="非法 HTTP 方法"):
            export_openapi._validate(
                {"openapi": "3.1.0", "paths": {"/x": {"fetch": {}}}}
            )


class TestDeterministicOutput:
    """DoD：重复执行产物必须完全一致，否则每次生成都会产生无意义的 diff。"""

    def test_two_exports_are_identical(self, tmp_path: Path) -> None:
        first = tmp_path / "a.json"
        second = tmp_path / "b.json"

        export_openapi.export(first)
        export_openapi.export(second)

        assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")

    def test_keys_are_sorted(self, tmp_path: Path) -> None:
        output = tmp_path / "sorted.json"
        export_openapi.export(output)

        raw = output.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        # 重新按同样规则序列化，应与文件内容一致
        expected = json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        assert raw == expected

    def test_ends_with_newline(self, tmp_path: Path) -> None:
        output = tmp_path / "nl.json"
        export_openapi.export(output)
        assert output.read_text(encoding="utf-8").endswith("\n")


class TestFrontendGenScript:
    """前端生成脚本的静态检查（不实际运行 npm，避免依赖 node 环境）。"""

    @pytest.mark.parametrize("project", ["c-end", "b-end"])
    def test_gen_script_exists(self, project: str) -> None:
        script = BACKEND_DIR.parent / "frontend" / project / "scripts" / "gen-api.mjs"
        assert script.exists(), f"{project} 缺少 scripts/gen-api.mjs"

    @pytest.mark.parametrize("project", ["c-end", "b-end"])
    def test_gen_script_reads_local_schema(self, project: str) -> None:
        """必须读本地 openapi.json，不能依赖后端服务在线。

        只检查可执行代码，跳过注释——脚本注释里会解释「为何不再用 HTTP」，
        按全文匹配会误判。
        """
        script = BACKEND_DIR.parent / "frontend" / project / "scripts" / "gen-api.mjs"
        code_lines = [
            line
            for line in script.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith(("//", "*", "/*"))
        ]
        code = "\n".join(code_lines)

        assert "openapi.json" in code
        assert "http://localhost" not in code, "不应依赖运行中的后端服务"
        assert "http://127.0.0.1" not in code, "不应依赖运行中的后端服务"

    @pytest.mark.parametrize("project", ["c-end", "b-end"])
    def test_gen_script_adds_banner(self, project: str) -> None:
        script = BACKEND_DIR.parent / "frontend" / project / "scripts" / "gen-api.mjs"
        content = script.read_text(encoding="utf-8")
        assert "AUTO-GENERATED FILE" in content

    @pytest.mark.parametrize("project", ["c-end", "b-end"])
    def test_package_json_points_to_script(self, project: str) -> None:
        pkg = json.loads(
            (BACKEND_DIR.parent / "frontend" / project / "package.json").read_text(
                encoding="utf-8"
            )
        )
        assert pkg["scripts"]["gen:api"] == "node scripts/gen-api.mjs"

    @pytest.mark.parametrize("project", ["c-end", "b-end"])
    def test_output_path_is_generated_file(self, project: str) -> None:
        """生成产物必须是 api-generated.d.ts，不能覆盖手写的 api.d.ts / api.ts。"""
        script = BACKEND_DIR.parent / "frontend" / project / "scripts" / "gen-api.mjs"
        content = script.read_text(encoding="utf-8")
        assert "api-generated.d.ts" in content
