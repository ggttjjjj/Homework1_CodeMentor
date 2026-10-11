# -*- coding: utf-8 -*-
"""Agent 核心：ReAct 循环（输入 -> 推理 -> 工具调用 -> 观察 -> ... -> 输出）。

中间过程通过 emit(kind, **data) 回调发布给 UI 层（CLI / Web / 测试），
Agent 不依赖任何具体展示方式。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

from .llm import LLMError
from .memory import ContextMemory
from .parsing import parse_reply
from .prompts import MODES, build_system_prompt
from .tools.base import ToolRegistry

logger = logging.getLogger(__name__)

# llm 客户端内部已带重试，Agent 层额外再尝试一次
EXTRA_CHAT_ATTEMPTS = 1


class LLMClient(Protocol):
    """Agent 依赖的最小 LLM 接口。"""

    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.3) -> str: ...

FORMAT_ERROR_HINT = (
    "错误: 无法从你的回复中解析出 Action 或 Final Answer。"
    "请复制以下模板之一回复（不要添加其他格式）：\n"
    '调用工具: Action: {"tool": "工具名", "args": {"参数": "值"}}\n'
    "结束任务: Final Answer: <给用户的答复>"
)

# 连续格式解析失败上限（不占用推理轮数，超限强制总结）
MAX_FORMAT_RETRIES = 4

# 事件回调类型
EmitFn = Callable[..., None]


@dataclass
class Step:
    """一轮推理的记录。"""

    index: int
    thought: str
    tool: Optional[str]
    args: Dict[str, Any] = field(default_factory=dict)
    observation: Optional[str] = None
    raw: str = ""


@dataclass
class AgentResult:
    """一次任务的最终结果。"""

    final_answer: str
    steps: List[Step] = field(default_factory=list)
    iterations: int = 0
    truncated: bool = False  # True 表示达到轮数上限被强制总结

    @property
    def tool_calls(self) -> List[str]:
        return [s.tool for s in self.steps if s.tool]


class Agent:
    """ReAct 式代码助手 Agent。

    :param llm: 任意实现 chat(messages) 的客户端
    :param registry: 工具注册表
    :param memory: 跨轮次上下文记忆
    :param mode: 工作模式，见 prompts.MODES
    :param max_iterations: 单次任务最大推理轮数
    :param emit: 事件回调 emit(kind, **data)
    """

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        memory: ContextMemory,
        mode: str = "auto",
        max_iterations: int = 8,
        emit: Optional[EmitFn] = None,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.memory = memory
        self.max_iterations = max(1, int(max_iterations))
        self._emit_fn = emit or (lambda *a, **k: None)
        self._mode = ""
        self.mode = mode  # 通过 setter 校验并构建系统提示词

    # ------------------------------------------------------------ 模式

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        if value not in MODES:
            raise ValueError(f"未知模式 '{value}'，可用: {', '.join(MODES)}")
        self._mode = value
        self._system_prompt = build_system_prompt(
            value, self.registry, self.max_iterations
        )

    @property
    def emit_handler(self) -> EmitFn:
        return self._emit_fn

    @emit_handler.setter
    def emit_handler(self, handler: Optional[EmitFn]) -> None:
        """运行期替换事件回调（Web 服务在重建 Agent 后重新绑定）。"""
        self._emit_fn = handler or (lambda *a, **k: None)

    # ------------------------------------------------------------ 事件

    def emit(self, kind: str, **data: Any) -> None:
        try:
            self._emit_fn(kind, **data)
        except Exception:  # UI 回调异常不影响 Agent 运行
            logger.debug("emit 回调异常 kind=%s", kind, exc_info=True)

    def _chat(self, messages: List[Dict[str, str]]) -> str:
        for attempt in range(EXTRA_CHAT_ATTEMPTS + 1):
            try:
                return self.llm.chat(messages)
            except LLMError as e:
                if attempt >= EXTRA_CHAT_ATTEMPTS:
                    raise
                self.emit("llm_retry", attempt=attempt + 1, error=str(e))

    # ------------------------------------------------------------ 主循环

    def run(self, user_input: str) -> AgentResult:
        """执行一次任务。max_iterations 限制有效推理轮数（工具调用），
        格式解析失败单独计数不占用预算，超限则强制总结。"""
        if not user_input.strip():
            raise ValueError("用户输入不能为空")

        self.memory.add("user", user_input)
        self.emit("episode_start", task=user_input)
        steps: List[Step] = []
        productive = 0
        format_failures = 0
        calls = 0

        while productive < self.max_iterations:
            if format_failures >= MAX_FORMAT_RETRIES:
                self.emit("error", message="连续格式解析失败过多，提前收尾")
                break
            calls += 1
            reply = self._chat(self.memory.build_messages(self._system_prompt))
            parsed = parse_reply(reply)

            # ---- 分支一：给出最终答案，任务结束 ----
            if parsed.tool is None and parsed.final is not None:
                self.memory.add("assistant", parsed.final)
                self.emit(
                    "final",
                    answer=parsed.final,
                    iterations=calls,
                    truncated=False,
                    thought=parsed.thought,
                )
                return AgentResult(
                    parsed.final, steps, iterations=calls, truncated=False
                )

            # ---- 分支二：调用工具 / 解析失败 ----
            if parsed.tool is not None:
                productive += 1
                format_failures = 0
                self.emit(
                    "action",
                    iteration=calls,
                    thought=parsed.thought,
                    tool=parsed.tool,
                    args=parsed.args,
                )
                observation = self.registry.execute(parsed.tool, parsed.args)
            else:
                format_failures += 1
                self.emit("parse_error", iteration=calls, raw=reply)
                observation = FORMAT_ERROR_HINT

            self.emit("observation", iteration=calls, text=observation)
            self.memory.add("assistant", reply)
            self.memory.add("user", f"Observation: {observation}")
            steps.append(
                Step(
                    index=calls,
                    thought=parsed.thought,
                    tool=parsed.tool,
                    args=parsed.args,
                    observation=observation,
                    raw=reply,
                )
            )

        # ---- 达到轮数上限 / 格式失败超限：强制总结 ----
        return self._force_final_answer(steps, calls)

    def _force_final_answer(self, steps: List[Step], calls: int) -> AgentResult:
        """预算耗尽后注入指令，强制基于已有观察收尾。"""
        self.memory.add(
            "user",
            "系统提示：已达到最大推理轮数，禁止再调用工具，"
            "请立即基于以上 Observation 给出 Final Answer。",
        )
        reply = self._chat(self.memory.build_messages(self._system_prompt))
        parsed = parse_reply(reply)
        final = parsed.final if parsed.final is not None else reply.strip()
        self.memory.add("assistant", final)
        self.emit(
            "final",
            answer=final,
            iterations=calls + 1,
            truncated=True,
            thought=parsed.thought,
        )
        return AgentResult(final, steps, iterations=calls + 1, truncated=True)
