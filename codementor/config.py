# -*- coding: utf-8 -*-
"""配置加载。优先级：环境变量 > .env > config.json > 默认值。"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

# 项目根目录（codementor 包的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

def _env_file_candidates():
    return [Path.cwd() / ".env", PROJECT_ROOT / ".env"]


def _parse_env_file(path: Path) -> Dict[str, str]:
    """解析 KEY=VALUE 格式，支持注释、export 前缀与成对引号。"""
    data: Dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return data
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            data[key] = value
    return data


def effective_env() -> Dict[str, str]:
    """合并 .env 与系统环境变量（系统环境变量优先），不污染进程状态。"""
    merged: Dict[str, str] = {}
    for cand in _env_file_candidates():
        if cand.is_file():
            merged.update(_parse_env_file(cand))
            break
    merged.update({k: v for k, v in os.environ.items() if v})
    return merged


def write_env_file(values: Dict[str, str], path: Optional[Path] = None) -> Path:
    """把配置写入 .env：更新已有键、追加新键，保留其余行。"""
    target = Path(path) if path else (PROJECT_ROOT / ".env")
    lines = target.read_text(encoding="utf-8").splitlines() if target.is_file() else []

    remaining = dict(values)
    out: list = []
    for line in lines:
        stripped = line.strip()
        key = None
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key.startswith("export "):
                key = key[len("export "):].strip()
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)

    if remaining:
        if out and out[-1].strip():
            out.append("")
        out.append("# ---- CodeMentor Web 配置向导写入 ----")
        for key, value in remaining.items():
            out.append(f"{key}={value}")

    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    return target

DEFAULTS = {
    "api_key": "",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "protocol": "openai",       # openai | anthropic（智谱 Coding 套餐用 anthropic）
    "max_tokens": 8192,         # anthropic 协议必填的输出上限
    "max_iterations": 8,        # Agent 单轮任务最大推理步数
    "request_timeout": 180,     # 单次 LLM 请求超时（秒）；长任务/大上下文时生成较慢，给足预算
    "max_retries": 3,           # LLM 请求失败重试次数
    "memory_chars": 24000,      # 上下文记忆字符预算（超出后压缩）
    "workspace": ".",           # 工具可访问的工作区根目录
}

# 配置项 -> 对应环境变量
ENV_MAP = {
    "api_key": "CODEMENTOR_API_KEY",
    "base_url": "CODEMENTOR_BASE_URL",
    "model": "CODEMENTOR_MODEL",
    "protocol": "CODEMENTOR_PROTOCOL",
    "workspace": "CODEMENTOR_WORKSPACE",
}


@dataclass
class Config:
    """运行时配置对象。"""

    api_key: str
    base_url: str
    model: str
    max_iterations: int
    request_timeout: int
    max_retries: int
    memory_chars: int
    workspace: str
    protocol: str = "openai"
    max_tokens: int = 8192

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Config":
        """合并配置。config.json 查找顺序：显式路径 > 当前目录 > 项目根目录。"""
        data = dict(DEFAULTS)

        candidates = []
        if config_path:
            candidates.append(Path(config_path))
        candidates += [Path.cwd() / "config.json", PROJECT_ROOT / "config.json"]
        for cand in candidates:
            if cand.is_file():
                try:
                    data.update(json.loads(cand.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, OSError) as e:
                    raise ValueError(f"配置文件 {cand} 解析失败: {e}") from e
                break

        env_layer = effective_env()
        for key, env in ENV_MAP.items():
            value = env_layer.get(env)
            if value:
                data[key] = value

        return cls(
            api_key=str(data["api_key"]),
            base_url=str(data["base_url"]).rstrip("/"),
            model=str(data["model"]),
            max_iterations=int(data["max_iterations"]),
            request_timeout=int(data["request_timeout"]),
            max_retries=max(1, int(data["max_retries"])),
            memory_chars=int(data["memory_chars"]),
            workspace=str(data["workspace"]),
            protocol=str(data["protocol"]).lower(),
            max_tokens=int(data["max_tokens"]),
        )
