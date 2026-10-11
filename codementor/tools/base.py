# -*- coding: utf-8 -*-
"""工具抽象层：Tool 定义与注册表。

工具自描述（名称/描述/参数/示例），注册表据此自动生成给 LLM 的文档；
执行不抛异常，错误转为以"错误:"开头的观察返回，让 Agent 自行修正；
超长输出自动截断。
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# 单条 Observation 的最大字符数（超出保留头尾）
MAX_OBSERVATION_CHARS = 3000
_KEEP_HEAD = 2600
_KEEP_TAIL = 300


@dataclass
class Tool:
    """一个可被 Agent 调用的工具。"""

    name: str
    description: str
    parameters: Dict[str, Dict[str, str]]
    func: Callable[..., str]
    example: str = ""


def truncate_observation(text: str) -> str:
    """超长观察结果截断，保留头尾。"""
    if len(text) <= MAX_OBSERVATION_CHARS:
        return text
    head, tail = text[:_KEEP_HEAD], text[-_KEEP_TAIL:]
    return (
        f"{head}\n\n...[输出过长，已截断：展示头 {_KEEP_HEAD} 字符 + 尾 {_KEEP_TAIL} 字符，"
        f"完整长度 {len(text)} 字符]...\n\n{tail}"
    )


class ToolRegistry:
    """工具注册表：注册、查询、生成文档、安全执行。"""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    @property
    def names(self) -> List[str]:
        return list(self._tools)

    def docs(self) -> str:
        """生成给 LLM 的工具文档。"""
        lines = []
        for tool in self._tools.values():
            params = ", ".join(
                f'{name}({spec.get("type", "string")}): {spec.get("description", "")}'
                for name, spec in tool.parameters.items()
            )
            lines.append(f"- {tool.name}({params})\n  {tool.description}")
            if tool.example:
                lines.append(f"  调用示例: {tool.example}")
        return "\n".join(lines)

    def execute(self, name: str, args: Optional[Dict[str, Any]] = None) -> str:
        """执行工具，异常转为错误观察字符串返回。"""
        if not isinstance(args, dict):
            args = {}
        tool = self._tools.get(name)
        if tool is None:
            return f"错误: 未知工具 '{name}'。可用工具: {', '.join(self._tools)}"
        try:
            result = tool.func(**args)
        except TypeError as e:
            return (
                f"错误: 工具 '{name}' 参数不匹配: {e}。"
                f"参数说明: {self._param_help(tool)}"
            )
        except Exception as e:
            return f"错误: 工具 '{name}' 执行失败 [{type(e).__name__}]: {e}"
        return truncate_observation(str(result))

    @staticmethod
    def _param_help(tool: Tool) -> str:
        return "; ".join(
            f"{name}({spec.get('type', 'string')})" for name, spec in tool.parameters.items()
        ) or "无参数"
