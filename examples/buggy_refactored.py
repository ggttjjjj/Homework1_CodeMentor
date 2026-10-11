# -*- coding: utf-8 -*-
"""重构示例：examples/buggy.py 的重构版本。

相对原版的改动（均为有意行为变化，详见审查报告）：
1. add_item       —— 去掉可变默认参数，未传 items 时每次新建列表
2. average        —— 空列表显式抛 ValueError（原为隐式 ZeroDivisionError）
3. first_index_of —— 从下标 0 开始匹配（修复原版漏掉首元素的 bug）
4. parse_positive —— 只捕获 ValueError/TypeError，删除 -1 哨兵中间值
"""


def add_item(item, items=None):
    """向列表添加元素并返回。

    未传 items 时基于新列表操作；传入列表时原地修改并返回原列表。
    """
    if items is None:
        items = []
    items.append(item)
    return items


def average(numbers):
    """计算数字列表的平均值；空列表抛 ValueError。"""
    if not numbers:
        raise ValueError("average() arg is an empty sequence")
    return sum(numbers) / len(numbers)


def first_index_of(target, items):
    """返回 target 在 items 中的首个下标，找不到返回 -1。"""
    for i, item in enumerate(items):
        if item == target:
            return i
    return -1


def parse_positive(text):
    """把文本解析为正整数，非法输入返回 None。"""
    try:
        value = int(text)
    except (ValueError, TypeError):
        return None
    return value if value > 0 else None
