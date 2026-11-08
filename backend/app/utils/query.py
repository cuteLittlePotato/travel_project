"""查询辅助：排序白名单与 LIKE 转义。

**安全要点**：``sort_by`` 是用户输入，直接拼进 ``ORDER BY`` 会导致 SQL 注入。
SQLAlchemy 的 ``order_by(column)`` 只能接受**列对象**，因此必须先在白名单里
把「对外字段名」映射为「真实列对象」，未命中一律拒绝。
"""

from __future__ import annotations

from typing import Any, Literal

from app.core.exceptions import ValidationError


def parse_sort_order(raw: str | None) -> Literal["asc", "desc"]:
    """解析排序方向。非法值拒绝，不静默退回默认值。"""
    if raw is None:
        return "desc"
    lowered = raw.lower()
    if lowered == "desc":
        return "desc"
    if lowered == "asc":
        return "asc"
    raise ValidationError([{"field": "sort_order", "reason": "仅支持 asc 或 desc"}])


def apply_sort(
    stmt: Any,
    model: Any,
    sort_by: str | None,
    sort_order: Literal["asc", "desc"],
    allowed: dict[str, Any] | None = None,
    default_field: str = "created_at",
) -> Any:
    """按白名单字段排序。

    :param stmt: SQLAlchemy 的 ``select()`` 语句
    :param model: ORM 模型类，用于取默认排序列
    :param sort_by: 用户传入的字段名
    :param sort_order: 排序方向
    :param allowed: ``{对外字段名: 模型列}``。未传则只允许 ``default_field``
    :param default_field: 未指定 ``sort_by`` 时使用的字段，**也必须存在于白名单**

    非法字段抛 ``ValidationError``（400 + 10001），而不是静默使用默认排序——
    静默退回会让调用方以为排序生效了。
    """
    if allowed is None:
        allowed = {default_field: getattr(model, default_field, None)}
        allowed = {k: v for k, v in allowed.items() if v is not None}

    if not allowed:
        # 模型没有默认排序列，直接返回原语句，不排序
        return stmt

    field = sort_by or default_field
    column = allowed.get(field)

    if column is None:
        raise ValidationError(
            [
                {
                    "field": "sort_by",
                    "reason": f"不支持的排序字段: {field}，可选值: {', '.join(sorted(allowed))}",
                }
            ]
        )

    return stmt.order_by(column.asc() if sort_order == "asc" else column.desc())


def apply_multi_sort(
    stmt: Any,
    sorts: list[tuple[str, Literal["asc", "desc"]]],
    allowed: dict[str, Any],
) -> Any:
    """多字段排序。任一字段不在白名单内则整体拒绝。"""
    columns: list[Any] = []
    for field, order in sorts:
        column = allowed.get(field)
        if column is None:
            raise ValidationError(
                [{"field": "sort_by", "reason": f"不支持的排序字段: {field}"}]
            )
        columns.append(column.asc() if order == "asc" else column.desc())

    return stmt.order_by(*columns) if columns else stmt


def escape_like(keyword: str, escape_char: str = "\\") -> str:
    """转义 LIKE 通配符。

    用户输入 ``100%`` 时，若不转义会被当成「任意字符」，导致搜索结果异常。
    ``%`` ``_`` ``\\`` 三个字符需转义，配合 SQL 的 ``ESCAPE`` 子句使用。

    用法：
        pattern = f"%{escape_like(keyword)}%"
        stmt.where(Model.name.like(pattern, escape="\\\\"))
    """
    return (
        keyword.replace(escape_char, escape_char * 2)
        .replace("%", f"{escape_char}%")
        .replace("_", f"{escape_char}_")
    )


def build_like_pattern(keyword: str | None, escape_char: str = "\\") -> str | None:
    """构造 ``%keyword%`` 模式。空关键词返回 None，表示不加该过滤条件。"""
    if not keyword or not keyword.strip():
        return None
    return f"%{escape_like(keyword.strip(), escape_char)}%"
