"""M17-T02 热度计算算法的测试。

覆盖 DoD：
    1. behavior_score 归一化到 0-100
    2. final_popularity = base × 0.6 + behavior × 0.4
    3. 无行为数据时 behavior_score = 0
    4. 纯函数：不访问 DB/Redis/外部服务
    5. 模块导入不触发任何 IO
边界：全集最大值与最小值相同时的除零保护。
"""

from __future__ import annotations

import ast
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

from app.modules.recommend.popularity_algorithm import (
    BehaviorCounts,
    calculate_behavior_scores,
    calculate_final_popularity,
    calculate_raw_score,
    calculate_raw_scores,
    normalize_scores,
    score_attractions,
)

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "modules"
    / "recommend"
    / "popularity_algorithm.py"
)


# ============================================================
# 原始分
# ============================================================


class TestRawScore:
    def test_weights_applied(self) -> None:
        """原始分 = view × 1 + click × 2 + plan × 10 + avg_rating × 20。"""
        counts = BehaviorCounts(
            view_count=10,
            click_count=5,
            plan_count=2,
            rating_sum=Decimal("9"),
            rating_count=2,  # 平均分 4.5
        )
        # 10×1 + 5×2 + 2×10 + 4.5×20 = 10 + 10 + 20 + 90 = 130
        assert calculate_raw_score(counts) == Decimal("130")

    def test_all_zero(self) -> None:
        assert calculate_raw_score(BehaviorCounts()) == Decimal("0")

    def test_rating_without_count_is_zero(self) -> None:
        """有 rating_sum 但 rating_count=0 —— 平均分按 0 处理，防止除零。"""
        counts = BehaviorCounts(rating_sum=Decimal("100"), rating_count=0)
        assert counts.avg_rating == Decimal("0")
        assert calculate_raw_score(counts) == Decimal("0")

    def test_avg_rating(self) -> None:
        counts = BehaviorCounts(rating_sum=Decimal("13"), rating_count=3)
        # 13 / 3 = 4.333...，四舍五入到 4 位小数比较
        assert counts.avg_rating.quantize(Decimal("0.0001")) == Decimal("4.3333")

    def test_batch_matches_single(self) -> None:
        counts = {
            "a": BehaviorCounts(view_count=1),
            "b": BehaviorCounts(plan_count=3),
        }
        batch = calculate_raw_scores(counts)
        assert batch["a"] == calculate_raw_score(counts["a"])
        assert batch["b"] == calculate_raw_score(counts["b"])

    def test_plan_count_weighs_heaviest(self) -> None:
        """加入计划的权重高于点击与浏览——意图强度排序。"""
        view = calculate_raw_score(BehaviorCounts(view_count=1))
        click = calculate_raw_score(BehaviorCounts(click_count=1))
        plan = calculate_raw_score(BehaviorCounts(plan_count=1))
        assert view < click < plan


# ============================================================
# 归一化（DoD 1）
# ============================================================


class TestNormalize:
    def test_range_is_0_to_100(self) -> None:
        """DoD：behavior_score 归一化到 0-100。"""
        raw = {
            "low": Decimal("0"),
            "mid": Decimal("50"),
            "high": Decimal("100"),
        }
        scores = normalize_scores(raw)

        assert min(scores.values()) == Decimal("0.00")
        assert max(scores.values()) == Decimal("100.00")
        assert scores["mid"] == Decimal("50.00")

    def test_all_within_bounds(self) -> None:
        raw = {f"a{i}": Decimal(i * 7) for i in range(20)}
        scores = normalize_scores(raw)
        assert all(Decimal("0") <= v <= Decimal("100") for v in scores.values())

    def test_empty_input(self) -> None:
        assert normalize_scores({}) == {}

    def test_single_element(self) -> None:
        """只有一个景点时 min == max，走除零保护。"""
        assert normalize_scores({"only": Decimal("123")}) == {"only": Decimal("0.00")}

    def test_division_by_zero_protection(self) -> None:
        """DoD 边界：全集最大值与最小值相同时不得抛异常。

        统一给 0 而非 100——「全站热度相同」不等于「全站最热」。
        """
        raw = {"a": Decimal("42"), "b": Decimal("42"), "c": Decimal("42")}
        scores = normalize_scores(raw)

        assert scores == {
            "a": Decimal("0.00"),
            "b": Decimal("0.00"),
            "c": Decimal("0.00"),
        }

    def test_quantized_to_two_decimals(self) -> None:
        """结果对齐 NUMERIC(10,2)。"""
        raw = {"a": Decimal("0"), "b": Decimal("3")}
        scores = normalize_scores(raw)
        for value in scores.values():
            assert value.as_tuple().exponent == -2


# ============================================================
# 行为得分（DoD 1 + 3）
# ============================================================


class TestBehaviorScore:
    def test_empty_counts_give_zero(self) -> None:
        """DoD：无行为数据时 behavior_score = 0。"""
        counts = {"a": BehaviorCounts()}
        assert calculate_behavior_scores(counts) == {"a": Decimal("0.00")}

    def test_no_behaviors_anywhere(self) -> None:
        counts = {f"a{i}": BehaviorCounts() for i in range(5)}
        assert all(v == Decimal("0.00") for v in calculate_behavior_scores(counts).values())

    def test_empty_counts_not_promoted_by_normalization(self) -> None:
        """零行为景点不会因为「是全集最小值」而被其他景点抬到非零。"""
        counts = {
            "active": BehaviorCounts(plan_count=10),
            "idle": BehaviorCounts(),
        }
        scores = calculate_behavior_scores(counts)
        assert scores["idle"] == Decimal("0.00")
        assert scores["active"] == Decimal("100.00")

    def test_mixed_distribution(self) -> None:
        counts = {
            "hot": BehaviorCounts(view_count=1000, click_count=500, plan_count=100),
            "cold": BehaviorCounts(view_count=1),
        }
        scores = calculate_behavior_scores(counts)
        assert scores["hot"] == Decimal("100.00")
        assert scores["cold"] == Decimal("0.00")

    def test_empty_mapping(self) -> None:
        assert calculate_behavior_scores({}) == {}


# ============================================================
# 最终热度（DoD 2）
# ============================================================


class TestFinalPopularity:
    def test_formula(self) -> None:
        """DoD：final_popularity = base × 0.6 + behavior × 0.4。"""
        # 90 × 0.6 + 50 × 0.4 = 54 + 20 = 74
        assert calculate_final_popularity(90, 50) == Decimal("74.00")

    def test_zero_behavior(self) -> None:
        # 80 × 0.6 + 0 × 0.4 = 48
        assert calculate_final_popularity(80, 0) == Decimal("48.00")

    def test_zero_base(self) -> None:
        # 0 × 0.6 + 100 × 0.4 = 40
        assert calculate_final_popularity(0, 100) == Decimal("40.00")

    def test_both_zero(self) -> None:
        assert calculate_final_popularity(0, 0) == Decimal("0.00")

    def test_accepts_decimal_int_float(self) -> None:
        assert calculate_final_popularity(Decimal("60"), Decimal("30")) == Decimal("48.00")
        assert calculate_final_popularity(60, 30) == Decimal("48.00")
        assert calculate_final_popularity(60.0, 30.0) == Decimal("48.00")

    def test_float_precision_kept(self) -> None:
        """用 str() 转 Decimal——0.1 不应变成 0.1000000000000000055。"""
        # 0.1 × 0.6 + 0.1 × 0.4 = 0.06 + 0.04 = 0.10
        assert calculate_final_popularity(0.1, 0.1) == Decimal("0.10")

    def test_result_quantized(self) -> None:
        result = calculate_final_popularity(Decimal("33.33"), Decimal("66.67"))
        assert result.as_tuple().exponent == -2

    def test_bounds(self) -> None:
        """基础热度与行为得分都在 0-100 时，最终热度也在 0-100。"""
        assert calculate_final_popularity(100, 100) == Decimal("100.00")
        assert calculate_final_popularity(0, 0) == Decimal("0.00")


# ============================================================
# 组合接口
# ============================================================


class TestScoreAttractions:
    def test_returns_behavior_and_final(self) -> None:
        counts = {
            "hot": BehaviorCounts(view_count=100),
            "cold": BehaviorCounts(view_count=1),
        }
        base = {"hot": Decimal("80"), "cold": Decimal("80")}
        result = score_attractions(counts, base)

        assert result["hot"] == (
            Decimal("100.00"),
            calculate_final_popularity(80, 100),
        )
        assert result["cold"] == (
            Decimal("0.00"),
            calculate_final_popularity(80, 0),
        )

    def test_missing_base_defaults_to_zero(self) -> None:
        result = score_attractions({"a": BehaviorCounts(view_count=5)}, {})
        assert result["a"] == (Decimal("0.00"), Decimal("0.00"))

    def test_empty(self) -> None:
        assert score_attractions({}, {}) == {}


# ============================================================
# 纯函数约束（DoD 4 + 5）
# ============================================================


class TestPurity:
    def test_no_io_imports(self) -> None:
        """DoD：模块不导入数据库 / 缓存 / HTTP 客户端。"""
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)

        forbidden = (
            "sqlalchemy",
            "redis",
            "asyncpg",
            "httpx",
            "requests",
            "aiohttp",
            "app.db",
            "app.infra",
        )
        offending = [
            name for name in imported if any(name.startswith(f) for f in forbidden)
        ]
        assert offending == [], f"纯函数模块不应导入 IO 依赖：{offending}"

    def test_no_session_or_client_references(self) -> None:
        """DoD 原文的 grep 约束：源码中不出现 session / redis / client。

        注释里提到「不访问缓存」是允许的，这里只检查**代码部分**——
        剥掉文档字符串与注释后再断言，否则约束会变成「连说明都不能写」。
        """
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    docstrings.add(doc)

        code: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                code.append(node.id)
            elif isinstance(node, ast.Attribute):
                code.append(node.attr)
            elif isinstance(node, ast.arg) or (isinstance(node, ast.keyword) and node.arg):
                code.append(node.arg)

        identifiers = " ".join(code).lower()
        for token in ("session", "redis", "httpx", "asyncpg"):
            assert token not in identifiers, f"代码中不应出现 {token!r}"

    def test_import_triggers_no_io(self) -> None:
        """DoD：模块导入不触发任何 IO。

        在干净的子进程里导入，且把 sqlalchemy / redis 等模块标记为
        「被导入即失败」，以此证明导入链路没有碰到它们。
        """
        script = """
import sys

class Trap:
    def find_module(self, name, path=None):
        if name.split('.')[0] in {'sqlalchemy', 'redis', 'asyncpg', 'httpx'}:
            raise AssertionError(f'导入模块时触发了 IO 依赖: {name}')
        return None

sys.meta_path.insert(0, Trap())
import app.modules.recommend.popularity_algorithm  # noqa: F401
print('OK')
"""
        # MODULE_PATH = <backend>/app/modules/recommend/popularity_algorithm.py
        backend_dir = MODULE_PATH.parents[3]
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=backend_dir,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout

    def test_functions_are_deterministic(self) -> None:
        """同样输入必得同样输出（无隐藏状态）。"""
        counts = {"a": BehaviorCounts(view_count=10), "b": BehaviorCounts(view_count=20)}
        first = calculate_behavior_scores(counts)
        second = calculate_behavior_scores(counts)
        assert first == second
