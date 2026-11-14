"""``model_call_log`` 按月分区的维护（M12-T01）。

分区表写满之后插入会落到 DEFAULT 分区——数据还能写进去，但
分区裁剪失效、清理旧数据时 ``DROP PARTITION`` 也覆盖不到，
久而久之 DEFAULT 分区会变成一张巨大的表。所以需要持续提前建分区。

策略：
    - 每次执行确保「当月 + 未来 ``PARTITION_LOOKAHEAD_MONTHS`` 个月」的分区都存在
    - 已存在的分区跳过（``CREATE TABLE IF NOT EXISTS`` 本身不适用于
      ``PARTITION OF``，所以先查 ``pg_class``）
    - 只建不删——清理旧分区是保留期策略的事（``DROP PARTITION``），
      不应由本函数顺手做掉

本模块的 DDL 必须**幂等**：定时任务可能重复执行、多 worker 并发执行。
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: 提前创建几个月的分区
PARTITION_LOOKAHEAD_MONTHS = 2

#: 可维护分区的表（与数据库设计的按月分区表保持一致）
PARTITIONED_TABLES = ("model_call_log",)


def partition_name(table: str, year: int, month: int) -> str:
    """``(model_call_log, 2026, 11)`` → ``model_call_log_p2026_11``。

    与迁移里初始分区的命名一致（``schema.sql`` 用同样的格式）。
    """
    return f"{table}_p{year}_{month:02d}"


def month_range(year: int, month: int) -> tuple[str, str]:
    """返回分区的时间范围 ``(start, end)``，``end`` 为下月 1 日（左闭右开）。"""
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start.isoformat(), end.isoformat()


def add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """在 (年, 月) 上加减月份，自动跨年。"""
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def months_to_ensure(
    today: date, lookahead: int = PARTITION_LOOKAHEAD_MONTHS
) -> list[tuple[int, int]]:
    """需要保证存在的月份：当月 + 未来 ``lookahead`` 个月。"""
    return [add_months(today.year, today.month, delta) for delta in range(lookahead + 1)]


async def partition_exists(session: AsyncSession, name: str) -> bool:
    result = await session.execute(
        text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"public.{name}"}
    )
    return bool(result.scalar_one())


async def ensure_partitions(
    session: AsyncSession,
    *,
    today: date | None = None,
    lookahead: int = PARTITION_LOOKAHEAD_MONTHS,
    tables: tuple[str, ...] = PARTITIONED_TABLES,
) -> list[str]:
    """确保分区存在，返回**本次新建**的分区名。

    幂等：已存在的分区跳过。并发安全：两个 worker 同时建同一个分区时，
    后到的那个会因为 ``IF NOT EXISTS`` 不生效而报 ``duplicate_table``——
    这里捕获该错误并视为成功（另一个 worker 已经建好了）。
    """
    today = today or date.today()
    created: list[str] = []

    for table in tables:
        for year, month in months_to_ensure(today, lookahead):
            name = partition_name(table, year, month)
            if await partition_exists(session, name):
                continue

            start, end = month_range(year, month)
            try:
                await session.execute(
                    text(
                        f'CREATE TABLE "{name}" PARTITION OF "{table}" '
                        f"FOR VALUES FROM ('{start}') TO ('{end}')"
                    )
                )
                await session.commit()
                created.append(name)
                logger.info("已创建分区 %s [%s, %s)", name, start, end)
            except Exception as exc:
                await session.rollback()
                if "already exists" in str(exc) or "duplicate_table" in str(exc):
                    logger.info("分区 %s 已被其他执行者创建，跳过", name)
                    continue
                logger.error("创建分区 %s 失败：%s", name, exc)
                raise

    return created


async def list_partitions(session: AsyncSession, table: str) -> list[str]:
    """列出某张分区表的全部分区名（含 DEFAULT 分区），按名称排序。"""
    result = await session.execute(
        text(
            """
            SELECT c.relname
            FROM pg_inherits i
            JOIN pg_class c ON c.oid = i.inhrelid
            JOIN pg_class p ON p.oid = i.inhparent
            WHERE p.relname = :table
            ORDER BY c.relname
            """
        ),
        {"table": table},
    )
    return [row[0] for row in result.all()]


async def drop_old_partitions(
    session: AsyncSession, *, before: date, table: str = "model_call_log"
) -> list[str]:
    """删除早于 ``before`` 所在月份的分区（保留期清理）。

    **不在 M12-T01 里调度**——保留多久是运营策略，等确认保留期后再接。
    这里只提供能力，供后续接入定时任务时调用。

    ``DEFAULT`` 分区永不删除。
    """
    dropped: list[str] = []
    cutoff_index = before.year * 12 + before.month - 1

    for name in await list_partitions(session, table):
        if name.endswith("_default"):
            continue
        suffix = name.rsplit("_p", 1)[-1]
        try:
            year_str, month_str = suffix.split("_")
            index = int(year_str) * 12 + int(month_str) - 1
        except (ValueError, IndexError):
            # 命名不符合约定，不去动它——误删分区的事故代价太大
            logger.warning("无法解析分区名 %s，跳过", name)
            continue

        if index < cutoff_index:
            await session.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
            await session.commit()
            dropped.append(name)
            logger.info("已删除过期分区 %s", name)

    return dropped


def next_partition_maintenance_time() -> str:
    """下一次维护时间（cron 表达式的可读形式，供日志与文档引用）。"""
    return "每月 1 日 03:10"
