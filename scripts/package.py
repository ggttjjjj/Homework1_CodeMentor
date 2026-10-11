# -*- coding: utf-8 -*-
"""打包源码发布包。

外层 zip 布局（解压后直接可用）：
  run.bat / run_web.bat   双击启动（首次运行自动释放源码）
  README.md / DESIGN.md   文档
  CodeMentor-source.zip   全部源码（不含 .env 等敏感文件）
"""

import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
ZIP_NAME = "Homework1_CodeMentor.zip"
SOURCE_ZIP = "CodeMentor-source.zip"

EXCLUDE_DIRS = {
    "__pycache__", ".git", ".pytest_cache", ".pytest_tmp",
    ".codementor_tmp", "dist", "node_modules", ".venv", "venv", ".idea", ".vscode",
}
EXCLUDE_FILES = {".env", "config.json", ".gitignore"}
EXCLUDE_SUFFIXES = {".zip", ".pyc"}


def should_skip(path: Path) -> bool:
    if path.name in EXCLUDE_FILES or path.suffix in EXCLUDE_SUFFIXES:
        return True
    return any(part in EXCLUDE_DIRS for part in path.relative_to(ROOT).parts)


def build_source_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(ROOT.rglob("*")):
            if path.is_dir() or should_skip(path):
                continue
            zf.write(path, path.relative_to(ROOT).as_posix())
    return buf.getvalue()


def main() -> None:
    DIST.mkdir(exist_ok=True)
    out = DIST / ZIP_NAME
    source_bytes = build_source_zip()
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in ("run.bat", "run_web.bat", "README.md", "DESIGN.md"):
            zf.write(ROOT / name, name)
            count += 1
        zf.writestr(SOURCE_ZIP, source_bytes)
        count += 1
    size_kb = out.stat().st_size / 1024
    print(f"打包完成: {out}")
    print(f"外层文件数: {count}（启动器 x2 + 文档 x2 + 内层源码包）")
    print(f"大小: {size_kb:.1f} KB（控制在 200MB 以内）")


if __name__ == "__main__":
    main()
