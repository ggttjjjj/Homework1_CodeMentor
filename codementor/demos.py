# -*- coding: utf-8 -*-
"""离线演示脚本（--provider mock 使用，无需 API Key）。

脚本第一轮让 Agent 调用 read_file 真实读取 examples/buggy.py，
工具层与 Observation 均为真实执行；只有"模型的回复"是预置的，
用于在无网络环境下演示完整的 ReAct 循环。
"""

REVIEW_DEMO_REPLIES = [
    # 第 1 轮：请求读取目标文件
    (
        "Thought: 用户要求审查 examples/buggy.py，我需要先读取该文件的完整内容。\n"
        'Action: {"tool": "read_file", "args": {"path": "examples/buggy.py"}}'
    ),
    # 第 2 轮：基于真实 Observation 给出审查报告
    '''Thought: 文件内容已获取，共 4 个函数。逐个分析后发现 4 处典型缺陷：可变默认参数、空列表除零、循环边界差一、裸 except 吞异常。下面给出完整报告。
Final Answer: ## 代码审查报告：examples/buggy.py

整体结构清晰、命名规范，但存在 **2 处高危、2 处中危** 缺陷，均已在源码中定位。

### 问题清单

| # | 严重度 | 位置 | 问题 | 修复建议 |
|---|--------|------|------|----------|
| 1 | 高 | `add_item()` 第 12 行 | 可变默认参数 `items=[]`：默认列表在多次调用间共享，上一次调用的元素会残留到下一次 | 改为 `items=None`，函数体内初始化 `items = [] if items is None else items` |
| 2 | 高 | `average()` 第 18-20 行 | 空列表触发 `ZeroDivisionError`，未做入参防护 | 入参为空时抛出 `ValueError("numbers 不能为空")`，让错误尽早暴露 |
| 3 | 中 | `first_index_of()` 第 25 行 | `range(1, len(items))` 跳过下标 0，目标是首元素时错误返回 -1 | 改为 `range(len(items))`，或直接使用 `items.index(target)` + 捕获 `ValueError` |
| 4 | 中 | `parse_positive()` 第 35-36 行 | 裸 `except:` 会吞掉所有异常（包括 `KeyboardInterrupt`），且 -1/None 双哨兵值语义混乱 | 只捕获 `ValueError`；统一失败策略（建议抛 `ValueError` 而非返回魔法值） |

### 修复后的参考实现

```python
def add_item(item, items=None):
    """向列表添加元素并返回新列表。"""
    items = [] if items is None else items
    items.append(item)
    return items


def average(numbers):
    """计算平均值；空列表抛出 ValueError。"""
    if not numbers:
        raise ValueError("numbers 不能为空")
    return sum(numbers) / len(numbers)


def first_index_of(target, items):
    """返回 target 的下标，找不到返回 -1。"""
    for i, item in enumerate(items):
        if item == target:
            return i
    return -1


def parse_positive(text):
    """把文本解析为正整数；格式非法抛出 ValueError。"""
    try:
        value = int(text)
    except ValueError:
        raise ValueError(f"{text!r} 不是合法整数")
    if value <= 0:
        raise ValueError(f"{value} 不是正整数")
    return value
```

### 进一步建议

- 为修复后的函数补充 pytest 单元测试（可以让我切换到【测试生成】模式自动完成）；
- `parse_positive` 的异常语义与返回值语义二选一后，调用方代码会更简洁。''',
]

MOCK_PROVIDERS = {"review": REVIEW_DEMO_REPLIES, "auto": REVIEW_DEMO_REPLIES}


def get_demo_replies(mode: str):
    """按模式返回演示脚本；不支持的模式回退到审查演示。"""
    return MOCK_PROVIDERS.get(mode, REVIEW_DEMO_REPLIES)
