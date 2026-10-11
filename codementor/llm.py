# -*- coding: utf-8 -*-
"""LLM 客户端：OpenAI 与 Anthropic 两种协议，统一的 chat() 接口。

网络错误与 429/5xx 指数退避重试；400/401 等客户端错误不重试直接抛出。
"""

import random
import time
from typing import Callable, Dict, List, Optional, Tuple

try:
    import requests
except ImportError as e:  # pragma: no cover - 环境缺依赖时给出友好提示
    raise ImportError(
        "缺少依赖 requests，请先执行: pip install -r requirements.txt"
    ) from e

from .config import Config

# 可重试的 HTTP 状态码
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

ANTHROPIC_VERSION = "2023-06-01"


class LLMError(Exception):
    """LLM 调用失败。retryable=False 表示重试无意义（如鉴权失败）。"""

    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def _with_retries(max_retries: int, call: Callable[[], str]) -> str:
    """按 retryable 标志做指数退避重试。"""
    last_error: Exception = LLMError("未知的调用失败")
    for attempt in range(1, max_retries + 1):
        try:
            return call()
        except LLMError as e:
            if not e.retryable:
                raise
            last_error = e
            if attempt < max_retries:
                delay = min(2.0 ** attempt + random.random(), 15.0)
                time.sleep(delay)
    message = f"LLM 调用失败（已重试 {max_retries} 次）: {last_error}"
    if "timed out" in str(last_error) or "timeout" in str(last_error).lower():
        message += "（请求超时：任务上下文较大时生成较慢，可在 .env 中调大 CODEMENTOR_REQUEST_TIMEOUT）"
    raise LLMError(message)


def _classify_response(resp: "requests.Response") -> None:
    """按状态码分类：可重试的抛 retryable 错误，客户端错误抛不可重试错误。"""
    if resp.status_code in RETRYABLE_STATUS:
        raise LLMError(
            f"服务暂时不可用（HTTP {resp.status_code}）: {resp.text[:200]}"
        )
    if resp.status_code != 200:
        # 401/403/404 等客户端错误重试无意义，直接失败
        raise LLMError(
            f"请求被拒绝（HTTP {resp.status_code}）: {resp.text[:300]}",
            retryable=False,
        )


class OpenAICompatibleLLM:
    """OpenAI 兼容 Chat Completions 客户端。"""

    def __init__(self, config: Config):
        self.config = config
        self.session = requests.Session()

    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.3) -> str:
        """发送对话，返回回复文本。messages 为 [{"role", "content"}] 列表。"""
        url = self.config.base_url + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
        }
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        def call() -> str:
            try:
                resp = self.session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self.config.request_timeout,
                )
            except requests.RequestException as e:
                raise LLMError(f"网络错误: {e}")
            _classify_response(resp)
            try:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError) as e:
                raise LLMError(f"响应格式异常: {e}")
            if isinstance(content, str) and content.strip():
                return content
            raise LLMError("模型返回内容为空")

        return _with_retries(self.config.max_retries, call)


def flatten_messages(
    messages: List[Dict[str, str]],
) -> Tuple[Optional[str], List[Dict[str, str]]]:
    """OpenAI 风格 messages 转 Anthropic 风格：system 独立、合并连续同角色。"""
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    turns: List[Dict[str, str]] = []
    for m in messages:
        if m["role"] == "system":
            continue
        if turns and turns[-1]["role"] == m["role"]:
            turns[-1]["content"] += "\n\n" + m["content"]
        else:
            turns.append({"role": m["role"], "content": m["content"]})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, turns


class AnthropicCompatibleLLM:
    """Anthropic Messages 协议客户端（智谱 GLM Coding 套餐 / Claude 等）。"""

    def __init__(self, config: Config):
        self.config = config
        self.session = requests.Session()

    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.3) -> str:
        url = self.config.base_url.rstrip("/") + "/v1/messages"
        system, turns = flatten_messages(messages)
        payload: Dict = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": turns,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["x-api-key"] = self.config.api_key
            headers["anthropic-version"] = ANTHROPIC_VERSION

        def call() -> str:
            try:
                resp = self.session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self.config.request_timeout,
                )
            except requests.RequestException as e:
                raise LLMError(f"网络错误: {e}")
            _classify_response(resp)
            try:
                data = resp.json()
            except ValueError as e:
                raise LLMError(f"响应格式异常: {e}")
            if data.get("type") == "error":
                raise LLMError(
                    f"服务端返回错误: {data.get('error', {}).get('message', '')}",
                    retryable=False,
                )
            try:
                text = "".join(
                    block.get("text", "")
                    for block in data.get("content", [])
                    if block.get("type") == "text"
                )
            except AttributeError as e:
                raise LLMError(f"响应格式异常: {e}")
            if text.strip():
                return text
            raise LLMError("模型返回内容为空")

        return _with_retries(self.config.max_retries, call)


class MockLLM:
    """离线演示 / 测试用假 LLM：按顺序返回预设回复，记录每次收到的 messages。"""

    def __init__(self, replies: List[str]):
        self.replies = list(replies)
        self.calls: List[List[Dict[str, str]]] = []

    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.3) -> str:
        self.calls.append([dict(m) for m in messages])
        if not self.replies:
            raise RuntimeError("MockLLM: 预设回复已耗尽，请补充更多脚本回复")
        return self.replies.pop(0)
