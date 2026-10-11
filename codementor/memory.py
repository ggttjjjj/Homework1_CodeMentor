# -*- coding: utf-8 -*-
"""上下文记忆：完整保留近期对话，超预算的最旧内容压缩进滚动摘要。"""

from dataclasses import dataclass
from typing import Dict, List

SUMMARY_CAP = 3000          # 摘要总长度上限
KEEP_USER_CHARS = 160       # 压缩后的用户消息保留长度
KEEP_ASSISTANT_CHARS = 400  # 压缩后的助手结论保留长度
KEEP_OBS_CHARS = 80         # 压缩后的工具观察保留长度


@dataclass
class Turn:
    role: str      # "user" | "assistant"
    content: str


class ContextMemory:
    """跨轮次对话记忆。"""

    def __init__(self, max_chars: int = 24000) -> None:
        self.max_chars = max_chars
        self.turns: List[Turn] = []
        self.summary: str = ""

    # ------------------------------------------------------------ 写入

    def add(self, role: str, content: str) -> None:
        self.turns.append(Turn(role=role, content=content))
        self._evict_over_budget()

    def clear(self) -> None:
        self.turns.clear()
        self.summary = ""

    # ------------------------------------------------------------ 压缩

    def _evict_over_budget(self) -> None:
        total = sum(len(t.content) for t in self.turns)
        while total > self.max_chars and len(self.turns) > 1:
            oldest = self.turns.pop(0)
            total -= len(oldest.content)
            self.summary = self._append_summary(self.summary, oldest)

    @staticmethod
    def _brief(turn: Turn) -> str:
        if turn.role == "user":
            if turn.content.startswith("Observation:"):
                body = turn.content[len("Observation:"):].strip()
                return f"[观察] {body[:KEEP_OBS_CHARS]}"
            return f"[用户] {turn.content[:KEEP_USER_CHARS]}"
        return f"[助手] {turn.content[:KEEP_ASSISTANT_CHARS]}"

    @staticmethod
    def _append_summary(summary: str, turn: Turn) -> str:
        piece = ContextMemory._brief(turn)
        merged = f"{summary}\n{piece}".strip()
        if len(merged) > SUMMARY_CAP:
            merged = merged[-SUMMARY_CAP:]
            # 截断点可能落在半行上，去掉不完整的首行
            newline = merged.find("\n")
            merged = merged[newline + 1:] if newline != -1 else merged
        return merged

    # ------------------------------------------------------------ 读取

    def build_messages(self, system_prompt: str) -> List[Dict[str, str]]:
        """构造发送给 LLM 的 messages。"""
        messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if self.summary:
            messages.append(
                {
                    "role": "system",
                    "content": f"[更早对话的压缩摘要]\n{self.summary}",
                }
            )
        messages.extend(
            {"role": turn.role, "content": turn.content} for turn in self.turns
        )
        return messages

    def view(self, last_n: int = 12) -> str:
        """/history 命令用的历史预览。"""
        lines = []
        for turn in self.turns[-last_n:]:
            who = {"user": "用户", "assistant": "助手"}.get(turn.role, turn.role)
            preview = turn.content.replace("\n", " ")[:80]
            lines.append(f"{who:>4}: {preview}")
        if self.summary:
            lines.insert(0, f"(已压缩 {len(self.summary)} 字符的更早历史)")
        return "\n".join(lines) if lines else "（暂无历史记录）"
