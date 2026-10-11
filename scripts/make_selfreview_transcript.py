# -*- coding: utf-8 -*-
"""生成 examples/demo_transcript_selfreview.md（review 模式审查 codementor 自身）。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HEADER = """# 演示记录：Agent 审查自身代码（GLM-5.3-Flash）

> 命令：python main.py --mode review -t "请审查你自己的代码（codementor 目录）的质量"
> 报告包含审查范围声明与定位到行号的问题清单。

```text

"""

src = ROOT / ".codementor_tmp" / "selfreview2.txt"
body = src.read_text(encoding="utf-8").strip()
out = ROOT / "examples" / "demo_transcript_selfreview.md"
out.write_text(HEADER + body + "\n```\n", encoding="utf-8")
print(f"written: {out} ({len(body)} chars)")
