#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CodeMentor 命令行入口。

用法：
  python main.py                                   # 交互模式（auto）
  python main.py --mode review                     # 交互模式（代码审查）
  python main.py --mode test -t "为 examples/buggy.py 生成单元测试"
  python main.py --provider mock -t "请审查 examples/buggy.py 的代码质量"   # 离线演示
  python main.py --mode review --log run.jsonl -t "..."
"""

import argparse
import json
import os
import sys
from pathlib import Path

from codementor import __version__
from codementor.agent import Agent, AgentResult
from codementor.app import MissingAPIKeyError, create_agent
from codementor.llm import LLMError
from codementor.prompts import MODES, get_mode_names

# ---------------------------------------------------------------- 颜色输出

USE_COLOR = True

CODES = {
    "bold": "1", "dim": "2", "red": "31", "green": "32",
    "yellow": "33", "cyan": "36",
}


def paint(text: str, style: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{CODES[style]}m{text}\033[0m"


def setup_stdio() -> None:
    """Windows 终端启用 ANSI；重定向输出时切换 UTF-8 防乱码。"""
    if os.name == "nt":
        os.system("")  # 激活控制台 VT 处理
    if not sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 组装

def build_agent(args) -> Agent:
    ui = ConsoleUI(verbose=args.verbose)
    try:
        agent, _config = create_agent(
            provider=args.provider,
            config_path=args.config,
            emit=ui.on_event,
            mode=args.mode,
        )
    except MissingAPIKeyError:
        print(
            paint("错误: 未配置 API Key。两种方式任选其一：", "red") + """
  1. 配置文件（推荐）: 复制 .env.example 为 .env，填入 CODEMENTOR_API_KEY
     以及你所用服务商的 PROTOCOL / BASE_URL / MODEL（模板里有各家示例）
  2. 离线体验: python main.py --provider mock -t "请审查 examples/buggy.py"
注意: zip 包出于安全不包含 .env——若你运行的是解压出来的副本，
      请把原目录的 .env 复制过来，或使用方式 2。""",
            file=sys.stderr,
        )
        sys.exit(1)
    except ValueError as e:
        print(paint(f"错误: {e}", "red"), file=sys.stderr)
        sys.exit(1)

    if args.provider == "mock":
        print(paint("[提示] mock 演示模式：无需 API Key，模型回复为预置脚本，"
                    "工具调用为真实执行（演示场景：审查 examples/buggy.py）。", "yellow"))
    return agent


# ---------------------------------------------------------------- 控制台 UI

class ConsoleUI:
    """订阅 Agent 事件并打印执行过程。"""

    OBS_PREVIEW = 600

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose

    def on_event(self, kind: str, **data) -> None:
        if kind == "action":
            if data.get("thought"):
                print(paint(f"Thought  {data['thought']}", "cyan"))
            print(paint(f"Action   {data['tool']}({json.dumps(data['args'], ensure_ascii=False)})", "yellow"))
        elif kind == "observation":
            text = data["text"]
            if not self.verbose and len(text) > self.OBS_PREVIEW:
                text = text[: self.OBS_PREVIEW] + f"\n...[预览截断，共 {len(data['text'])} 字符，--verbose 查看全文]"
            print(paint(f"Observe  {text}", "dim"))
        elif kind == "parse_error":
            print(paint("格式解析失败，已回纠提示让模型自修复…", "red"))


def print_result(result: AgentResult) -> None:
    print()
    print(paint(f"═══ 最终答复（推理 {result.iterations} 轮，工具调用 {len(result.tool_calls)} 次）═══", "green"))
    print(result.final_answer)


# ---------------------------------------------------------------- 单次任务

def run_once(agent: Agent, task: str, log_path: str = None) -> int:
    try:
        result = agent.run(task)
    except LLMError as e:
        print(paint(f"\n调用 LLM 失败: {e}", "red"), file=sys.stderr)
        return 1
    print_result(result)
    if log_path:
        write_log(log_path, task, result)
    return 0


def write_log(path: str, task: str, result: AgentResult) -> None:
    """执行轨迹写入 JSON。"""
    payload = {
        "task": task,
        "iterations": result.iterations,
        "truncated": result.truncated,
        "tool_calls": result.tool_calls,
        "steps": [
            {"index": s.index, "thought": s.thought, "tool": s.tool,
             "args": s.args, "observation": s.observation}
            for s in result.steps
        ],
        "final_answer": result.final_answer,
    }
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(paint(f"执行日志已写入 {path}", "dim"))


# ---------------------------------------------------------------- 交互 REPL

HELP_TEXT = f"""可用命令:
  /help              显示本帮助
  /mode <名称>       切换工作模式: {', '.join(get_mode_names())}
  /tools             查看工具清单
  /history           查看对话历史摘要
  /reset             清空上下文记忆
  /exit  /quit       退出

使用提示: 直接输入任务描述，例如:
  请审查 examples/buggy.py 的代码质量
  为 examples/buggy.py 生成单元测试并运行验证
  解释一下 examples/buggy.py 中 average 函数的逻辑"""


def run_repl(agent: Agent) -> int:
    mode_label = MODES[agent.mode]["label"]
    print(paint(f"\nCodeMentor · 代码助手 Agent v{__version__}", "bold"))
    print(f"模式: {agent.mode}({mode_label}) | 最大推理轮数: {agent.max_iterations}")
    print(f"输入 /help 查看命令\n")
    while True:
        try:
            line = input(paint("你> ", "green")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            return 0
        if not line:
            continue
        if line.startswith("/"):
            if not handle_command(line, agent):
                return 0
            continue
        try:
            result = agent.run(line)
        except LLMError as e:
            print(paint(f"调用 LLM 失败: {e}", "red"), file=sys.stderr)
            continue
        print_result(result)
        print()


def handle_command(line: str, agent: Agent) -> bool:
    """处理 REPL 命令，返回 False 表示退出。"""
    parts = line.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/exit", "/quit"):
        print("再见！")
        return False
    if cmd == "/help":
        print(HELP_TEXT)
    elif cmd == "/mode":
        if not arg:
            print(f"当前模式: {agent.mode}。可选: {', '.join(get_mode_names())}")
        elif arg in MODES:
            agent.mode = arg
            agent.memory.clear()
            print(f"已切换到 {arg}({MODES[arg]['label']}) 模式，并清空历史")
        else:
            print(paint(f"未知模式 '{arg}'，可选: {', '.join(get_mode_names())}", "red"))
    elif cmd == "/tools":
        print(agent.registry.docs())
    elif cmd == "/history":
        print(agent.memory.view())
    elif cmd == "/reset":
        agent.memory.clear()
        print("已清空上下文记忆")
    else:
        print(paint(f"未知命令 {cmd}，/help 查看帮助", "red"))
    return True


# ---------------------------------------------------------------- 入口

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="codementor",
        description="CodeMentor —— 代码助手 Agent（审查/解释/测试生成/重构/代码生成）",
    )
    parser.add_argument("--mode", default="auto", choices=get_mode_names(),
                        help="工作模式，默认 auto")
    parser.add_argument("--provider", default="api", choices=["api", "mock"],
                        help="api=真实 LLM（默认），mock=离线演示脚本")
    parser.add_argument("-t", "--task", help="单次任务：执行后退出（省略则进入交互模式）")
    parser.add_argument("-c", "--config", help="config.json 路径（默认自动查找）")
    parser.add_argument("--log", help="把执行轨迹写入 JSON 文件")
    parser.add_argument("--verbose", action="store_true", help="显示完整 Observation")
    parser.add_argument("--no-color", action="store_true", help="禁用彩色输出")
    parser.add_argument("--version", action="version", version=f"CodeMentor {__version__}")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    global USE_COLOR
    args = parse_args(argv)
    setup_stdio()
    if args.no_color or not sys.stdout.isatty():
        USE_COLOR = False

    agent = build_agent(args)
    if args.task:
        return run_once(agent, args.task, args.log)
    return run_repl(agent)


if __name__ == "__main__":
    sys.exit(main())
