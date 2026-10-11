# -*- coding: utf-8 -*-
"""模型回复解析：从 ReAct 文本中提取 Thought / Action / Final Answer。

协议格式（见 prompts.py）：

    Thought: <推理>
    Action: {"tool": "<工具名>", "args": {...}}
    Final Answer: <最终答复>

对模型输出的格式漂移做了容错：JSON 提取用括号配平扫描而非整行解析，
支持代码块包裹与朴素两行式写法，常见 JSON 瑕疵（尾逗号等）自动修复。
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

ACTION_HEAD_RE = re.compile(r"^[ \t]*Action\s*[:：]", re.M)
ACTION_PLAIN_RE = re.compile(r"^[ \t]*Action\s*[:：]\s*([A-Za-z_][A-Za-z0-9_]*)[ \t]*$", re.M)
ARGS_HEAD_RE = re.compile(r"^[ \t]*Args\s*[:：]\s*", re.M)
FINAL_RE = re.compile(r"^[ \t]*(?:\*\*)?Final\s*Answer(?:\*\*)?\s*[:：]", re.M | re.I)
THOUGHT_PREFIX_RE = re.compile(
    r"^[ \t]*(?:\*\*)?Thought(?:\*\*)?\s*[:：]?", re.I
)


@dataclass
class ParsedReply:
    """一次回复的解析结果。tool 与 final 互斥，均为 None 表示解析失败。"""

    thought: str = ""
    tool: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)
    final: Optional[str] = None


def parse_reply(reply: str) -> ParsedReply:
    """解析一条模型回复，永远不会抛异常。"""
    final_match = FINAL_RE.search(reply)

    # Action 优先：模型可能习惯在结尾顺手写 "Final Answer" 字样
    tool, args, marker_start = _extract_action(reply)
    if tool:
        thought = _clean_thought(reply[:marker_start])
        return ParsedReply(thought=thought, tool=tool, args=args)

    if final_match:
        final = reply[final_match.end():].strip().lstrip("*").strip()
        thought = _clean_thought(reply[: final_match.start()])
        return ParsedReply(thought=thought, final=final)

    return ParsedReply(thought=_clean_thought(reply))


# ---------------------------------------------------------------- JSON 容错

def _try_loads(text: str) -> Optional[Any]:
    """逐级尝试修复并解析 JSON。"""
    candidates = [text]
    # 去掉可能残留的代码围栏
    fenced = re.sub(r"```[a-zA-Z]*|```", "", text).strip()
    if fenced != text:
        candidates.append(fenced)
    # 去尾逗号：{"a": 1,} / [1, 2,]
    no_trailing = re.sub(r",\s*([}\]])", r"\1", candidates[-1])
    if no_trailing != candidates[-1]:
        candidates.append(no_trailing)
    # 中文引号 -> 英文引号（放在最后，避免破坏正常字符串内容）
    quoted = candidates[-1].replace("\u201c", '"').replace("\u201d", '"')
    if quoted != candidates[-1]:
        candidates.append(quoted)

    for cand in candidates:
        try:
            return json.loads(cand)
        except ValueError:  # JSONDecodeError 是其子类
            continue
    return None


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """定位第一个括号配平的 JSON 对象并解析（跟踪字符串/转义状态）。"""
    start = text.find("{")
    while start != -1:
        depth, in_str, escape = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        obj = _try_loads(text[start : i + 1])
                        if isinstance(obj, dict):
                            return obj
                        break  # 配平失败/不是对象，换下一个 '{'
        start = text.find("{", start + 1)
    return None


# ---------------------------------------------------------------- 内部工具

def _extract_action(reply: str) -> Tuple[Optional[str], Dict[str, Any], int]:
    """提取工具调用，返回 (tool, args, Action 标记位置)。

    两遍扫描：先在所有 Action 标记中找合法 JSON 形式（规范的调用写法），
    再退回 "Action: 工具名 + Args:" 两行式，避免 Thought 中引用的
    格式示例被误认为真实调用。
    """
    markers = list(ACTION_HEAD_RE.finditer(reply))

    # 第一遍：JSON 形式
    for head_match in markers:
        obj = extract_json_object(reply[head_match.end():])
        if obj and isinstance(obj.get("tool"), str):
            args = obj.get("args", {})
            if not isinstance(args, dict):
                args = {}
            return obj["tool"].strip(), args, head_match.start()

    # 第二遍：朴素两行式
    for head_match in markers:
        line_start = reply.rfind("\n", 0, head_match.start()) + 1
        plain = ACTION_PLAIN_RE.search(reply, line_start)
        if plain:
            args: Dict[str, Any] = {}
            args_match = ARGS_HEAD_RE.search(reply, plain.end())
            if args_match:
                obj = extract_json_object(reply[args_match.end():])
                if isinstance(obj, dict):
                    args = obj
            return plain.group(1), args, head_match.start()

    # 没有任何 Action 标记携带合法的工具调用
    return None, {}, 0


def _clean_thought(text: str) -> str:
    """去掉 Thought 前缀与多余空白，提取纯推理文本。"""
    text = text.strip()
    if not text:
        return ""
    return THOUGHT_PREFIX_RE.sub("", text, count=1).strip()
