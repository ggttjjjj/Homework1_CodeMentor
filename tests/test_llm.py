# -*- coding: utf-8 -*-
"""llm 模块单元测试：重试退避逻辑（通过假 session 模拟，无网络）。"""

import pytest

import codementor.llm as llm_mod
from codementor.config import Config
from codementor.llm import (
    AnthropicCompatibleLLM,
    LLMError,
    MockLLM,
    OpenAICompatibleLLM,
    flatten_messages,
)


def make_llm(max_retries=3):
    cfg = Config(
        api_key="test-key",
        base_url="http://fake/v1",
        model="test-model",
        max_iterations=5,
        request_timeout=5,
        max_retries=max_retries,
        memory_chars=1000,
        workspace=".",
    )
    return OpenAICompatibleLLM(cfg)


class FakeResponse:
    def __init__(self, status, body=""):
        self.status_code = status
        self.text = body

    def json(self):
        return {"choices": [{"message": {"content": "ok-reply"}}]}


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls += 1
        item = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)


class TestRetry:
    def test_retry_on_429_then_success(self):
        llm = make_llm()
        llm.session = FakeSession([FakeResponse(429), FakeResponse(200)])
        assert llm.chat([{"role": "user", "content": "hi"}]) == "ok-reply"
        assert llm.session.calls == 2

    def test_retry_on_network_error(self):
        import requests as requests_mod
        llm = make_llm()
        llm.session = FakeSession([requests_mod.ConnectionError("boom"), FakeResponse(200)])
        assert llm.chat([{"role": "user", "content": "hi"}]) == "ok-reply"

    def test_retries_exhausted_raises(self):
        llm = make_llm(max_retries=2)
        llm.session = FakeSession([FakeResponse(503)])
        with pytest.raises(LLMError, match="已重试 2 次"):
            llm.chat([{"role": "user", "content": "hi"}])
        assert llm.session.calls == 2

    def test_client_error_no_retry(self):
        llm = make_llm()
        llm.session = FakeSession([FakeResponse(401, "unauthorized")])
        with pytest.raises(LLMError, match="401"):
            llm.chat([{"role": "user", "content": "hi"}])
        assert llm.session.calls == 1   # 没有重试

    def test_request_payload_shape(self):
        llm = make_llm()
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured.update(url=url, json=json, headers=headers)
            return FakeResponse(200)

        llm.session = type("S", (), {"post": staticmethod(fake_post)})()
        llm.chat([{"role": "user", "content": "hi"}])
        assert captured["url"] == "http://fake/v1/chat/completions"
        assert captured["json"]["model"] == "test-model"
        assert captured["headers"]["Authorization"] == "Bearer test-key"


class AnthropicResponse:
    def __init__(self, status, body=""):
        self.status_code = status
        self.text = body

    def json(self):
        return {"content": [{"type": "text", "text": "anthropic-ok"}]}


class TestFlattenMessages:
    def test_system_merged_and_roles_kept(self):
        msgs = [
            {"role": "system", "content": "SYS-1"},
            {"role": "system", "content": "SYS-2"},
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
        ]
        system, turns = flatten_messages(msgs)
        assert system == "SYS-1\n\nSYS-2"
        assert turns == [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
        ]

    def test_consecutive_same_role_merged(self):
        # ReAct 的 Observation 以 user 角色注入，可能与相邻 user 消息相连
        msgs = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "任务"},
            {"role": "assistant", "content": "Action: ..."},
            {"role": "user", "content": "Observation: 结果"},
            {"role": "user", "content": "新任务"},
        ]
        system, turns = flatten_messages(msgs)
        assert system == "S"
        assert [t["role"] for t in turns] == ["user", "assistant", "user"]
        assert "Observation: 结果" in turns[-1]["content"]
        assert "新任务" in turns[-1]["content"]

    def test_no_system_returns_none(self):
        system, turns = flatten_messages([{"role": "user", "content": "hi"}])
        assert system is None
        assert turns == [{"role": "user", "content": "hi"}]


class TestAnthropicClient:
    def make_llm(self, max_retries=3):
        cfg = Config(
            api_key="test-key",
            base_url="http://fake/anthropic",
            model="glm-5.3-flash",
            max_iterations=5,
            request_timeout=5,
            max_retries=max_retries,
            memory_chars=1000,
            workspace=".",
            protocol="anthropic",
            max_tokens=4096,
        )
        return AnthropicCompatibleLLM(cfg)

    def test_payload_shape_and_headers(self):
        llm = self.make_llm()
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured.update(url=url, json=json, headers=headers)
            return AnthropicResponse(200)

        llm.session = type("S", (), {"post": staticmethod(fake_post)})()
        messages = [
            {"role": "system", "content": "SYSTEM_PROMPT"},
            {"role": "user", "content": "hi"},
        ]
        assert llm.chat(messages) == "anthropic-ok"
        assert captured["url"] == "http://fake/anthropic/v1/messages"
        body = captured["json"]
        assert body["model"] == "glm-5.3-flash"
        assert body["max_tokens"] == 4096            # anthropic 协议必填
        assert body["system"] == "SYSTEM_PROMPT"     # system 独立字段
        assert body["messages"] == [{"role": "user", "content": "hi"}]
        assert captured["headers"]["x-api-key"] == "test-key"
        assert captured["headers"]["anthropic-version"] == "2023-06-01"

    def test_retry_on_429_then_success(self):
        llm = self.make_llm()
        llm.session = FakeSession([AnthropicResponse(429), AnthropicResponse(200)])
        assert llm.chat([{"role": "user", "content": "hi"}]) == "anthropic-ok"
        assert llm.session.calls == 2

    def test_client_error_no_retry(self):
        llm = self.make_llm()
        llm.session = FakeSession([AnthropicResponse(401, "unauthorized")])
        with pytest.raises(LLMError, match="401"):
            llm.chat([{"role": "user", "content": "hi"}])
        assert llm.session.calls == 1

    def test_error_body_raises_non_retryable(self):
        class ErrResponse(AnthropicResponse):
            def json(self):
                return {"type": "error",
                        "error": {"type": "invalid_request_error", "message": "bad"}}

        llm = self.make_llm(max_retries=2)
        llm.session = FakeSession([ErrResponse(200)])
        with pytest.raises(LLMError, match="bad"):
            llm.chat([{"role": "user", "content": "hi"}])
        assert llm.session.calls == 1   # 不可重试，只调一次


class TestMockLLM:
    def test_scripted_replies_in_order(self):
        mock = MockLLM(["r1", "r2"])
        assert mock.chat([{"role": "user", "content": "a"}]) == "r1"
        assert mock.chat([{"role": "user", "content": "b"}]) == "r2"
        assert len(mock.calls) == 2
        assert mock.calls[0][0]["content"] == "a"

    def test_exhausted_raises(self):
        mock = MockLLM([])
        with pytest.raises(RuntimeError):
            mock.chat([])


class TestTimeoutHint:
    def test_timeout_error_carries_tuning_hint(self):
        import requests as requests_mod
        llm = make_llm(max_retries=2)
        llm.session = FakeSession([requests_mod.ReadTimeout("Read timed out. (read timeout=60)")])
        with pytest.raises(LLMError, match="CODEMENTOR_REQUEST_TIMEOUT"):
            llm.chat([{"role": "user", "content": "hi"}])

    def test_non_timeout_error_has_no_hint(self):
        llm = make_llm(max_retries=2)
        llm.session = FakeSession([FakeResponse(503)])
        with pytest.raises(LLMError) as exc_info:
            llm.chat([{"role": "user", "content": "hi"}])
        assert "REQUEST_TIMEOUT" not in str(exc_info.value)
