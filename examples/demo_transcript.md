# 演示记录：代码审查（mock 离线模式）

> 命令行运行输出。`--provider mock` 模式下模型回复为预置脚本，
> 工具调用与 Observation 为真实执行。配置 API Key 后流程相同。

```text
命令: python main.py --provider mock --mode review -t "请审查 examples/buggy.py 的代码质量"

[提示] mock 演示模式：无需 API Key，模型回复为预置脚本，工具调用为真实执行（演示场景：审查 examples/buggy.py）。
Thought  用户要求审查 examples/buggy.py，我需要先读取该文件的完整内容。
Action   read_file({"path": "examples/buggy.py"})
Observe  examples/buggy.py（共 39 行）:
   1 | # -*- coding: utf-8 -*-
   2 | """演示样本：包含若干典型缺陷的代码，供代码审查 / 测试生成等模式演示使用。
   3 | 
   4 | 刻意埋入的缺陷（评审时可对照）：
   5 | 1. add_item      —— 可变默认参数在多次调用间共享
   6 | 2. average       —— 空列表触发 ZeroDivisionError
   7 | 3. first_index_of —— 循环从 1 开始，漏掉下标 0
   8 | 4. parse_positive —— 裸 except 吞掉所有异常，且混用 -1/None 哨兵值
   9 | """
  10 | 
  11 | 
  12 | def add_item(item, items=[]):
  13 |     """向列表添加元素并返回。"""
  14 |     items.append(item)
  15 |     return items
  16 | 
  17 | 
  18 | def average(numbers):
  19 |     """计算数字列表的平均值。"""
  20 |     return sum(numbers) / len(numbers
...[预览截断，共 1098 字符，--verbose 查看全文]

═══ 最终答复（推理 2 轮，工具调用 1 次）═══
## 代码审查报告：examples/buggy.py

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
- `parse_positive` 的异常语义与返回值语义二选一后，调用方代码会更简洁。
```
