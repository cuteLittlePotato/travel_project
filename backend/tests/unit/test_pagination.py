"""M0-T12 分页与排序辅助的测试。

覆盖 DoD：
    1. page_size=101 返回 400 + code=10001（接口测试）
    2. page=0 或负数返回 400（接口测试）
    3. 响应含 items/total/page/page_size/total_pages（结构断言）
    4. sort_by 走白名单，防 SQL 注入
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from app.core.error_handlers import register_exception_handlers
from app.core.exceptions import BusinessError, ErrorCode
from app.schemas.pagination import (
    DEEP_PAGE_THRESHOLD,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    CommonQuery,
    PageQuery,
    SortQuery,
    build_page,
    page_params,
    sort_params,
)
from app.utils.query import (
    apply_multi_sort,
    apply_sort,
    build_like_pattern,
    escape_like,
    parse_sort_order,
)

# ============================================================
# 测试用接口：带真实分页参数的端点
# ============================================================


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/items")
    async def list_items(
        paging: PageQuery = Depends(page_params),
        sorting: SortQuery = Depends(sort_params),
    ) -> dict[str, Any]:
        # 模拟 41 条数据
        return build_page(
            items=list(range(paging.offset, min(paging.offset + paging.page_size, 41))),
            total=41,
            page=paging.page,
            page_size=paging.page_size,
        )

    @app.get("/sorted")
    async def sorted_items(
        paging: PageQuery = Depends(page_params),
        sorting: SortQuery = Depends(sort_params),
    ) -> dict[str, Any]:
        from app.utils.query import parse_sort_order

        order = parse_sort_order(sorting.sort_order)
        allowed = {"id": _FakeModel.id, "name": _FakeModel.name}
        if sorting.sort_by and sorting.sort_by not in allowed:
            from app.core.exceptions import ValidationError

            raise ValidationError(
                [{"field": "sort_by", "reason": f"不支持的排序字段: {sorting.sort_by}"}]
            )
        return {"order": order, "sort_by": sorting.sort_by}

    return app


class _Column:
    """模拟 SQLAlchemy 列对象，只用于验证白名单映射。"""

    def __init__(self, name: str) -> None:
        self.name = name

    def asc(self) -> tuple[str, str]:
        return (self.name, "asc")

    def desc(self) -> tuple[str, str]:
        return (self.name, "desc")


class _Stmt:
    """模拟 SQLAlchemy select 语句，记录传给 order_by 的列。"""

    def __init__(self) -> None:
        self.ordered: tuple[Any, ...] = ()

    def order_by(self, *columns: Any) -> _Stmt:
        self.ordered = columns
        return self


class _FakeModel:
    id = _Column("id")
    name = _Column("name")
    created_at = _Column("created_at")


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_app(), raise_server_exceptions=False)


# ============================================================
# DoD 1 & 2：参数边界走接口
# ============================================================


class TestPaginationBoundary:
    def test_page_size_101_returns_400_with_code_10001(self, client: TestClient) -> None:
        """DoD：page_size 传 101 时返回 400 + code=10001。"""
        response = client.get("/items?page_size=101")
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == ErrorCode.VALIDATION_FAILED == 10001
        assert body["data"]["errors"][0]["field"] == "page_size"

    def test_page_size_100_is_allowed(self, client: TestClient) -> None:
        assert client.get("/items?page_size=100").status_code == 200

    def test_page_size_0_returns_400(self, client: TestClient) -> None:
        assert client.get("/items?page_size=0").status_code == 400

    def test_page_zero_returns_400(self, client: TestClient) -> None:
        """DoD：page=0 返回 400。"""
        response = client.get("/items?page=0")
        assert response.status_code == 400
        assert response.json()["code"] == 10001

    def test_page_negative_returns_400(self, client: TestClient) -> None:
        assert client.get("/items?page=-1").status_code == 400

    def test_page_one_is_valid(self, client: TestClient) -> None:
        assert client.get("/items?page=1").status_code == 200

    def test_non_integer_page_returns_400(self, client: TestClient) -> None:
        assert client.get("/items?page=abc").status_code == 400

    def test_invalid_sort_order_returns_400(self, client: TestClient) -> None:
        response = client.get("/sorted?sort_order=random")
        assert response.status_code == 400
        assert response.json()["code"] == 10001

    def test_unknown_sort_field_returns_400(self, client: TestClient) -> None:
        response = client.get("/sorted?sort_by=password")
        assert response.status_code == 400
        assert "不支持的排序字段" in response.json()["data"]["errors"][0]["reason"]


# ============================================================
# DoD 3：响应结构
# ============================================================


class TestResponseStructure:
    def test_has_exactly_five_fields(self, client: TestClient) -> None:
        body = client.get("/items").json()
        assert set(body) == {"items", "total", "page", "page_size", "total_pages"}

    def test_defaults(self, client: TestClient) -> None:
        body = client.get("/items").json()
        assert body["page"] == 1
        assert body["page_size"] == DEFAULT_PAGE_SIZE == 20
        assert body["total"] == 41

    def test_total_pages_rounds_up(self, client: TestClient) -> None:
        # 41 条 / 每页 20 → 3 页
        assert client.get("/items").json()["total_pages"] == 3

    def test_offset_applied(self, client: TestClient) -> None:
        body = client.get("/items?page=2&page_size=20").json()
        assert body["items"][0] == 20

    def test_build_page_has_five_fields(self) -> None:
        data = build_page(items=["a"], total=1, page=1, page_size=20)
        assert set(data) == {"items", "total", "page", "page_size", "total_pages"}


# ============================================================
# 边界：total=0
# ============================================================


class TestEmptyResult:
    def test_total_zero_gives_zero_pages(self) -> None:
        """约定：total=0 时 total_pages 返回 0，前端据此判断空态。"""
        data = build_page(items=[], total=0, page=1, page_size=20)
        assert data["total_pages"] == 0
        assert data["items"] == []

    def test_negative_total_treated_as_zero(self) -> None:
        data = build_page(items=[], total=-1, page=1, page_size=20)
        assert data["total_pages"] == 0

    def test_exact_multiple(self) -> None:
        assert build_page([], total=40, page=1, page_size=20)["total_pages"] == 2

    def test_one_more_than_multiple(self) -> None:
        assert build_page([], total=41, page=1, page_size=20)["total_pages"] == 3


# ============================================================
# DoD 4：排序白名单（防 SQL 注入）
# ============================================================


class TestSortWhitelist:
    def test_allowed_field_accepted(self) -> None:
        allowed = {"name": _FakeModel.name}
        stmt = apply_sort(_Stmt(), _FakeModel, "name", "asc", allowed=allowed)
        assert stmt.ordered == (("name", "asc"),)

    def test_disallowed_field_rejected(self) -> None:
        allowed = {"name": _FakeModel.name}
        with pytest.raises(BusinessError) as exc_info:
            apply_sort(_Stmt(), _FakeModel, "password", "asc", allowed=allowed)
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED

    @pytest.mark.parametrize(
        "payload",
        [
            "id; DROP TABLE user--",
            "name--",
            "1 OR 1=1",
            "(SELECT password FROM user)",
            "name, (SELECT 1)",
            "__class__",
        ],
    )
    def test_injection_payloads_rejected(self, payload: str) -> None:
        """任何不在白名单里的字符串都必须拒绝，不能被拼进 SQL。"""
        allowed = {"id": _FakeModel.id, "name": _FakeModel.name}
        with pytest.raises(BusinessError):
            apply_sort(_Stmt(), _FakeModel, payload, "asc", allowed=allowed)

    def test_default_field_not_in_whitelist_rejected(self) -> None:
        """默认排序字段若不在白名单内，应显式报错。

        静默退回其他字段会让调用方以为排序生效了，产生难以排查的分页错乱。
        """
        allowed = {"name": _FakeModel.name}
        with pytest.raises(BusinessError) as exc_info:
            apply_sort(_Stmt(), _FakeModel, None, "desc", allowed=allowed)
        # 具体原因在 data.errors，不在 message（message 统一为「参数校验失败」）
        assert "不支持的排序字段" in exc_info.value.data["errors"][0]["reason"]

    def test_sort_desc_default(self) -> None:
        allowed = {"created_at": _FakeModel.created_at}
        stmt = apply_sort(_Stmt(), _FakeModel, None, "desc", allowed=allowed)
        assert stmt.ordered == (("created_at", "desc"),)

    def test_empty_whitelist_returns_unchanged(self) -> None:
        class _Bare:
            pass

        original = _Stmt()
        assert apply_sort(original, _Bare, "x", "asc") is original

    def test_multi_sort_all_valid(self) -> None:
        allowed = {"id": _FakeModel.id, "name": _FakeModel.name}
        stmt = apply_multi_sort(_Stmt(), [("id", "asc"), ("name", "desc")], allowed)
        assert stmt.ordered == (("id", "asc"), ("name", "desc"))

    def test_multi_sort_rejects_any_invalid(self) -> None:
        allowed = {"id": _FakeModel.id}
        with pytest.raises(BusinessError):
            apply_multi_sort(_Stmt(), [("id", "asc"), ("evil", "desc")], allowed)


class TestSortOrder:
    def test_default_is_desc(self) -> None:
        assert parse_sort_order(None) == "desc"

    @pytest.mark.parametrize("raw", ["asc", "ASC", "Asc"])
    def test_asc_case_insensitive(self, raw: str) -> None:
        assert parse_sort_order(raw) == "asc"

    @pytest.mark.parametrize("raw", ["desc", "DESC"])
    def test_desc_case_insensitive(self, raw: str) -> None:
        assert parse_sort_order(raw) == "desc"

    @pytest.mark.parametrize("raw", ["random", "ascending", "", "0"])
    def test_invalid_rejected(self, raw: str) -> None:
        with pytest.raises(BusinessError):
            parse_sort_order(raw)


# ============================================================
# LIKE 通配符转义
# ============================================================


class TestLikeEscape:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("故宫", "故宫"),
            ("100%", "100\\%"),
            ("a_b", "a\\_b"),
            ("back\\slash", "back\\\\slash"),
            ("%_%", "\\%\\_\\%"),
        ],
    )
    def test_escape(self, raw: str, expected: str) -> None:
        assert escape_like(raw) == expected

    def test_build_pattern(self) -> None:
        assert build_like_pattern("故宫") == "%故宫%"

    def test_build_pattern_escapes(self) -> None:
        assert build_like_pattern("50%") == "%50\\%%"

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_empty_returns_none(self, raw: str | None) -> None:
        assert build_like_pattern(raw) is None

    def test_strips_whitespace(self) -> None:
        assert build_like_pattern("  故宫  ") == "%故宫%"


# ============================================================
# 深分页
# ============================================================


class TestDeepPage:
    def test_threshold_defined(self) -> None:
        assert DEEP_PAGE_THRESHOLD > 0

    def test_detects_deep_page(self) -> None:
        assert PageQuery(page=DEEP_PAGE_THRESHOLD + 1, page_size=20).is_deep_page is True

    def test_normal_page_not_deep(self) -> None:
        assert PageQuery(page=1, page_size=20).is_deep_page is False

    def test_offset_calculation(self) -> None:
        assert PageQuery(page=1, page_size=20).offset == 0
        assert PageQuery(page=3, page_size=20).offset == 40
        assert PageQuery(page=2, page_size=100).offset == 100


# ============================================================
# 模型校验
# ============================================================


class TestModels:
    def test_page_size_over_limit_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            PageQuery(page_size=MAX_PAGE_SIZE + 1)

    def test_page_zero_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            PageQuery(page=0)

    def test_common_query_inherits_both(self) -> None:
        q = CommonQuery(page=2, page_size=50, sort_by="name", sort_order="asc", keyword="故宫")
        assert q.offset == 50
        assert q.sort_by == "name"
        assert q.keyword == "故宫"

    def test_keyword_length_capped(self) -> None:
        with pytest.raises(PydanticValidationError):
            CommonQuery(keyword="x" * 101)

    def test_constants_match_api_spec(self) -> None:
        """API §1.4：默认 20，上限 100。"""
        assert DEFAULT_PAGE_SIZE == 20
        assert MAX_PAGE_SIZE == 100
