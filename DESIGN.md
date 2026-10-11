# CodeMentor 设计文档（DESIGN.md）

> 技术选型：Python 3.9+ · requests · pytest（零 Agent 框架依赖，LLM 原生 API 路线）

---

## 1. 需求分析与目标

本项目构建一个代码助手 Agent，覆盖以下能力点：

| 要求 | 设计回应 |
|------|----------|
| LLM 调用 | 双协议客户端：OpenAI Chat Completions（绝大多数服务商）+ Anthropic Messages（智谱 Coding 套餐通道 / Claude），统一 chat() 接口，Agent 层无感知 |
| Prompt 设计 | 系统提示词 = 基础 ReAct 协议 + 模式化指令 + 工具文档 + few-shot 示例，四段拼装 |
| 工具集成 | 插件式工具注册表，6 种开箱工具，新增工具零侵入（见 §7） |
| Agent 循环 | 输入 → Thought → Action → Observation → … → Final Answer，全程可观测 |
| 上下文记忆 | 会话级多轮记忆 + 字符预算滑动窗口 + 滚动摘要 |
| 错误处理与重试 | 四层防线（LLM 层/解析层/工具层/循环层），见 §8 |

五个可选方向（审查/解释/测试生成/重构/代码生成）**全部实现**为五种工作模式，
并由 `auto` 模式自动路由，避免只能演示单一场景。

## 2. 总体架构

```
┌────────── Web 界面（web.py + web/，Flask）──────────┐
│ 聊天交互 / 模式切换 / ReAct 过程时间线 / 事件轮询     │
└──────────────────────────┬─────────────────────────┘
┌────────────────────────── CLI（main.py）────────────┐
│ argparse 参数解析 / REPL 命令路由 / 彩色过程展示      │
└──────────────────────────┬─────────────────────────┘
                           │ 共用 emit(kind, **data) 事件回调（观察者模式）
                    ┌──────▼───────────────┐
                    │      Agent           │  agent.py —— 唯一的决策循环
                    │  while 预算内:        │
                    │   LLM(messages)      │
                    │   parse_reply()      │──► Final? ──► 返回结果
                    │   registry.execute() │
                    │   memory.add(obs)    │
                    └───┬───────┬───────┬──┘
                        │       │       │
          ┌─────────────▼─┐ ┌───▼─────┐ ┌▼──────────────────────┐
          │ ContextMemory │ │Parsing  │ │ LLM 抽象（双协议）      │
          │ turns+summary │ │协议容错  │ │ OpenAI / Anthropic    │
          └───────────────┘ └─────────┘ │ MockLLM（离线/测试）    │
                                      └───────────────────────┘
                        │
          ┌─────────────▼───────────────────────┐
          │ ToolRegistry                        │
          │ fs_tools: read/write/list/search    │
          │ code_tools: execute_code/run_tests  │
          └─────────────────────────────────────┘
```

分层职责与依赖方向（自上而下单向依赖，核心包不 import UI 层）：

| 层 | 模块 | 职责 |
|----|------|------|
| 表现层 | `main.py` / `web.py + web/` | CLI 参数与 REPL；Flask 服务、后台任务线程、事件轮询 API、前端页面 |
| 组装层 | `app.py` | `create_agent()` 工厂：读配置、构建 LLM/工具/记忆/Agent，CLI 与 Web 唯一共用入口 |
| 决策层 | `agent.py` | ReAct 循环、终止判定、强制总结 |
| 支撑层 | `parsing.py` / `memory.py` / `prompts.py` / `llm.py` / `config.py` | 协议解析、记忆、提示词、模型访问（双协议）、配置（.env） |
| 能力层 | `tools/` | 工具实现与安全边界 |

**解耦关键**：Agent 通过 `emit()` 向外发布事件（episode_start/action/observation/final…），
CLI 的 ConsoleUI 和 Web 的任务事件缓冲区是两个平行的订阅者，单元测试订阅同一事件流做断言。
Agent 核心完全不知道 UI 的存在——Web 界面的加入对 `agent.py` 是零改动。

### Web 层设计（web.py + web/）

- **无构建步骤的前端**：原生 HTML/CSS/JS 单页（暗色聊天界面），CDN 引入
  marked/DOMPurify/highlight.js 做 Markdown 渲染与代码高亮，CDN 不可用时自动降级纯文本；
- **后台任务线程**：`POST /api/chat` 把 Agent.run 放进 daemon 线程（单条消息
  上限 20000 字符，超长返回 400），事件通过 emit 回调写入任务缓冲区；
  `GET /api/task/<id>?since=` 增量轮询（700ms），相比 SSE 对代理/断连更稳健；
- **前端可视化 ReAct**：推理过程卡片实时追加 Thought/Action/Observation 时间线，
  最终答复以 Markdown 卡片渲染并附元信息（轮数、工具调用链、是否被强制总结）；
- **首次配置向导**：无 `.env` 时全屏弹出向导（**24 项服务商预设按
  国内/国际/聚合/本地/自定义分组**，选中自动填充 protocol/base_url/推荐模型；
  "自定义"项额外提供协议选择，可接任意中转/自建端点），`POST /api/setup`
  校验后由 `write_env_file()` 持久化到 `.env`（更新已有键、保留其余行）并立即
  重建 Agent——配置"有记忆"，下次启动直接进入聊天界面；
- **未配置兜底**：向导之外 `/api/chat` 仍返回 503 与修复提示，服务永不因缺配置拒绝启动。

## 3. Agent 循环设计（核心）

### 3.1 ReAct 协议

模型每轮必须输出两种格式之一：

```
Thought: <推理>
Action: {"tool": "<名称>", "args": {...}}        ← 请求调用工具

Thought: <推理总结>
Final Answer: <面向用户的 Markdown 答复>           ← 结束任务
```

选择**文本协议**而非 OpenAI function calling 的理由：
(a) 任何兼容服务商（含本地 Ollama）都能跑，不依赖各家的函数调用实现质量；
(b) Thought 显式可见，便于演示与调试 Agent 的推理过程；
(c) 解析逻辑完全可控，可以做针对性容错。

### 3.2 循环伪代码

```python
def run(user_input):
    memory.add("user", user_input)
    while productive < max_iterations and format_failures < MAX_FORMAT_RETRIES:
        reply = llm.chat(memory.build_messages(system_prompt))
        parsed = parse_reply(reply)                    # 永不抛异常
        if parsed.final:                               # 终止条件 1
            memory.add("assistant", parsed.final)
            return AgentResult(final, steps, truncated=False)
        if parsed.tool:
            productive += 1                            # 有效轮数 +1
            observation = registry.execute(tool, args) # 工具层永不抛异常
        else:
            format_failures += 1                       # 格式漂移不占推理预算
            observation = FORMAT_ERROR_HINT            # 自纠：格式错误回给模型
        memory.add("assistant", reply)
        memory.add("user", "Observation: " + observation)
    return force_final_answer()                        # 终止条件 2：强制总结
```

四个设计决策：

1. **Observation 以 user 角色注入**。ReAct 的经典做法，
   保证任何严格角色校验的兼容服务都能接受这份 messages。
2. **解析失败不是异常，而是一次"负面观察"**。模型偶尔不守格式时，
   Agent 把纠错提示（含可复制模板）作为 Observation 回灌，模型下一轮自修复——
   这比直接抛错中断体验好得多（测试 `test_parse_failure_gets_format_hint` 验证）。
3. **格式漂移不消耗推理预算**。模型偶发连续格式漂移时，若占用轮数预算会把
   任务挤爆；因此有效预算只统计工具调用轮，格式失败单独计数（上限 4 次），
   超限才强制总结
   （测试 `test_format_failures_do_not_consume_budget` / `test_excessive_format_failures_force_final`）。
4. **预算耗尽后强制总结而不是报错**。注入"禁止再调用工具，立即给出 Final Answer"
   指令再调一次 LLM，保证用户总能拿到结论，同时 `truncated=True` 标记如实暴露降级。

### 3.3 测试生成模式的闭环示例

`test` 模式提示词强制流程：读被测代码 → 列用例 → `write_file` 写测试 →
**必须 `run_tests` 实跑** → 失败则修复重写。工具的失败输出（如断言失败详情）
作为 Observation 回到模型，形成"生成-执行-修复"闭环，这是 Agent 相比
单次调用 LLM 的本质增值。

## 4. 提示词设计（prompts.py）

系统提示词四段式拼装：

```
你是 CodeMentor…
# 当前工作模式      ← 模式化指令（每个方向一段结构化产出要求）
# 可用工具          ← 由 ToolRegistry.docs() 自动生成，增工具自动进提示词
# 工作方式(ReAct)   ← 协议格式 + few-shot 双示例（工具调用 & 最终答复）
# 规则              ← 一次一工具 / 错误要自纠 / 轮数预算 / 禁止虚构 Observation
```

要点：
- **few-shot 双示例**：分别演示 Action 与 Final Answer 的正确写法，
  显著降低格式漂移率；
- **产出结构约束**：每种模式明确"最终输出必须包含什么"
  （如 review 模式要求问题表格含 严重度/行号/修复建议），
  把"输出质量"从模型自觉变成协议要求；
- **反幻觉约束**："不要虚构文件内容，一切结论以 Observation 为准"。

## 5. 工具系统设计（tools/）

### 5.1 注册表模式

```python
Tool(name, description, parameters, func, example)   # 自描述
ToolRegistry.register/get/docs/execute
```

- `docs()` 自动生成面向 LLM 的工具说明 → 提示词与工具实现永不脱节；
- `execute()` 是唯一执行入口，统一做：未知工具、参数不匹配、
  运行时异常三种兜底 + 超长输出截断（保留头尾并标注总长）。

### 5.2 安全边界（边界情况处理）

| 威胁 | 防护 |
|------|------|
| 路径穿越（`../`、绝对路径） | `_safe_path` 统一 resolve 后 relative_to 校验，越界即拒 |
| 大文件/大目录撑爆上下文 | 读 200KB 上限、目录 200 条、搜索 50 条、观察 3000 字符截断 |
| 恶意/失控代码 | 子进程隔离 + 超时强杀（默认 10s，上限 30s）；危险调用黑名单拦截（rmtree/os.system/subprocess 等），并明确提示改用 run_tests |
| 临时文件污染 | 执行代码写入 `.codementor_tmp/` 沙箱目录，执行后清理 |
| 非法正则 | 编译失败返回可读错误，模型可自行修正表达式 |

> 黑名单为演示级防护，可被混淆绕过；生产化方案见 §10。

## 6. 上下文记忆（memory.py）

- **数据结构**：`turns`（完整保留近期对话）+ `summary`（被压缩的早期对话）；
- **预算**：按字符计（默认 24000）。新增消息超预算时，从最旧开始逐条出队；
- **压缩策略**（无 LLM 参与、确定性，便于测试）：用户消息留前 160 字符、
  助手结论留 400、工具观察留 80，拼接进滚动摘要（上限 3000，超出丢最旧）；
- **注入方式**：摘要作为第二条 system 消息（"更早对话的压缩摘要"）。

效果：长会话中早期的工具巨量输出被压缩，但用户问过什么、Agent 结论是什么
始终可追溯——多轮测试 `test_history_persists_between_runs` 验证。

## 7. 错误处理矩阵（四层防线）

| 层 | 故障 | 策略 | 测试 |
|----|------|------|------|
| LLM 层 | 网络/429/5xx | 指数退避 + 随机抖动重试（默认 3 次，上限 15s） | test_retry_on_429_then_success |
| LLM 层 | 401/400 等客户端错 | **不重试**，立即抛出可读错误（含响应体片段） | test_client_error_no_retry |
| 解析层 | 格式漂移 | 纠错提示（含模板）作为 Observation 回灌，模型自修复；格式失败不占推理预算，连续 4 次后强制总结 | test_parse_failure_gets_format_hint / test_format_failures_do_not_consume_budget |
| 工具层 | 任何异常 | 转为 `错误: ...` 字符串观察（含修正线索），循环继续 | test_unknown_tool_returns_error_observation |
| 循环层 | 轮数耗尽 | 注入强制总结指令，保证有产出 | test_max_iterations_forces_final |
| UI 层 | emit 回调崩溃 | 吞掉异常，不影响 Agent | test_events_do_not_break_agent |

## 8. 可扩展性

**新增一个工具**（以 `count_lines` 为例，3 步）：

```python
# 1. 实现（任意模块）
def count_lines(path): return f"{len(open(path, encoding='utf-8').readlines())} 行"

# 2. 注册（fs_tools.build_fs_tools 追加）
Tool(name="count_lines", description="统计文件行数",
     parameters={"path": {"type": "string", "description": "文件路径"}},
     func=lambda path: count_lines(path))

# 3. 完成。工具文档自动进入系统提示词，Agent 自动可用
```

**新增一个模式**：在 `prompts.MODES` 加一个条目（label + instruction）即可，
CLI 参数与 `/mode` 命令自动支持。

**切换 LLM 服务商**：改 `base_url` + `model`（+ api_key），无代码改动；
**切换协议**（openai / anthropic）：改 `protocol` 一个字段。

> 智谱 GLM Coding 套餐的额度仅在 Anthropic 兼容端点生效（标准 paas/v4
> 端点按账户余额计费），因此实现了双协议：`AnthropicCompatibleLLM`
> 处理 system 抽离、连续同角色合并、必填 max_tokens 等协议差异，
> 与 OpenAI 客户端共享同一套重试策略。

## 9. 测试策略（120 个用例，全部离线可跑）

| 文件 | 覆盖 |
|------|------|
| test_parsing.py | 最终答复/工具调用/围栏 JSON/尾逗号修复/两行式 Action/括号配平扫描/解析失败/示例劫持回归/Unicode 工具名拒绝 |
| test_tools.py | 读写的正常与越界路径、目录过滤、正则搜索含非法正则、代码执行(成功/相对路径/stderr/超时/危险调用/空代码)、注册表兜底与截断 |
| test_memory.py | messages 结构、多轮保留、滑窗压缩进摘要、摘要上限、清空 |
| test_agent.py | 工具调用→最终答复全流程、未知工具自纠、坏路径自纠、格式自纠、格式漂移不占预算、超限强制收尾、轮数上限强制总结、Agent 层 LLM 重试、多轮记忆、UI 回调隔离、模式切换 |
| test_llm.py | 双协议：openai 与 anthropic 各自的请求体形状(鉴权头/system 分离/max_tokens/连续同角色合并)、429 重试成功、网络错误重试、重试耗尽、401 不重试、超时提示、MockLLM |
| test_config.py | 默认值/config.json 覆盖/.env 加载与真实环境变量优先/.env 胜过 config.json/write_env_file 新建与更新保留/坏配置报错 |
| test_web.py | 页面与静态资源、/api/status 结构、未配置态 503、配置向导(预设/保存持久化/重建 Agent/校验 400)、完整聊天流程(事件流+final)、空消息/超长消息 400、模式切换与记忆清空、LLM 错误转 error 事件 |

关键手法：`MockLLM` 脚本化模型回复 + 真实工具执行，
使得"Agent 循环逻辑"的每条分支都能在无网络环境下精确复现与断言。

功能验证记录（examples/ 下的运行记录，智谱 GLM 真实调用）：
- 代码审查：命中示例样本全部 4 个预埋缺陷（行号一致）；
- 测试生成：生成 20 个 pytest 用例并实跑，其中 2 个失败用例正是缺陷用例；
- 重构建议：产出重构版与 16 个回归测试（已并入测试套件）；
- 代码解释 / 代码生成：输出行号级讲解；生成代码带类型注解并通过执行验证。

## 10. 局限与改进方向

1. **代码沙箱强度**：黑名单拦截可被混淆绕过。改进：容器级隔离
   （Docker/gVisor）、资源配额（内存/CPU）、无网络命名空间。
2. **串行工具调用**：一次一个工具。改进：支持并行 Action 批量执行
   （需配合 function calling 的 multi-tool-call 语义）。
3. **记忆压缩为启发式截断**。改进：用 LLM 生成语义摘要，
   或引入向量库做长期记忆检索。
4. **Web 界面**：现有 Flask + 事件轮询方案可升级为 FastAPI + SSE 的流式推送
   （架构上只需新增一个 emit 订阅者，核心零改动）。
