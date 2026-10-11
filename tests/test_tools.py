# -*- coding: utf-8 -*-
"""tools 模块单元测试：文件工具、代码执行工具与安全边界。"""

import pytest

from codementor.tools import build_registry


@pytest.fixture
def reg(tmp_path):
    (tmp_path / "app.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "g.py").write_text("VALUE = 42\n", encoding="utf-8")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "app.cpython-311.pyc").write_text("binary", encoding="utf-8")
    return build_registry(str(tmp_path))


class TestReadFile:
    def test_returns_numbered_lines(self, reg):
        obs = reg.execute("read_file", {"path": "app.py"})
        assert "| def f(x):" in obs
        assert "共 2 行" in obs

    def test_missing_file_is_error_observation(self, reg):
        obs = reg.execute("read_file", {"path": "nope.py"})
        assert obs.startswith("错误:") and "文件不存在" in obs

    def test_directory_is_rejected(self, reg):
        obs = reg.execute("read_file", {"path": "sub"})
        assert "目录" in obs


class TestPathSafety:
    def test_escape_rejected(self, reg):
        obs = reg.execute("read_file", {"path": "../secret.txt"})
        assert obs.startswith("错误:") and "越界" in obs

    def test_absolute_outside_rejected(self, reg):
        obs = reg.execute("read_file", {"path": "C:/Windows/win.ini"})
        assert "越界" in obs

    def test_write_escape_rejected(self, reg):
        obs = reg.execute("write_file", {"path": "../evil.txt", "content": "x"})
        assert "越界" in obs


class TestWriteFile:
    def test_roundtrip(self, reg):
        obs = reg.execute("write_file", {"path": "sub/gen.py", "content": "print(1)\n"})
        assert obs.startswith("已写入")
        back = reg.execute("read_file", {"path": "sub/gen.py"})
        assert "print(1)" in back

    def test_content_must_be_string(self, reg):
        obs = reg.execute("write_file", {"path": "x.py", "content": 123})
        assert obs.startswith("错误:")


class TestListDir:
    def test_tree_and_skip_cache(self, reg):
        obs = reg.execute("list_dir", {"path": "."})
        assert "app.py" in obs and "sub/" in obs and "g.py" in obs
        assert "__pycache__" not in obs


class TestSearchCode:
    def test_find_with_lineno(self, reg):
        obs = reg.execute("search_code", {"pattern": r"VALUE = \d+"})
        assert "sub/g.py:1:" in obs

    def test_no_match(self, reg):
        obs = reg.execute("search_code", {"pattern": "NOT_EXIST_TOKEN"})
        assert "未找到" in obs

    def test_invalid_regex_is_error(self, reg):
        obs = reg.execute("search_code", {"pattern": "([unclosed"})
        assert obs.startswith("错误:") and "正则" in obs


class TestExecuteCode:
    def test_success(self, reg):
        obs = reg.execute("execute_code", {"code": "print(sum(range(10)))"})
        assert "[退出码 0]" in obs and "45" in obs

    def test_relative_path_runs_in_workspace_cwd(self, reg, tmp_path):
        (tmp_path / "data.txt").write_text("hello-from-workspace", encoding="utf-8")
        obs = reg.execute("execute_code", {
            "code": "print(open('data.txt', encoding='utf-8').read())"
        })
        assert "[退出码 0]" in obs and "hello-from-workspace" in obs

    def test_stderr_captured(self, reg):
        obs = reg.execute("execute_code", {"code": "import sys\nsys.stderr.write('boom')\nraise SystemExit(3)"})
        assert "[退出码 3]" in obs and "boom" in obs

    def test_timeout_killed(self, reg):
        obs = reg.execute("execute_code", {"code": "import time\ntime.sleep(5)", "timeout": 1})
        assert "[执行超时]" in obs

    def test_dangerous_call_blocked(self, reg):
        obs = reg.execute("execute_code", {"code": "import os\nos.system('echo hi')"})
        assert "[已拦截]" in obs

    def test_empty_code_rejected(self, reg):
        obs = reg.execute("execute_code", {"code": "   "})
        assert obs.startswith("错误:")


class TestRegistry:
    def test_unknown_tool(self, reg):
        obs = reg.execute("no_such_tool", {})
        assert "未知工具" in obs and "read_file" in obs

    def test_wrong_args_hint(self, reg):
        obs = reg.execute("read_file", {"wrong": 1})
        assert "参数不匹配" in obs

    def test_truncation(self, reg, tmp_path):
        (tmp_path / "big.py").write_text("x\n" * 5000, encoding="utf-8")
        obs = reg.execute("read_file", {"path": "big.py"})
        assert len(obs) < 4000 and "截断" in obs

    def test_docs_contains_all_tools(self, reg):
        docs = reg.docs()
        for name in ["read_file", "write_file", "list_dir", "search_code", "execute_code", "run_tests"]:
            assert name in docs
