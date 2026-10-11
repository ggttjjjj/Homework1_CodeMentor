# -*- coding: utf-8 -*-
"""运行 mock 演示并生成 examples/demo_transcript.md。"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADER = """# 演示记录：代码审查（mock 离线模式）

> 命令行运行输出。--provider mock 模式下模型回复为预置脚本，
> 工具调用与 Observation 为真实执行。配置 API Key 后流程相同。

```text
命令: python main.py --provider mock --mode review -t "请审查 examples/buggy.py 的代码质量"

"""

FOOTER = "```\n"

proc = subprocess.run(
    [sys.executable, "main.py", "--provider", "mock", "--mode", "review",
     "-t", "请审查 examples/buggy.py 的代码质量", "--no-color"],
    cwd=str(ROOT), capture_output=True, text=True,
    encoding="utf-8", errors="replace",
)
body = proc.stdout.strip()
out = ROOT / "examples" / "demo_transcript.md"
out.write_text(HEADER + body + "\n" + FOOTER, encoding="utf-8")
print(f"written: {out} ({len(body)} chars, exit={proc.returncode})")
