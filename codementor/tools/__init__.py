# -*- coding: utf-8 -*-
"""工具包入口：统一的注册表构建入口。"""

from typing import List

from .base import Tool, ToolRegistry, truncate_observation
from .code_tools import build_code_tools
from .fs_tools import build_fs_tools

__all__ = [
    "Tool",
    "ToolRegistry",
    "truncate_observation",
    "build_registry",
    "build_fs_tools",
    "build_code_tools",
]


def build_registry(workspace: str) -> ToolRegistry:
    """构建绑定到指定工作区的默认工具集（文件系统 + 代码执行）。"""
    registry = ToolRegistry()
    tools: List[Tool] = build_fs_tools(workspace) + build_code_tools(workspace)
    for tool in tools:
        registry.register(tool)
    return registry
