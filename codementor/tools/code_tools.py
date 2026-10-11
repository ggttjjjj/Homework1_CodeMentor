# -*- coding: utf-8 -*-
"""代码执行工具：子进程运行 Python 代码 / 运行 pytest。

限时执行、超时终止；危险调用做拦截（演示级防护，生产环境应容器隔离）。
"""

import subprocess
import sys
import uuid
from pathlib import Path
from typing import List

from .base import Tool

EXECUTE_TIMEOUT_DEFAULT = 10
EXECUTE_TIMEOUT_MAX = 30
TEST_TIMEOUT = 120
OUTPUT_LIMIT = 4000

DANGEROUS_PATTERNS = [
    "shutil.rmtree",
    "os.system",
    "os.popen",
    "os.remove",
    "os.unlink",
    "subprocess",
    "rm -rf",
    "ctypes",
]


def _run_subprocess(cmd: List[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    """跨平台子进程执行（Windows/Linux 均以 UTF-8 解码输出）。"""
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _trim(text: str, limit: int = OUTPUT_LIMIT) -> str:
    text = text or ""
    if len(text) <= limit:
        return text if text.strip() else "（空）"
    return text[:limit] + f"\n...[输出截断，共 {len(text)} 字符]"


def _sandbox_dir(workspace: str) -> Path:
    root = Path(workspace).resolve()
    sandbox = root / ".codementor_tmp"
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


def execute_code(workspace: str, code: str, timeout: int = EXECUTE_TIMEOUT_DEFAULT) -> str:
    """在子进程中执行 Python 代码，返回退出码与输出。cwd 为工作区根目录。"""
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code 不能为空")

    for pattern in DANGEROUS_PATTERNS:
        if pattern in code:
            return (
                f"[已拦截] 检测到危险调用 '{pattern}'。execute_code 仅允许纯计算代码，"
                f"禁止文件删除/子进程/系统命令等操作；运行测试请使用 run_tests 工具。"
            )

    timeout = max(1, min(int(timeout), EXECUTE_TIMEOUT_MAX))
    root = Path(workspace).resolve()
    sandbox = _sandbox_dir(workspace)
    script = sandbox / f"exec_{uuid.uuid4().hex[:8]}.py"
    script.write_text(code, encoding="utf-8")
    try:
        proc = _run_subprocess([sys.executable, str(script)], root, timeout)
    except subprocess.TimeoutExpired:
        return f"[执行超时] 代码运行超过 {timeout}s 被强制终止，请检查是否存在死循环。"
    finally:
        script.unlink(missing_ok=True)

    header = f"[退出码 {proc.returncode}]"
    return (
        f"{header}\nstdout:\n{_trim(proc.stdout)}\nstderr:\n{_trim(proc.stderr)}"
    )


def run_tests(workspace: str, target: str = "tests") -> str:
    """对指定目录/文件运行 pytest，返回测试结果。"""
    root = Path(workspace).resolve()
    target_path = (root / target).resolve()
    try:
        target_path.relative_to(root)
    except ValueError:
        raise PermissionError(f"测试目标 '{target}' 不在工作区内，已拒绝")

    if not target_path.exists():
        raise FileNotFoundError(f"测试目标不存在: {target}")

    try:
        proc = _run_subprocess(
            [sys.executable, "-m", "pytest", str(target_path), "-q", "--no-header"],
            root,
            TEST_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return f"[测试超时] pytest 运行超过 {TEST_TIMEOUT}s 被终止，可能存在挂起的用例。"

    combined = (proc.stdout or "") + (proc.stderr or "")
    if "No module named pytest" in combined:
        return (
            "错误: 当前 Python 环境未安装 pytest，无法运行测试。"
            "请先安装: pip install pytest"
        )

    verdict = "全部通过" if proc.returncode == 0 else "存在失败或错误"
    return f"[pytest 退出码 {proc.returncode} | {verdict}]\n{_trim(combined)}"


def build_code_tools(workspace: str) -> List[Tool]:
    """构造绑定到指定工作区的代码执行工具集。"""
    return [
        Tool(
            name="execute_code",
            description="在隔离子进程中执行一段 Python 代码并返回 stdout/stderr（工作目录为工作区根，可直接用相对路径读文件），用于验证逻辑、运行示例",
            parameters={
                "code": {"type": "string", "description": "要执行的完整 Python 代码"},
                "timeout": {"type": "integer", "description": f"超时秒数 1-{EXECUTE_TIMEOUT_MAX}，默认 {EXECUTE_TIMEOUT_DEFAULT}"},
            },
            func=lambda code, timeout=EXECUTE_TIMEOUT_DEFAULT: execute_code(workspace, code, timeout),
            example='Action: {"tool": "execute_code", "args": {"code": "print(sum(range(10)))"}}',
        ),
        Tool(
            name="run_tests",
            description="对指定目录或文件运行 pytest 单元测试，返回通过/失败详情",
            parameters={
                "target": {"type": "string", "description": "测试目录或文件路径，默认 tests/"},
            },
            func=lambda target="tests": run_tests(workspace, target),
            example='Action: {"tool": "run_tests", "args": {"target": "tests"}}',
        ),
    ]
