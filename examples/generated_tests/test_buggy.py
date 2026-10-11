import pytest
from examples.buggy import add_item, average, first_index_of, parse_positive


class TestAddItem:
    """测试 add_item 函数"""
    
    def test_add_item_normal(self):
        """测试正常添加元素"""
        items = [1, 2, 3]
        result = add_item(4, items)
        assert result == [1, 2, 3, 4]
    
    def test_add_item_empty_list(self):
        """测试向空列表添加元素"""
        result = add_item(1, [])
        assert result == [1]
    
    def test_add_item_default_param(self):
        """测试默认参数的可变性问题"""
        # 第一次调用
        result1 = add_item(1)
        # 第二次调用，应该不共享默认列表
        result2 = add_item(2)
        assert result1 == [1]
        assert result2 == [1, 2]
    
    def test_add_item_none_items(self):
        """测试None作为items参数"""
        with pytest.raises(AttributeError):
            add_item(1, None)


class TestAverage:
    """测试 average 函数"""
    
    def test_average_normal(self):
        """测试正常数字列表的平均值"""
        assert average([1, 2, 3, 4, 5]) == 3.0
    
    def test_average_single_element(self):
        """测试单元素列表的平均值"""
        assert average([10]) == 10.0
    
    def test_average_empty_list(self):
        """测试空列表应该抛出ZeroDivisionError"""
        with pytest.raises(ZeroDivisionError):
            average([])


class TestFirstIndexOf:
    """测试 first_index_of 函数"""
    
    def test_first_index_of_found(self):
        """测试找到目标元素"""
        assert first_index_of(3, [1, 2, 3, 4, 5]) == 2
    
    def test_first_index_of_first_element(self):
        """测试目标在第一个位置"""
        assert first_index_of(1, [1, 2, 3]) == 0
    
    def test_first_index_of_last_element(self):
        """测试目标在最后一个位置"""
        assert first_index_of(5, [1, 2, 3, 4, 5]) == 4
    
    def test_first_index_of_not_found(self):
        """测试目标不存在"""
        assert first_index_of(6, [1, 2, 3]) == -1
    
    def test_first_index_of_empty_list(self):
        """测试空列表"""
        assert first_index_of(1, []) == -1
    
    def test_first_index_of_duplicate(self):
        """测试重复元素，应该返回第一个出现的索引"""
        assert first_index_of(2, [1, 2, 3, 2]) == 1


class TestParsePositive:
    """测试 parse_positive 函数"""
    
    def test_parse_positive_normal(self):
        """测试正常正整数文本"""
        assert parse_positive("42") == 42
    
    def test_parse_positive_boundary_min(self):
        """测试最小正整数"""
        assert parse_positive("1") == 1
    
    def test_parse_positive_negative(self):
        """测试负数"""
        assert parse_positive("-5") is None
    
    def test_parse_positive_zero(self):
        """测试零"""
        assert parse_positive("0") is None
    
    def test_parse_positive_non_numeric(self):
        """测试非数字文本"""
        assert parse_positive("abc") is None
    
    def test_parse_positive_empty_string(self):
        """测试空字符串"""
        assert parse_positive("") is None
    
    def test_parse_positive_whitespace(self):
        """测试空白字符串"""
        assert parse_positive("   ") is None
    
    def test_parse_positive_float(self):
        """测试浮点数"""
        assert parse_positive("3.14") is None
    
    def test_parse_positive_negative_zero(self):
        """测试负零"""
        assert parse_positive("-0") is None
    
    def test_parse_positive_large_number(self):
        """测试大数字"""
        assert parse_positive("999999999999999999999") == 999999999999999999999