# -*- coding: utf-8 -*-
"""examples/buggy_refactored.py 的行为验证测试。"""

import pytest

from examples.buggy_refactored import (
    add_item,
    average,
    first_index_of,
    parse_positive,
)


class TestAddItem:
    def test_no_items_creates_new_list_each_call(self):
        """重构点1：不传 items 时每次新建列表，不再跨调用共享。"""
        first = add_item(1)
        second = add_item(2)
        assert first == [1]
        assert second == [2]

    def test_with_existing_list_appends_in_place(self):
        items = ["a"]
        result = add_item("b", items)
        assert result is items
        assert items == ["a", "b"]


class TestAverage:
    def test_normal(self):
        assert average([1, 2, 3]) == pytest.approx(2.0)

    def test_empty_raises_value_error(self):
        """重构点2：空列表显式抛 ValueError，而非 ZeroDivisionError。"""
        with pytest.raises(ValueError):
            average([])


class TestFirstIndexOf:
    def test_finds_first_element(self):
        """重构点3：下标 0 也要参与匹配（修复原版 bug）。"""
        assert first_index_of("a", ["a", "b"]) == 0

    def test_finds_middle(self):
        assert first_index_of(2, [1, 2, 3]) == 1

    def test_returns_minus_one_when_missing(self):
        assert first_index_of("z", ["a", "b"]) == -1

    def test_empty_items(self):
        assert first_index_of(1, []) == -1


class TestParsePositive:
    @pytest.mark.parametrize("text", ["3", " 10 "])
    def test_valid_positive(self, text):
        assert parse_positive(text) == int(text)

    @pytest.mark.parametrize("text", ["0", "-5"])
    def test_non_positive_returns_none(self, text):
        assert parse_positive(text) is None

    @pytest.mark.parametrize("text", ["abc", None, [1, 2]])
    def test_invalid_returns_none(self, text):
        """重构点4：非法输入返回 None，且不会抛出未处理异常。"""
        assert parse_positive(text) is None

    def test_float_is_truncated_current_behavior(self):
        """待确认项：int(3.5) 隐式截断为 3，这是原版即有的行为。

        若业务上认为浮点输入应视为非法，可在 parse_positive 中
        增加 isinstance 检查并让此测试改为断言返回 None。
        """
        assert parse_positive(3.5) == 3
