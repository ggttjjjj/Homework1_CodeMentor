# -*- coding: utf-8 -*-
"""Agent 组装工厂：CLI 与 Web 共用的构建入口。"""

from pathlib import Path
from typing import Callable, Optional, Tuple, Union

from .agent import Agent
from .config import Config
from .demos import get_demo_replies
from .llm import AnthropicCompatibleLLM, LLMError, MockLLM, OpenAICompatibleLLM
from .memory import ContextMemory
from .tools import build_registry


class MissingAPIKeyError(ValueError):
    """未配置 API Key，调用方应给出配置引导而不是崩溃。"""


def create_agent(
    provider: str = "api",
    config_path: Optional[str] = None,
    emit: Optional[Callable] = None,
    mode: str = "auto",
) -> Tuple[Agent, Config]:
    """构建 Agent。provider="mock" 时使用离线演示脚本（无需 Key）。"""
    config = Config.load(config_path)

    workspace = Path(config.workspace).resolve()
    if not workspace.is_dir():
        raise ValueError(f"工作区不存在: {workspace}")

    registry = build_registry(str(workspace))
    memory = ContextMemory(max_chars=config.memory_chars)

    if provider == "mock":
        llm: Union[OpenAICompatibleLLM, AnthropicCompatibleLLM, MockLLM] = MockLLM(
            get_demo_replies(mode)
        )
    else:
        if not config.api_key:
            raise MissingAPIKeyError(
                "未配置 API Key：请复制 .env.example 为 .env 并填入 CODEMENTOR_API_KEY"
            )
        llm = (
            AnthropicCompatibleLLM(config)
            if config.protocol == "anthropic"
            else OpenAICompatibleLLM(config)
        )

    agent = Agent(
        llm=llm,
        registry=registry,
        memory=memory,
        mode=mode,
        max_iterations=config.max_iterations,
        emit=emit,
    )
    return agent, config
