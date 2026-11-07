"""查询辅助：排序字段白名单，防止 SQL 注入。"""

from __future__ import annotations

from typing import Any, Literal

from app.core.exceptions import ValidationError


def apply_sort(
    stmt: Any,
    model: Any,
    sort_by: str | None,
    sort_order: Literal["asc", "desc"],
    allowed: dict[str, Any] | None = None,
    default_field: str = "created_at",
) -> Any:
    """按白名单字段排序。

    ``allowed`` 为 ``{对外字段名: 模型列}``。未在白名单内的字段一律拒绝，
    绝不把用户输入直接拼进 SQL。
    """
    if allowed is None:
        allowed = {"created_at": model.created_at}

    field = sort_by or default_field
    column = allowed.get(field)
    if column is None:
        raise ValidationError(
            [{"field": "sort_by", "reason": f"不支持的排序字段: {field}"}]
        )

    return stmt.order_by(column.asc() if sort_order == "asc" else column.desc())


def parse_sort_order(raw: str | None) -> Literal["asc", "desc"]:
    if raw is None or raw.lower() == "desc":
        return "desc"
    if raw.lower() == "asc":
        return "asc"
    raise ValidationError([{"field": "sort_order", "reason": "仅支持 asc 或 desc"}])
