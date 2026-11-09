"""M17 推荐引擎的枚举与常量。

本模块只放**常量与纯数据定义**，不引入任何 IO 依赖——
``popularity_algorithm`` 需要被导入时不触发数据库/缓存连接
（M17-T02 DoD：「模块导入不触发任何 IO」）。
"""

from __future__ import annotations

from decimal import Decimal

# ============================================================
# 热度计算的权重（需求 §3.2 热度计算流程）
#
# 需求中的公式含 favorite_count × 5，但评审 Q9 已决定**不做收藏功能**，
# 并删除了 ``popularity_stat.favorite_count`` 字段。
# 因此本模块按「浏览 / 点击 / 加入计划 / 评分」四项计算，
# 收藏项的权重不保留——保留会让字段缺失时恒为 0，读代码的人误以为漏实现。
# ============================================================

#: 浏览量权重
WEIGHT_VIEW = Decimal("1")
#: 点击量权重
WEIGHT_CLICK = Decimal("2")
#: 加入计划次数权重（意图最强，权重最高）
WEIGHT_PLAN = Decimal("10")
#: 评分的权重系数（作用于平均分 0-5，换算后满分为 100）
WEIGHT_RATING = Decimal("20")

#: 行为原始分归一化后的取值范围
BEHAVIOR_SCORE_MIN = Decimal("0")
BEHAVIOR_SCORE_MAX = Decimal("100")

#: 最终热度 = 基础热度 × 0.6 + 行为得分 × 0.4（需求 §3.2 / 数据库 §3.2）
BASE_POPULARITY_WEIGHT = Decimal("0.6")
BEHAVIOR_SCORE_WEIGHT = Decimal("0.4")

#: 分值保留两位小数，与 ``NUMERIC(10,2)`` 对齐
SCORE_QUANTUM = Decimal("0.01")


__all__ = [
    "BASE_POPULARITY_WEIGHT",
    "BEHAVIOR_SCORE_MAX",
    "BEHAVIOR_SCORE_MIN",
    "BEHAVIOR_SCORE_WEIGHT",
    "SCORE_QUANTUM",
    "WEIGHT_CLICK",
    "WEIGHT_PLAN",
    "WEIGHT_RATING",
    "WEIGHT_VIEW",
]
