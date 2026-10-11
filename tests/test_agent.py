# -*- coding: utf-8 -*-
"""agent 模块单元测试：用 MockLLM 驱动完整 ReAct 循环（无网络）。"""

import pytest

from codementor.agent import Agent, FORMAT_ERROR_HINT
from codementor.llm import MockLLM
from codementor.memory import ContextMemory
from codementor.prompts import build_system_prompt
from codementor.tools import build_registry


def make_agent(tmp_path, replies, mode="review", **kwargs):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    events = []
    llm = MockLLM(replies)
    agent = Agent(
        llm=llm,
        registry=build_registry(str(tmp_path)),
        memory=ContextMemory(),
        mode=mode,
        emit=lambda kind, **data: events.append((kind, data)),
        **kwargs,
    )
    return agent, llm, events


class TestHappyPath:
    def test_tool_call_then_final(self, tmp_path):
        agent, llm, events = make_agent(tmp_path, [
            'Thought: 先读文件\nAction: {"tool": "read_file", "args": {"path": "a.py"}}',
            "Thought: 已了解内容\nFinal Answer: 该文件定义了函数 f，返回 1。",
        ])
        result = agent.run("看看 a.py")

        assert result.final_answer.startswith("该文件定义了函数 f")
        assert result.truncated is False
        assert result.iterations == 2
        assert result.tool_calls == ["read_file"]
        step = result.steps[0]
        assert step.tool == "read_file"
        assert "def f" in step.observation      # Observation 来自真实工具执行
        assert step.thought == "先读文件"       # Thought 前缀已被清理

        kinds = [k for k, _ in events]
        assert kinds[0] == "episode_start"
        assert "action" in kinds and "observation" in kinds and "final" in kinds

    def test_system_prompt_contains_tools_and_mode(self, tmp_path):
        agent, _, _ = make_agent(tmp_path, [])
        prompt = agent._system_prompt
        assert "代码审查" in prompt
        assert "read_file" in prompt and "run_tests" in prompt
        assert "ReAct" in prompt


class TestSelfCorrection:
    def test_unknown_tool_returns_error_observation(self, tmp_path):
        agent, _, _ = make_agent(tmp_path, [
            'Thought: x\nAction: {"tool": "no_such", "args": {}}',
            "Final Answer: 已改用正确工具完成任务。",
        ])
        result = agent.run("t")
        assert "未知工具" in result.steps[0].observation
        assert result.final_answer.startswith("已改用")

    def test_bad_path_error_observation(self, tmp_path):
        agent, _, _ = make_agent(tmp_path, [
            'Action: {"tool": "read_file", "args": {"path": "../outside.py"}}',
            "Final Answer: 已在工作区内找到替代文件。",
        ])
        result = agent.run("t")
        assert "越界" in result.steps[0].observation

    def test_parse_failure_gets_format_hint(self, tmp_path):
        agent, _, _ = make_agent(tmp_path, [
            "我打算直接读取文件看看内容。",
            "Final Answer: 已按格式完成任务。",
        ])
        result = agent.run("t")
        assert result.steps[0].observation == FORMAT_ERROR_HINT
        assert "格式" in result.steps[0].observation


class TestLoopBoundaries:
    def test_max_iterations_forces_final(self, tmp_path):
        agent, llm, _ = make_agent(tmp_path, [
            'Action: {"tool": "list_dir", "args": {}}',
            'Action: {"tool": "list_dir", "args": {}}',
            "Final Answer: 被迫总结收尾。",
        ], max_iterations=2)
        result = agent.run("t")
        assert result.truncated is True
        assert result.iterations == 3   # 2 轮工具 + 1 次强制总结
        assert len(result.steps) == 2
        assert result.final_answer == "被迫总结收尾。"
        # 强制总结指令已注入对话
        all_contents = [m["content"] for c in llm.calls for m in c]
        assert any("最大推理轮数" in c for c in all_contents)

    def test_format_failures_do_not_consume_budget(self, tmp_path):
        # 格式漂移不占用推理轮数预算：2 次失败 + 1 次工具调用 + 最终答复
        agent, _, _ = make_agent(tmp_path, [
            "（格式漂移的废话 1）",
            "（格式漂移的废话 2）",
            'Thought: 回到正轨\nAction: {"tool": "read_file", "args": {"path": "a.py"}}',
            "Final Answer: 尽管漂移过，任务预算未被浪费。",
        ], max_iterations=2)
        result = agent.run("t")
        assert result.truncated is False
        assert result.tool_calls == ["read_file"]
        assert result.iterations == 4
        assert "预算未被浪费" in result.final_answer

    def test_excessive_format_failures_force_final(self, tmp_path):
        agent, _, _ = make_agent(tmp_path, [
            "（废话 1）", "（废话 2）", "（废话 3）", "（废话 4）",
            "Final Answer: 格式失败超限后被迫收尾。",
        ], max_iterations=8)
        result = agent.run("t")
        assert result.truncated is True
        assert result.final_answer.startswith("格式失败超限")
        assert len(result.steps) == 4   # 4 次失败轮都留有记录

    def test_empty_input_rejected(self, tmp_path):
        agent, _, _ = make_agent(tmp_path, [])
        with pytest.raises(ValueError):
            agent.run("   ")


class TestMultiTurnMemory:
    def test_history_persists_between_runs(self, tmp_path):
        agent, _, _ = make_agent(tmp_path, [
            "Final Answer: 第一轮答复：函数 f 返回 1。",
            "Final Answer: 第二轮答复：延续上一轮结论。",
        ])
        agent.run("第一问：a.py 里有什么？")
        result = agent.run("第二问：继续")
        assert result.final_answer.startswith("第二轮答复")
        contents = [m["content"] for m in agent.memory.build_messages("S")]
        assert any("第一轮答复" in c for c in contents)

    def test_events_do_not_break_agent(self, tmp_path):
        # emit 回调抛异常不应影响 Agent 运行
        agent, _, _ = make_agent(tmp_path, ["Final Answer: ok"])
        agent._emit_fn = lambda kind, **data: (_ for _ in ()).throw(RuntimeError("UI 崩溃"))
        assert agent.run("t").final_answer == "ok"


class TestAgentLevelRetry:
    def test_llm_error_gets_one_extra_attempt(self, tmp_path):
        from codementor.llm import LLMError

        class FlakyLLM:
            def __init__(self):
                self.calls = 0

            def chat(self, messages, temperature=0.3):
                self.calls += 1
                if self.calls == 1:
                    raise LLMError("客户端三次重试后仍失败")
                return "Final Answer: 第二次成功了。"

        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        events = []
        agent = Agent(
            llm=FlakyLLM(),
            registry=build_registry(str(tmp_path)),
            memory=ContextMemory(),
            emit=lambda kind, **d: events.append(kind),
        )
        result = agent.run("t")
        assert result.final_answer == "第二次成功了。"
        assert "llm_retry" in events
        assert events.count("episode_start") == 1

    def test_llm_error_still_raises_after_extra_attempt(self, tmp_path):
        from codementor.llm import LLMError

        class DeadLLM:
            def chat(self, messages, temperature=0.3):
                raise LLMError("彻底失败")

        agent = Agent(
            llm=DeadLLM(),
            registry=build_registry(str(tmp_path)),
            memory=ContextMemory(),
        )
        with pytest.raises(LLMError):
            agent.run("t")


class TestModeSwitch:
    def test_invalid_mode_rejected(self, tmp_path):
        agent, _, _ = make_agent(tmp_path, [])
        with pytest.raises(ValueError):
            agent.mode = "hack"

    def test_emit_handler_settable(self, tmp_path):
        agent, _, _ = make_agent(tmp_path, ["Final Answer: ok"])
        seen = []
        agent.emit_handler = lambda kind, **d: seen.append(kind)
        agent.run("t")
        assert "episode_start" in seen and "final" in seen

    def test_switch_rebuilds_prompt(self, tmp_path):
        agent, _, _ = make_agent(tmp_path, [])
        agent.mode = "test"
        assert "pytest" in agent._system_prompt
