#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CodeMentor Web 界面服务。

Agent 任务在后台线程执行，事件写入任务缓冲区，前端通过
/api/task/<id>?since= 轮询增量获取。

用法:
  python web.py               # http://127.0.0.1:8000（自动打开浏览器）
  python web.py --mock        # 离线演示（无需 .env）
  python web.py --port 5000
"""

import argparse
import threading
import webbrowser
from pathlib import Path
from typing import Dict, Optional

from flask import Flask, jsonify, request, send_from_directory

from codementor.agent import Agent
from codementor.app import MissingAPIKeyError, create_agent
from codementor.config import write_env_file
from codementor.llm import LLMError
from codementor.prompts import MODES, get_mode_names

PROJECT_ROOT = Path(__file__).resolve().parent

# 单条消息长度上限（防止超长输入撑大上下文）
MAX_MESSAGE_CHARS = 20000

# 配置向导的服务商预设（模型名仅供参考，可在向导中修改）
PROVIDER_PRESETS = [
    # ---------- 国内大模型 ----------
    {"id": "zhipu-coding", "group": "国内大模型", "label": "智谱 GLM Coding 套餐（Lite/Pro，推荐）",
     "protocol": "anthropic", "base_url": "https://open.bigmodel.cn/api/anthropic",
     "models": ["glm-5.3-flash", "glm-5.3", "glm-4.6"]},
    {"id": "zhipu", "group": "国内大模型", "label": "智谱 GLM 按量付费 / 免费档",
     "protocol": "openai", "base_url": "https://open.bigmodel.cn/api/paas/v4",
     "models": ["glm-4.5-flash", "glm-4-flash"]},
    {"id": "deepseek", "group": "国内大模型", "label": "DeepSeek 深度求索",
     "protocol": "openai", "base_url": "https://api.deepseek.com/v1",
     "models": ["deepseek-chat", "deepseek-reasoner"]},
    {"id": "qwen", "group": "国内大模型", "label": "通义千问（阿里云百炼）",
     "protocol": "openai", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "models": ["qwen-plus", "qwen-max", "qwen-turbo"]},
    {"id": "moonshot", "group": "国内大模型", "label": "Kimi / Moonshot 月之暗面",
     "protocol": "openai", "base_url": "https://api.moonshot.cn/v1",
     "models": ["kimi-k2-turbo-preview", "kimi-k2-0905-preview", "moonshot-v1-128k"]},
    {"id": "doubao", "group": "国内大模型", "label": "豆包（火山方舟）",
     "protocol": "openai", "base_url": "https://ark.cn-beijing.volces.com/api/v3",
     "models": ["doubao-seed-1.6", "doubao-pro-32k"]},
    {"id": "ernie", "group": "国内大模型", "label": "文心一言（百度千帆）",
     "protocol": "openai", "base_url": "https://qianfan.baidubce.com/v2",
     "models": ["ernie-4.5-turbo-8k", "ernie-4.0-8k", "ernie-speed-8k"]},
    {"id": "hunyuan", "group": "国内大模型", "label": "腾讯混元",
     "protocol": "openai", "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
     "models": ["hunyuan-turbos-latest", "hunyuan-large"]},
    {"id": "spark", "group": "国内大模型", "label": "讯飞星火",
     "protocol": "openai", "base_url": "https://spark-api-open.xf-yun.com/v1",
     "models": ["4.0Ultra", "generalv3.5", "lite"]},
    {"id": "minimax", "group": "国内大模型", "label": "MiniMax 稀宇科技",
     "protocol": "openai", "base_url": "https://api.minimax.chat/v1",
     "models": ["MiniMax-M1", "MiniMax-Text-01", "abab6.5s-chat"]},
    {"id": "stepfun", "group": "国内大模型", "label": "阶跃星辰 StepFun",
     "protocol": "openai", "base_url": "https://api.stepfun.com/v1",
     "models": ["step-2-16k", "step-1v-8k"]},
    {"id": "lingyi", "group": "国内大模型", "label": "零一万物 Yi",
     "protocol": "openai", "base_url": "https://api.lingyiwanwu.com/v1",
     "models": ["yi-large", "yi-lightning"]},
    # ---------- 国际大模型 ----------
    {"id": "openai", "group": "国际大模型", "label": "OpenAI",
     "protocol": "openai", "base_url": "https://api.openai.com/v1",
     "models": ["gpt-5", "gpt-4o-mini", "gpt-4o"]},
    {"id": "anthropic", "group": "国际大模型", "label": "Anthropic Claude（官方）",
     "protocol": "anthropic", "base_url": "https://api.anthropic.com",
     "models": ["claude-sonnet-4-5", "claude-opus-4-1", "claude-haiku-4-5"]},
    {"id": "gemini", "group": "国际大模型", "label": "Google Gemini（OpenAI 兼容端点）",
     "protocol": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
     "models": ["gemini-2.5-flash", "gemini-2.5-pro"]},
    {"id": "grok", "group": "国际大模型", "label": "xAI Grok",
     "protocol": "openai", "base_url": "https://api.x.ai/v1",
     "models": ["grok-4", "grok-3"]},
    {"id": "mistral", "group": "国际大模型", "label": "Mistral AI",
     "protocol": "openai", "base_url": "https://api.mistral.ai/v1",
     "models": ["mistral-large-latest", "codestral-latest"]},
    # ---------- 聚合平台 ----------
    {"id": "siliconflow", "group": "聚合平台", "label": "硅基流动 SiliconFlow（多模型聚合）",
     "protocol": "openai", "base_url": "https://api.siliconflow.cn/v1",
     "models": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct"]},
    {"id": "openrouter", "group": "聚合平台", "label": "OpenRouter（国际聚合，需外网）",
     "protocol": "openai", "base_url": "https://openrouter.ai/api/v1",
     "models": ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4.5", "deepseek/deepseek-chat"]},
    {"id": "groq", "group": "聚合平台", "label": "Groq（极速开源模型推理）",
     "protocol": "openai", "base_url": "https://api.groq.com/openai/v1",
     "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]},
    # ---------- 本地部署 ----------
    {"id": "ollama", "group": "本地部署", "label": "本地 Ollama",
     "protocol": "openai", "base_url": "http://localhost:11434/v1",
     "models": ["qwen2.5-coder:7b", "llama3.1:8b"]},
    {"id": "lmstudio", "group": "本地部署", "label": "本地 LM Studio",
     "protocol": "openai", "base_url": "http://localhost:1234/v1",
     "models": []},
    {"id": "vllm", "group": "本地部署", "label": "本地 vLLM（默认端口 8000，注意避开本服务）",
     "protocol": "openai", "base_url": "http://localhost:8000/v1",
     "models": []},
    # ---------- 自定义 ----------
    {"id": "custom", "group": "自定义", "label": "自定义 / 中转接口（手填协议与地址）",
     "protocol": "openai", "base_url": "",
     "models": []},
]


def create_app(agent: Optional[Agent] = None, mock: bool = False,
               unconfigured: bool = False, env_path: Optional[str] = None,
               agent_factory=None) -> Flask:
    """构建 Flask 应用。agent 可注入（测试）；env_path/agent_factory 为测试钩子。"""
    app = Flask(__name__, static_folder=str(PROJECT_ROOT / "web"),
                static_url_path="/static")
    app.json.ensure_ascii = False

    state: Dict = {
        "agent": None, "config": None, "configured": False,
        "busy": False, "tasks": {}, "task_seq": 0,
    }
    lock = threading.Lock()

    # ---------------------------------------------------------------- 事件

    def emit(kind: str, **data) -> None:
        with lock:
            task = state["tasks"].get(state.get("current_task"))
            if task is not None and not task["done"]:
                task["events"].append({"seq": task["next_seq"], "kind": kind,
                                       "data": _jsonable(data)})
                task["next_seq"] += 1

    def bind_agent(new_agent, config=None) -> None:
        state["agent"] = new_agent
        if config is not None:
            state["config"] = config
        state["configured"] = new_agent is not None
        if new_agent is not None:
            new_agent.emit_handler = emit

    if agent is not None:
        bind_agent(agent)
    elif not unconfigured:
        try:
            built, config = create_agent(provider="mock" if mock else "api")
            bind_agent(built, config)
        except (MissingAPIKeyError, ValueError):
            state["configured"] = False

    def run_task(task: Dict, message: str) -> None:
        try:
            task["result"] = state["agent"].run(message)
        except LLMError as e:
            emit("error", message=f"LLM 调用失败: {e}")
        except Exception as e:  # noqa: BLE001 - 后台线程兜底
            emit("error", message=f"{type(e).__name__}: {e}")
        finally:
            with lock:
                task["done"] = True
                state["busy"] = False

    # ---------------------------------------------------------------- 页面

    @app.get("/")
    def index():
        return send_from_directory(str(PROJECT_ROOT / "web"), "index.html")

    # ---------------------------------------------------------------- API

    @app.get("/api/status")
    def api_status():
        cfg = state["config"]
        agent = state["agent"]
        tools = []
        if agent is not None:
            tools = [
                {"name": t.name, "description": t.description.split("，")[0]}
                for t in agent.registry._tools.values()
            ]
        return jsonify({
            "configured": state["configured"],
            "mock": mock,
            "busy": state["busy"],
            "mode": agent.mode if agent else "auto",
            "modes": [
                {"id": m, "label": MODES[m]["label"]} for m in get_mode_names()
            ],
            "model": "(mock 演示)" if mock else (cfg.model if cfg else ""),
            "protocol": cfg.protocol if cfg else "",
            "workspace": str(Path(cfg.workspace).resolve()) if cfg else "",
            "tools": tools,
            "memory_turns": len(agent.memory.turns) if agent else 0,
        })

    @app.get("/api/presets")
    def api_presets():
        """配置向导的服务商预设列表。"""
        return jsonify({"presets": PROVIDER_PRESETS})

    @app.post("/api/setup")
    def api_setup():
        """保存配置向导提交的接入参数：写入 .env（持久记忆）并重建 Agent。"""
        if state["busy"]:
            return jsonify({"error": "任务执行中，暂不能修改配置"}), 409
        data = request.get_json(silent=True) or {}
        api_key = str(data.get("api_key", "")).strip()
        protocol = str(data.get("protocol", "openai")).strip().lower()
        base_url = str(data.get("base_url", "")).strip().rstrip("/")
        model = str(data.get("model", "")).strip()

        if not api_key:
            return jsonify({"error": "API Key 不能为空"}), 400
        if protocol not in ("openai", "anthropic"):
            return jsonify({"error": "protocol 只能是 openai 或 anthropic"}), 400
        if not base_url.startswith(("http://", "https://")):
            return jsonify({"error": "接口地址必须以 http(s):// 开头"}), 400
        if not model:
            return jsonify({"error": "模型名不能为空"}), 400

        try:
            write_env_file(
                {
                    "CODEMENTOR_API_KEY": api_key,
                    "CODEMENTOR_PROTOCOL": protocol,
                    "CODEMENTOR_BASE_URL": base_url,
                    "CODEMENTOR_MODEL": model,
                },
                path=Path(env_path) if env_path else None,
            )
        except OSError as e:
            return jsonify({"error": f"写入 .env 失败: {e}"}), 500

        factory = agent_factory or create_agent
        try:
            built, config = factory()
        except (MissingAPIKeyError, ValueError) as e:
            return jsonify({"error": f"配置已保存但 Agent 构建失败: {e}"}), 500
        with lock:
            bind_agent(built, config)
        return jsonify({"ok": True, "model": config.model, "protocol": config.protocol})

    @app.post("/api/chat")
    def api_chat():
        if not state["configured"] or state["agent"] is None:
            return jsonify({"error": "未配置 API Key：请复制 .env.example 为 .env 并填写，然后重启服务"}), 503
        message = (request.get_json(silent=True) or {}).get("message", "").strip()
        if not message:
            return jsonify({"error": "消息不能为空"}), 400
        if len(message) > MAX_MESSAGE_CHARS:
            return jsonify(
                {"error": f"消息过长（{len(message)} 字符，上限 {MAX_MESSAGE_CHARS}），请拆分后分次发送"}
            ), 400
        with lock:
            if state["busy"]:
                return jsonify({"error": "上一个任务还在执行中，请稍候"}), 409
            state["task_seq"] += 1
            task_id = state["task_seq"]
            task = {"events": [], "next_seq": 0, "done": False, "result": None}
            state["tasks"][task_id] = task
            state["current_task"] = task_id
            state["busy"] = True
        threading.Thread(target=run_task, args=(task, message), daemon=True).start()
        return jsonify({"task_id": task_id}), 202

    @app.get("/api/task/<int:task_id>")
    def api_task(task_id: int):
        since = request.args.get("since", 0, type=int)
        with lock:
            task = state["tasks"].get(task_id)
            if task is None:
                return jsonify({"error": "任务不存在"}), 404
            payload = {
                "events": [e for e in task["events"] if e["seq"] >= since],
                "done": task["done"],
                "next_since": task["next_seq"],
            }
            result = task["result"]
        if result is not None:
            payload["final"] = {
                "answer": result.final_answer,
                "iterations": result.iterations,
                "tool_calls": result.tool_calls,
                "truncated": result.truncated,
            }
        return jsonify(payload)

    @app.post("/api/mode")
    def api_mode():
        mode = (request.get_json(silent=True) or {}).get("mode", "")
        if mode not in MODES:
            return jsonify({"error": f"未知模式 '{mode}'"}), 400
        if state["busy"]:
            return jsonify({"error": "任务执行中，暂不能切换模式"}), 409
        state["agent"].mode = mode          # 切换模式会重建系统提示词
        state["agent"].memory.clear()       # 模式语境不同，清空历史避免串扰
        return jsonify({"mode": mode})

    @app.post("/api/reset")
    def api_reset():
        if state["agent"] is not None:
            state["agent"].memory.clear()
        return jsonify({"ok": True})

    return app


def _jsonable(data: Dict) -> Dict:
    """只保留可 JSON 序列化的事件数据。"""
    clean = {}
    for key, value in data.items():
        try:
            jsonify(value)
            clean[key] = value
        except Exception:
            clean[key] = str(value)
    return clean


def main() -> None:
    parser = argparse.ArgumentParser(prog="codementor-web",
                                     description="CodeMentor Web 界面")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--mock", action="store_true", help="离线演示模式（无需 .env）")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    app = create_app(mock=args.mock)
    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"CodeMentor Web 已启动: {url}  (Ctrl+C 退出)")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
