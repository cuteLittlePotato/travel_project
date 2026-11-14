"""``OpeningHours`` 校验模型的测试。

背景：``attraction.opening_hours`` 原本是 ``dict[str, Any]``，
接受任意结构（如 ``{"foo": "bar"}``）。脏数据入库后，
C 端按星期展示时拿到无法解析的内容。

本模型给出白名单结构（数据库设计 §3.2）::

    {"mon": "09:00-17:00", "tue": "closed", "note": "16:30 停止入场"}
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.catalog.schemas import (
    OPENING_HOURS_CLOSED,
    WEEKDAY_KEYS,
    AttractionCreate,
    OpeningHours,
)

# ============================================================
# 合法输入
# ============================================================


class TestValid:
    def test_single_day(self) -> None:
        value = OpeningHours(mon="09:00-17:00")
        assert value.mon == "09:00-17:00"

    def test_full_week(self) -> None:
        value = OpeningHours(
            mon="09:00-17:00",
            tue="09:00-17:00",
            wed="09:00-17:00",
            thu="09:00-17:00",
            fri="09:00-17:00",
            sat="09:00-18:00",
            sun="09:00-18:00",
        )
        assert value.sat == "09:00-18:00"

    def test_closed_day(self) -> None:
        value = OpeningHours(mon="09:00-17:00", wed=OPENING_HOURS_CLOSED)
        assert value.wed == "closed"

    def test_note_only(self) -> None:
        """只有备注也算有效——有些景点确实全天开放，只写补充说明。"""
        value = OpeningHours(note="全天开放，无需预约")
        assert value.note == "全天开放，无需预约"

    def test_boundary_times(self) -> None:
        """00:00 与 23:59 都是合法时间。"""
        assert OpeningHours(mon="00:00-23:59").mon == "00:00-23:59"

    def test_midnight_crossing_not_allowed_as_is(self) -> None:
        """跨午夜（22:00-02:00）不能这么写，结束必须晚于开始。"""
        with pytest.raises(ValidationError):
            OpeningHours(mon="22:00-02:00")


# ============================================================
# 格式校验
# ============================================================


class TestTimeFormat:
    @pytest.mark.parametrize(
        "bad_value",
        [
            "9:00-17:00",       # 缺前导零
            "09:00~17:00",      # 错误分隔符
            "09:00",            # 缺结束时间
            "09:00-17:00-18:00",  # 多了段
            "0900-1700",        # 缺冒号
            "24:00-25:00",      # 越界
            "09:60-17:00",      # 分钟越界
            "open",             # 自由文本
            "",
        ],
    )
    def test_rejected_formats(self, bad_value: str) -> None:
        with pytest.raises(ValidationError):
            OpeningHours(mon=bad_value)

    def test_error_message_mentions_format(self) -> None:
        with pytest.raises(ValidationError) as exc:
            OpeningHours(mon="9:00-17:00")
        assert "HH:mm-HH:mm" in str(exc.value)


class TestTimeOrder:
    def test_end_before_start_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            OpeningHours(mon="17:00-09:00")
        assert "结束时间必须晚于开始时间" in str(exc.value)

    def test_same_start_end_rejected(self) -> None:
        """零时长区间没有意义。"""
        with pytest.raises(ValidationError):
            OpeningHours(mon="09:00-09:00")

    def test_one_minute_is_valid(self) -> None:
        assert OpeningHours(mon="09:00-09:01").mon == "09:00-09:01"


# ============================================================
# 结构校验
# ============================================================


class TestStructure:
    def test_unknown_key_rejected(self) -> None:
        """白名单模型不接受未知 key——这正是它比 dict 强的地方。"""
        with pytest.raises(ValidationError):
            OpeningHours(mon="09:00-17:00", foo="bar")

    def test_extra_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OpeningHours(**{"holiday": "09:00-17:00"})

    def test_empty_rejected(self) -> None:
        """全空没有意义。"""
        with pytest.raises(ValidationError) as exc:
            OpeningHours()
        assert "至少要设置一天或填写备注" in str(exc.value)

    def test_note_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OpeningHours(note="x" * 201)

    def test_note_max_length_ok(self) -> None:
        assert OpeningHours(note="x" * 200).note is not None

    def test_all_weekday_keys_covered(self) -> None:
        assert WEEKDAY_KEYS == ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


# ============================================================
# 序列化
# ============================================================


class TestSerialization:
    def test_none_fields_dropped(self) -> None:
        """未设置的星期不应序列化成 null 存进 JSONB。"""
        value = OpeningHours(mon="09:00-17:00", note="备注")
        dumped = value.model_dump()

        assert dumped == {"mon": "09:00-17:00", "note": "备注"}
        assert "tue" not in dumped
        assert "wed" not in dumped

    def test_closed_preserved(self) -> None:
        dumped = OpeningHours(mon="09:00-17:00", wed="closed").model_dump()
        assert dumped["wed"] == "closed"

    def test_roundtrip(self) -> None:
        original = {
            "mon": "09:00-17:00",
            "wed": "closed",
            "sat": "09:00-18:00",
            "note": "16:30 停止入场",
        }
        assert OpeningHours(**original).model_dump() == original


# ============================================================
# 与 AttractionCreate 的集成
# ============================================================


class TestAttractionIntegration:
    def test_create_accepts_opening_hours(self) -> None:
        payload = AttractionCreate(
            name="故宫博物院",
            city_id=uuid.uuid4(),
            opening_hours=OpeningHours(mon="09:00-17:00", note="周一闭馆除外"),
        )
        assert payload.opening_hours is not None
        assert payload.opening_hours.mon == "09:00-17:00"

    def test_create_accepts_none(self) -> None:
        payload = AttractionCreate(name="无开放时间", city_id=uuid.uuid4())
        assert payload.opening_hours is None

    def test_model_dump_drops_empty_fields(self) -> None:
        """``model_dump()`` 落库时不应带 null 字段。"""
        payload = AttractionCreate(
            name="测试",
            city_id=uuid.uuid4(),
            opening_hours=OpeningHours(mon="09:00-17:00"),
        )
        dumped = payload.model_dump(exclude={"category_ids"})

        assert dumped["opening_hours"] == {"mon": "09:00-17:00"}

    def test_create_rejects_bad_opening_hours(self) -> None:
        with pytest.raises(ValidationError):
            AttractionCreate(
                name="测试",
                city_id=uuid.uuid4(),
                opening_hours={"mon": "bad"},  # type: ignore[arg-type]
            )

    def test_create_rejects_unknown_key(self) -> None:
        with pytest.raises(ValidationError):
            AttractionCreate(
                name="测试",
                city_id=uuid.uuid4(),
                opening_hours={"foo": "09:00-17:00"},  # type: ignore[arg-type]
            )
