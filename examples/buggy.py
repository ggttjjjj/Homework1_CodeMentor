# -*- coding: utf-8 -*-
"""演示样本：包含若干典型缺陷的代码，供代码审查 / 测试生成等模式演示使用。

刻意埋入的缺陷（评审时可对照）：
1. add_item      —— 可变默认参数在多次调用间共享
2. average       —— 空列表触发 ZeroDivisionError
3. first_index_of —— 循环从 1 开始，漏掉下标 0
4. parse_positive —— 裸 except 吞掉所有异常，且混用 -1/None 哨兵值
"""


def add_item(item, items=[]):
    """向列表添加元素并返回。"""
    items.append(item)
    return items


def average(numbers):
    """计算数字列表的平均值。"""
    return sum(numbers) / len(numbers)


def first_index_of(target, items):
    """返回 target 在 items 中的下标，找不到返回 -1。"""
    for i in range(1, len(items)):
        if items[i] == target:
            return i
    return -1


def parse_positive(text):
    """把文本解析为正整数，非法输入返回 None。"""
    try:
        value = int(text)
    except:
        value = -1
    if value <= 0:
        return None
    return value
