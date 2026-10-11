# -*- coding: utf-8 -*-
"""web 模块接口测试：用注入的 Mock Agent 驱动完整 Web 流程（无网络）。"""

import time

import pytest

from codementor.agent import Agent
from codementor.llm import MockLLM
from codementor.memory import ContextMemory
from codementor.tools import build_registry
from web import create_app


def make_client(tmp_path, replies=None):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    llm = MockLLM(replies or [
        'Thought: 读文件\nAction: {"tool": "read_file", "args": {"path": "a.py"}}',
        "Final Answer: 文件定义了函数 f。",
    ])
    agent = Agent(
        llm=llm,
        registry=build_registry(str(tmp_path)),
        memory=ContextMemory(),
        mode="auto",
    )
    app = create_app(agent=agent)
    return app.test_client(), agent


def wait_done(client, task_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/task/{task_id}?since=0")
        assert resp.status_code == 200
        data = resp.get_json()
        if data["done"]:
            return data
        time.sleep(0.05)
    pytest.fail("任务在超时时间内没有完成")


class TestPages:
    def test_index_served(self, tmp_path):
        client, _ = make_client(tmp_path)
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"CodeMentor" in resp.data

    def test_static_css(self, tmp_path):
        client, _ = make_client(tmp_path)
        resp = client.get("/static/style.css")
        assert resp.status_code == 200


class TestStatus:
    def test_status_shape(self, tmp_path):
        client, _ = make_client(tmp_path)
        data = client.get("/api/status").get_json()
        assert data["configured"] is True
        assert data["mode"] == "auto"
        assert len(data["modes"]) == 6
        assert {"id": "review", "label": "代码审查"} in data["modes"]
        tool_names = [t["name"] for t in data["tools"]]
        assert "read_file" in tool_names and "run_tests" in tool_names

    def test_unconfigured_banner_state(self):
        app = create_app(unconfigured=True)
        client = app.test_client()
        data = client.get("/api/status").get_json()
        assert data["configured"] is False
        resp = client.post("/api/chat", json={"message": "hi"})
        assert resp.status_code == 503
        assert ".env" in resp.get_json()["error"]


class TestChatFlow:
    def test_full_episode(self, tmp_path):
        client, agent = make_client(tmp_path)
        resp = client.post("/api/chat", json={"message": "看看 a.py"})
        assert resp.status_code == 202
        task_id = resp.get_json()["task_id"]

        data = wait_done(client, task_id)
        kinds = [e["kind"] for e in data["events"]]
        assert "episode_start" in kinds
        assert "action" in kinds and "observation" in kinds
        action = next(e for e in data["events"] if e["kind"] == "action")
        assert action["data"]["tool"] == "read_file"
        observation = next(e for e in data["events"] if e["kind"] == "observation")
        assert "def f" in observation["data"]["text"]

        assert data["final"]["answer"].startswith("文件定义了函数 f")
        assert data["final"]["tool_calls"] == ["read_file"]
        assert data["final"]["truncated"] is False
        # 多轮记忆已写入
        assert len(agent.memory.turns) >= 3

    def test_empty_message_rejected(self, tmp_path):
        client, _ = make_client(tmp_path)
        resp = client.post("/api/chat", json={"message": "   "})
        assert resp.status_code == 400

    def test_oversized_message_rejected(self, tmp_path):
        from web import MAX_MESSAGE_CHARS
        client, _ = make_client(tmp_path)
        resp = client.post("/api/chat", json={"message": "x" * (MAX_MESSAGE_CHARS + 1)})
        assert resp.status_code == 400
        assert "消息过长" in resp.get_json()["error"]

    def test_unknown_task_404(self, tmp_path):
        client, _ = make_client(tmp_path)
        assert client.get("/api/task/999").status_code == 404


class TestSetupWizard:
    def _wizard_app(self, tmp_path):
        """未配置状态 + 写入/重建路径均指向临时目录的应用。"""
        from codementor.config import Config

        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        holder = {}

        def factory():
            llm = MockLLM(["Final Answer: 配置完成后的回答。"])
            agent = Agent(llm=llm, registry=build_registry(str(tmp_path)),
                          memory=ContextMemory(), mode="auto")
            config = Config(
                api_key="sk-new", base_url="http://preset/v1", model="preset-model",
                max_iterations=8, request_timeout=60, max_retries=3,
                memory_chars=1000, workspace=str(tmp_path),
                protocol="anthropic", max_tokens=4096,
            )
            holder["agent"] = agent
            return agent, config

        app = create_app(unconfigured=True,
                         env_path=str(tmp_path / ".env"),
                         agent_factory=factory)
        return app.test_client(), tmp_path, holder

    def test_presets_endpoint(self, tmp_path):
        client, _, _ = self._wizard_app(tmp_path)
        data = client.get("/api/presets").get_json()
        presets = data["presets"]
        assert len(presets) >= 20                      # 覆盖国内外主流服务商
        first = presets[0]
        assert {"id", "group", "label", "protocol", "base_url", "models"} <= set(first)
        groups = {p["group"] for p in presets}
        assert {"国内大模型", "国际大模型", "聚合平台", "本地部署", "自定义"} <= groups
        # 官方 Claude 走 anthropic 协议；自定义项存在且地址留空
        claude = next(p for p in presets if p["id"] == "anthropic")
        assert claude["protocol"] == "anthropic"
        custom = next(p for p in presets if p["id"] == "custom")
        assert custom["base_url"] == ""

    def test_setup_saves_env_and_rebuilds_agent(self, tmp_path):
        client, tmp, holder = self._wizard_app(tmp_path)
        assert client.get("/api/status").get_json()["configured"] is False

        resp = client.post("/api/setup", json={
            "api_key": "sk-wizard-key",
            "protocol": "anthropic",
            "base_url": "https://open.bigmodel.cn/api/anthropic/",
            "model": "glm-5.3-flash",
        })
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

        env_text = (tmp / ".env").read_text(encoding="utf-8")   # 已持久化（记忆）
        assert "CODEMENTOR_API_KEY=sk-wizard-key" in env_text
        assert "CODEMENTOR_PROTOCOL=anthropic" in env_text
        assert "CODEMENTOR_BASE_URL=https://open.bigmodel.cn/api/anthropic" in env_text

        status = client.get("/api/status").get_json()             # Agent 已重建
        assert status["configured"] is True
        assert status["model"] == "preset-model"
        assert holder["agent"] is not None

        chat = client.post("/api/chat", json={"message": "你好"})  # 可正常使用
        assert chat.status_code == 202

    def test_setup_validation_errors(self, tmp_path):
        client, _, _ = self._wizard_app(tmp_path)
        cases = [
            ({"api_key": "", "protocol": "openai", "base_url": "http://x/v1", "model": "m"}, "API Key"),
            ({"api_key": "k", "protocol": "grpc", "base_url": "http://x/v1", "model": "m"}, "protocol"),
            ({"api_key": "k", "protocol": "openai", "base_url": "ftp://x", "model": "m"}, "http"),
            ({"api_key": "k", "protocol": "openai", "base_url": "http://x/v1", "model": ""}, "模型"),
        ]
        for payload, expect in cases:
            resp = client.post("/api/setup", json=payload)
            assert resp.status_code == 400, payload
            assert expect in resp.get_json()["error"]


class TestControls:
    def test_mode_switch_rebuilds_and_clears(self, tmp_path):
        client, agent = make_client(tmp_path, ["Final Answer: ok"])
        agent.run("占位一轮")
        assert len(agent.memory.turns) > 0
        resp = client.post("/api/mode", json={"mode": "review"})
        assert resp.status_code == 200
        assert agent.mode == "review"
        assert len(agent.memory.turns) == 0   # 切模式清空记忆
        assert client.post("/api/mode", json={"mode": "hack"}).status_code == 400

    def test_reset_clears_memory(self, tmp_path):
        client, agent = make_client(tmp_path, ["Final Answer: ok"])
        agent.run("hi")
        assert client.post("/api/reset").status_code == 200
        assert len(agent.memory.turns) == 0

    def test_llm_error_becomes_error_event(self, tmp_path):
        from codementor.llm import LLMError
        agent_llm = MockLLM([])
        agent_llm.chat = lambda *a, **k: (_ for _ in ()).throw(LLMError("boom"))
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        agent = Agent(llm=agent_llm, registry=build_registry(str(tmp_path)),
                      memory=ContextMemory(), mode="auto")
        client = create_app(agent=agent).test_client()
        task_id = client.post("/api/chat", json={"message": "t"}).get_json()["task_id"]
        data = wait_done(client, task_id)
        assert data.get("final") is None
        errors = [e for e in data["events"] if e["kind"] == "error"]
        assert errors and "boom" in errors[0]["data"]["message"]
