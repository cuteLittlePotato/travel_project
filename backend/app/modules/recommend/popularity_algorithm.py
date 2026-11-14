"""景点热度计算算法（M17-T02）。

**纯函数模块**——不访问数据库、缓存、外部服务，不做任何 IO。
这一约束让算法可以被单元测试完全覆盖，也让 M11-T10 的数据管道
可以自由选择调用方式（进程内函数调用或内部接口）。

算法来源：需求文档 §3.2「热度计算流程」。

    原始分 = view × 1 + click × 2 + plan × 10 + avg_rating × 20
    行为得分 = min-max 归一化到 0-100
    最终热度 = base_popularity × 0.6 + 行为得分 × 0.4

两点说明：

1. **不包含收藏**：需求公式里的 ``favorite_count × 5`` 对应评审 Q9
   已删除的收藏功能，本实现不含该项。

2. **归一化在全量景点之间做**：min-max 需要「全集」作为参照，
   单个景点无法独立归一化。因此本模块提供两个层次：
   ``calculate_raw_scores`` 先算全集的原始分，``normalize_scores``
   再做归一化。数据管道必须先收集全集再调用，不能逐条计算。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.modules.recommend.constants import (
    BASE_POPULARITY_WEIGHT,
    BEHAVIOR_SCORE_MAX,
    BEHAVIOR_SCORE_MIN,
    BEHAVIOR_SCORE_WEIGHT,
    SCORE_QUANTUM,
    WEIGHT_CLICK,
    WEIGHT_PLAN,
    WEIGHT_RATING,
    WEIGHT_VIEW,
)


@dataclass(frozen=True, slots=True)
class BehaviorCounts:
    """单个景点的原始行为计数（``popularity_stat`` 的统计列）。

    用不可变数据类而非 dict：字段名有拼写保护，且能明确表达
    「只有这四项参与计算」。
    """

    view_count: int = 0
    click_count: int = 0
    plan_count: int = 0
    rating_sum: Decimal = Decimal("0")
    rating_count: int = 0

    @property
    def avg_rating(self) -> Decimal:
        """平均评分（0-5）。无评分时为 0。"""
        if self.rating_count <= 0:
            return Decimal("0")
        return self.rating_sum / Decimal(self.rating_count)

    def is_empty(self) -> bool:
        """四项计数全为 0 —— DoD 要求此时 ``behavior_score = 0``。"""
        return (
            self.view_count == 0
            and self.click_count == 0
            and self.plan_count == 0
            and self.rating_count == 0
        )


def calculate_raw_score(counts: BehaviorCounts) -> Decimal:
    """单个景点的行为原始分（未归一化）。

    量与量之间可以相加，是因为权重已经把「一次浏览」「一次加入计划」
    折算成了同一量纲的相对重要性。评分先按 5 分制换算到 0-100
    （× 20）再加权，否则 0-5 的评分在数值上会被浏览/点击淹没。
    """
    return (
        Decimal(counts.view_count) * WEIGHT_VIEW
        + Decimal(counts.click_count) * WEIGHT_CLICK
        + Decimal(counts.plan_count) * WEIGHT_PLAN
        + counts.avg_rating * WEIGHT_RATING
    )


def calculate_raw_scores(
    counts_by_attraction: Mapping[str, BehaviorCounts],
) -> dict[str, Decimal]:
    """批量计算原始分。键默认是景点 ID 字符串，本函数不关心其含义。"""
    return {
        key: calculate_raw_score(counts)
        for key, counts in counts_by_attraction.items()
    }


def normalize_scores(raw_scores: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """把原始分 min-max 归一化到 0-100。

    **除零保护**（DoD 边界）：全集最大值 == 最小值时分母为 0。
    此时所有景点相对位置相同，统一给 0 分——
    给 100 会让「全站无人访问」被误判为「全站最热」。

    空输入返回空 dict。
    """
    if not raw_scores:
        return {}

    values = list(raw_scores.values())
    low = min(values)
    high = max(values)
    span = high - low

    if span <= 0:
        return dict.fromkeys(raw_scores, BEHAVIOR_SCORE_MIN)

    return {
        key: _quantize(
            (value - low) / span * (BEHAVIOR_SCORE_MAX - BEHAVIOR_SCORE_MIN)
            + BEHAVIOR_SCORE_MIN
        )
        for key, value in raw_scores.items()
    }


def calculate_behavior_scores(
    counts_by_attraction: Mapping[str, BehaviorCounts],
) -> dict[str, Decimal]:
    """一步算出行为得分（原始分 + 归一化）。

    **零行为的景点要参与 min-max**，它们是合集里的最小值（0），
    归一化后天然得 0——这正是期望结果。

    一个反面写法是先过滤掉零行为景点再归一化：那样「1 个活跃景点 +
    9 个零行为景点」会变成「只有一个元素」，触发除零保护，
    活跃景点反而得 0 分。零行为景点是全集的一部分，不能剔除。

    全集都没有行为时，min == max == 0，同样走除零保护得到全 0，
    与 DoD「无行为数据时 behavior_score=0」一致。
    """
    if not counts_by_attraction:
        return {}

    return normalize_scores(calculate_raw_scores(counts_by_attraction))


def calculate_final_popularity(
    base_popularity: Decimal | int | float, behavior_score: Decimal | int | float
) -> Decimal:
    """最终热度 = 基础热度 × 0.6 + 行为得分 × 0.4（需求 §3.2）。

    入参先转 Decimal 再计算，避免 float 的二进制误差累积到
    两位小数的落库值上。
    """
    base = _to_decimal(base_popularity)
    behavior = _to_decimal(behavior_score)
    return _quantize(
        base * BASE_POPULARITY_WEIGHT + behavior * BEHAVIOR_SCORE_WEIGHT
    )


def score_attractions(
    counts_by_attraction: Mapping[str, BehaviorCounts],
    base_popularity_by_attraction: Mapping[str, Decimal | int | float],
) -> dict[str, tuple[Decimal, Decimal]]:
    """一次算出每个景点的 (行为得分, 最终热度)。

    方便数据管道一次性拿到要写库的两个值。缺少基础热度的景点
    按 0 处理——正常情况下 ``attraction.base_popularity`` 非空且有默认值。
    """
    behavior_scores = calculate_behavior_scores(counts_by_attraction)
    return {
        key: (
            behavior_scores[key],
            calculate_final_popularity(
                base_popularity_by_attraction.get(key, Decimal("0")),
                behavior_scores[key],
            ),
        )
        for key in counts_by_attraction
    }


def _to_decimal(value: Decimal | int | float) -> Decimal:
    if isinstance(value, Decimal):
        return value
    # 用 str() 转换 float，避免 Decimal(0.1) 得到 0.1000000000000000055...
    return Decimal(str(value))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(SCORE_QUANTUM)


__all__ = [
    "BehaviorCounts",
    "calculate_behavior_scores",
    "calculate_final_popularity",
    "calculate_raw_score",
    "calculate_raw_scores",
    "normalize_scores",
    "score_attractions",
]
