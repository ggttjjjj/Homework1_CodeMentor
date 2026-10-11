# -*- coding: utf-8 -*-
"""parsing 模块单元测试：ReAct 协议解析与容错。"""

from codementor.parsing import ParsedReply, extract_json_object, parse_reply


class TestFinalAnswer:
    def test_basic(self):
        r = parse_reply("Thought: 已看完代码\nFinal Answer: 存在除零风险")
        assert r.final == "存在除零风险"
        assert r.tool is None
        assert r.thought == "已看完代码"

    def test_bold_marker(self):
        r = parse_reply("Thought: 分析完成\n**Final Answer:** 报告如下……")
        assert r.final is not None and r.final.startswith("报告如下")

    def test_final_multiline(self):
        r = parse_reply("Thought: t\nFinal Answer: 第一行\n第二行")
        assert r.final == "第一行\n第二行"

    def test_not_triggered_without_colon(self):
        # 句中提到 final answer 但没有冒号标记，不算最终答复
        r = parse_reply("Thought: 下面解释 final answer 的含义")
        assert r.final is None and r.tool is None


class TestAction:
    def test_plain_json(self):
        r = parse_reply('Thought: 先读文件\nAction: {"tool": "read_file", "args": {"path": "a.py"}}')
        assert r.tool == "read_file"
        assert r.args == {"path": "a.py"}
        assert r.final is None
        assert r.thought == "先读文件"

    def test_fenced_json(self):
        text = ('Thought: 先读文件\nAction: ```json\n'
                '{"tool": "read_file", "args": {"path": "a.py"}}\n```')
        assert parse_reply(text).tool == "read_file"

    def test_json_with_trailing_text(self):
        text = 'Thought: x\nAction: {"tool": "list_dir", "args": {}} 等待结果后继续。'
        assert parse_reply(text).tool == "list_dir"

    def test_trailing_comma_repaired(self):
        text = 'Action: {"tool": "search_code", "args": {"pattern": "def", "path": ".",}}'
        r = parse_reply(text)
        assert r.tool == "search_code"
        assert r.args["pattern"] == "def"

    def test_missing_args_defaults_empty(self):
        r = parse_reply('Action: {"tool": "list_dir"}')
        assert r.tool == "list_dir" and r.args == {}

    def test_two_line_style(self):
        text = 'Thought: 浏览结构\nAction: read_file\nArgs: {"path": "x.py"}'
        r = parse_reply(text)
        assert r.tool == "read_file"
        assert r.args == {"path": "x.py"}

    def test_no_tool_key_is_parse_failure(self):
        r = parse_reply('Action: {"command": "read_file"}')
        assert r.tool is None and r.final is None


class TestActionEdgeCases:
    def test_plain_example_before_real_json_action(self):
        # Thought 中的格式示例不应劫持其后的真实调用
        text = (
            "Thought: 按协议先写示例：\nAction: read_file\nArgs: {\"path\": \"示例\"}\n"
            "下面是真实调用：\nAction: {\"tool\": \"search_code\", \"args\": {\"pattern\": \"def\"}}"
        )
        r = parse_reply(text)
        assert r.tool == "search_code"
        assert r.args == {"pattern": "def"}

    def test_json_example_without_tool_skipped(self):
        text = (
            'Thought: 参数长这样 {"command": "x"}\n'
            'Action: {"command": "示例"}\n'
            'Action: {"tool": "list_dir", "args": {}}'
        )
        r = parse_reply(text)
        assert r.tool == "list_dir"

    def test_unicode_tool_name_rejected(self):
        r = parse_reply("Thought: x\nAction: read_file中文")
        assert r.tool is None and r.final is None

    def test_args_taken_after_tool_name(self):
        text = 'Thought: 示例参数 Args: {"path": "旧"}\nAction: read_file\nArgs: {"path": "新"}'
        r = parse_reply(text)
        assert r.tool == "read_file"
        assert r.args == {"path": "新"}

    def test_plain_two_line_still_works(self):
        text = 'Thought: 浏览结构\nAction: read_file\nArgs: {"path": "x.py"}'
        r = parse_reply(text)
        assert r.tool == "read_file"
        assert r.args == {"path": "x.py"}


class TestUnparseable:
    def test_free_text(self):
        r = parse_reply("我觉得应该先看看文件内容再说。")
        assert r.tool is None and r.final is None

    def test_empty(self):
        r = parse_reply("")
        assert r.tool is None and r.final is None


class TestExtractJsonObject:
    def test_balanced_scan_ignores_braces_in_strings(self):
        text = '前缀 {"tool": "echo {brace}", "args": {}} 后缀'
        obj = extract_json_object(text)
        assert obj == {"tool": "echo {brace}", "args": {}}

    def test_nested(self):
        obj = extract_json_object('x {"a": {"b": 1}} y')
        assert obj == {"a": {"b": 1}}

    def test_none_when_absent(self):
        assert extract_json_object("没有 JSON") is None
