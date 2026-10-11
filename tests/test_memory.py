# -*- coding: utf-8 -*-
"""memory 模块单元测试：多轮记忆与滑动窗口压缩。"""

from codementor.memory import ContextMemory


class TestBasicFlow:
    def test_build_messages_structure(self):
        m = ContextMemory()
        m.add("user", "你好")
        m.add("assistant", "你好，有什么可以帮你？")
        msgs = m.build_messages("SYSTEM_PROMPT")
        assert msgs[0] == {"role": "system", "content": "SYSTEM_PROMPT"}
        assert [x["role"] for x in msgs[1:]] == ["user", "assistant"]

    def test_persists_across_adds(self):
        m = ContextMemory()
        m.add("user", "第一问")
        m.add("assistant", "第一答")
        m.add("user", "第二问")
        contents = [x["content"] for x in m.build_messages("S")]
        assert "第一问" in contents and "第二问" in contents

    def test_clear(self):
        m = ContextMemory()
        m.add("user", "x")
        m.clear()
        assert m.build_messages("S") == [{"role": "system", "content": "S"}]


class TestSlidingWindow:
    def test_old_turns_compressed_into_summary(self):
        m = ContextMemory(max_chars=260)
        m.add("user", "A" * 100)
        m.add("assistant", "B" * 100)   # 200，未超
        m.add("user", "C" * 100)        # 300 > 260，最旧一轮被压缩
        msgs = m.build_messages("S")
        contents = [x["content"] for x in msgs]

        summary = [c for c in contents if "压缩摘要" in c]
        assert summary and "A" * 100 in summary[0]  # 旧内容进入摘要

        kept = [c for c in contents if "压缩摘要" not in c and c != "S"]
        assert sum(len(c) for c in kept) <= 260     # 预算得到保证
        assert not any(c == "A" * 100 for c in kept)

    def test_summary_capped(self):
        m = ContextMemory(max_chars=100)
        for i in range(40):
            m.add("user", f"问题{i}：" + "x" * 80)
            m.add("assistant", f"回答{i}：" + "y" * 80)
        assert len(m.summary) <= 3000

    def test_view_shows_recent(self):
        m = ContextMemory()
        m.add("user", "问" * 200)
        assert "问" in m.view()
