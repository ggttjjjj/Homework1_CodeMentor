# -*- coding: utf-8 -*-
"""把 .codementor_tmp 下保存的运行输出包装成 examples/ 演示记录。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DOCS = {
    "flash_review.txt": (
        "examples/demo_transcript_api_review.md",
        "代码审查（GLM-5.3-Flash）",
        '命令: python main.py --mode review -t "请审查 examples/buggy.py 的代码质量"',
    ),
    "m_refactor.txt": (
        "examples/demo_transcript_api_refactor.md",
        "重构建议（GLM-5.3-Flash）",
        '命令: python main.py --mode refactor -t "分析 examples/buggy.py 的代码坏味道并给出重构建议"',
    ),
    "api_test.txt": (
        "examples/demo_transcript_api_test.md",
        "测试生成（GLM-4.5-Flash）",
        '命令: python main.py --mode test -t "为 examples/buggy.py 生成单元测试并运行验证"',
    ),
}

HEADER = """# {title}

> 命令与产出说明见正文；由本脚本从 .codementor_tmp 的原始输出包装生成。

```text
{command}

"""

for src_name, (out_rel, title, command) in DOCS.items():
    src = ROOT / ".codementor_tmp" / src_name
    if not src.is_file():
        print(f"跳过（缺原始输出）: {src_name}")
        continue
    body = src.read_text(encoding="utf-8").strip()
    out = ROOT / out_rel
    out.write_text(
        HEADER.format(title=title, command=command) + body + "\n```\n",
        encoding="utf-8",
    )
    print(f"written: {out} ({len(body)} chars)")
