# -*- coding: utf-8 -*-
"""文件系统工具：读、写、列目录、代码搜索。

路径限制在工作区内（拒绝 `..`/绝对路径越界），读写有大小与数量上限。
"""

import os
import re
from pathlib import Path
from typing import List

from .base import Tool

MAX_FILE_BYTES = 200 * 1024
MAX_LIST_ENTRIES = 200
MAX_SEARCH_MATCHES = 50
MAX_SEARCH_FILE_BYTES = 1024 * 1024

SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache",
    "node_modules", ".venv", "venv", ".idea", ".vscode",
    ".codementor_tmp", "dist", ".mypy_cache",
}


def _safe_path(workspace: str, user_path: str) -> Path:
    """把路径限制在工作区内，越界抛 PermissionError。"""
    root = Path(workspace).resolve()
    candidate = (root / user_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise PermissionError(
            f"路径越界: '{user_path}' 不在工作区 {root} 内，已拒绝访问"
        )
    return candidate


def _skip_hidden(name: str) -> bool:
    return name.startswith(".") or name in SKIP_DIRS


def read_file(workspace: str, path: str) -> str:
    """读取文本文件，返回带行号的内容（便于模型引用行号）。"""
    target = _safe_path(workspace, path)
    if not target.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    if target.is_dir():
        raise IsADirectoryError(f"'{path}' 是目录，请用 list_dir 浏览")
    raw = target.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raw = raw[:MAX_FILE_BYTES]
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    numbered = "\n".join(f"{i:>4} | {line}" for i, line in enumerate(lines, 1))
    note = ""
    if len(raw) == MAX_FILE_BYTES:
        note = f"\n[提示] 文件超过 {MAX_FILE_BYTES} 字节，仅返回前 {MAX_FILE_BYTES} 字节。"
    return f"{path}（共 {len(lines)} 行）:\n{numbered}{note}"


def write_file(workspace: str, path: str, content: str) -> str:
    """在工作区内写入/覆盖文本文件。"""
    if not isinstance(content, str):
        raise TypeError("content 必须是字符串")
    target = _safe_path(workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    target.write_bytes(data)
    return f"已写入 {path}（{len(data)} 字节，{content.count(chr(10)) + 1} 行）"


def list_dir(workspace: str, path: str = ".", depth: int = 2) -> str:
    """按树形结构列出目录内容（跳过 .git/__pycache__ 等）。"""
    base = _safe_path(workspace, path)
    if not base.exists():
        raise FileNotFoundError(f"路径不存在: {path}")
    if base.is_file():
        return f"'{path}' 是文件: {base.stat().st_size} 字节"

    depth = max(1, min(int(depth), 4))
    entries: List[str] = []

    def walk(directory: Path, level: int) -> None:
        if level > depth or len(entries) >= MAX_LIST_ENTRIES:
            return
        try:
            children = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError as e:
            entries.append("  " * level + f"[无法访问: {e}]")
            return
        for child in children:
            if len(entries) >= MAX_LIST_ENTRIES:
                entries.append("  " * level + "...[条目过多，已截断]")
                return
            if _skip_hidden(child.name):
                continue
            if child.is_dir():
                entries.append("  " * level + f"{child.name}/")
                walk(child, level + 1)
            else:
                size = child.stat().st_size
                entries.append("  " * level + f"{child.name}  ({size} B)")

    entries.append(f"{path}/")
    walk(base, 1)
    return "\n".join(entries)


def search_code(workspace: str, pattern: str, path: str = ".") -> str:
    """在工作区内用正则搜索代码，返回 文件:行号: 内容 形式的命中。"""
    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"正则表达式非法: {e}")
    base = _safe_path(workspace, path)
    if not base.exists():
        raise FileNotFoundError(f"路径不存在: {path}")

    matches: List[str] = []
    if base.is_file():
        targets = [base]
    else:
        targets = [
            p
            for p in base.rglob("*")
            if p.is_file()
            and not any(_skip_hidden(part) for part in p.relative_to(base).parts[:-1])
            and not _skip_hidden(p.name)
            and p.stat().st_size <= MAX_SEARCH_FILE_BYTES
        ]

    for file_path in sorted(targets):
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = file_path.relative_to(Path(workspace).resolve())
        for lineno, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                matches.append(f"{rel.as_posix()}:{lineno}: {line.strip()[:200]}")
                if len(matches) >= MAX_SEARCH_MATCHES:
                    matches.append(f"...[命中过多，仅显示前 {MAX_SEARCH_MATCHES} 条]")
                    return "\n".join(matches)
    if not matches:
        return f"未找到匹配 '{pattern}' 的内容"
    return "\n".join(matches)


def build_fs_tools(workspace: str) -> List[Tool]:
    """构造绑定到指定工作区的文件系统工具集。"""
    return [
        Tool(
            name="read_file",
            description="读取工作区内的文本文件，返回带行号的内容",
            parameters={
                "path": {"type": "string", "description": "相对工作区根目录的文件路径"},
            },
            func=lambda path: read_file(workspace, path),
            example='Action: {"tool": "read_file", "args": {"path": "src/main.py"}}',
        ),
        Tool(
            name="write_file",
            description="在工作区内写入/覆盖文本文件（用于保存生成的代码或测试）",
            parameters={
                "path": {"type": "string", "description": "目标文件路径"},
                "content": {"type": "string", "description": "要写入的完整文本内容"},
            },
            func=lambda path, content: write_file(workspace, path, content),
            example='Action: {"tool": "write_file", "args": {"path": "tests/test_a.py", "content": "..."}}',
        ),
        Tool(
            name="list_dir",
            description="按树形结构列出目录内容，用于了解项目结构",
            parameters={
                "path": {"type": "string", "description": "目录路径，默认根目录"},
                "depth": {"type": "integer", "description": "递归深度 1-4，默认 2"},
            },
            func=lambda path=".", depth=2: list_dir(workspace, path, depth),
            example='Action: {"tool": "list_dir", "args": {"path": "."}}',
        ),
        Tool(
            name="search_code",
            description="用正则表达式在工作区内搜索代码内容，返回 文件:行号: 内容",
            parameters={
                "pattern": {"type": "string", "description": "正则表达式"},
                "path": {"type": "string", "description": "限定搜索的子目录或文件，默认整个工作区"},
            },
            func=lambda pattern, path=".": search_code(workspace, pattern, path),
            example='Action: {"tool": "search_code", "args": {"pattern": "def \\w+", "path": "src"}}',
        ),
    ]
