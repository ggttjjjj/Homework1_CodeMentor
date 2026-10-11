/* ============ CodeMentor Web 前端逻辑 ============ */
"use strict";

const $ = (id) => document.getElementById(id);
const messagesEl = $("messages");
const inputEl = $("input");
const sendBtn = $("send");

const state = {
  status: null,
  busy: false,
  taskId: null,
  since: 0,
  pollTimer: null,
  episode: null, // 当前回合的 DOM 句柄
};

/* ---------------- 基础工具 ---------------- */

async function fetchJSON(url, options) {
  const resp = await fetch(url, options);
  let body = {};
  try { body = await resp.json(); } catch (_) { /* 忽略 */ }
  if (!resp.ok) throw Object.assign(new Error(body.error || `HTTP ${resp.status}`), { status: resp.status });
  return body;
}

function esc(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

function toast(message, type = "") {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast ${type}`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), 3800);
}

function renderMarkdown(text) {
  if (window.marked && window.DOMPurify) {
    marked.setOptions({ breaks: true, gfm: true });
    const html = DOMPurify.sanitize(marked.parse(text || ""));
    const wrap = document.createElement("div");
    wrap.className = "md";
    wrap.innerHTML = html;
    if (window.hljs) wrap.querySelectorAll("pre code").forEach((b) => hljs.highlightElement(b));
    return wrap;
  }
  const pre = document.createElement("pre");
  pre.textContent = text || "";
  return pre;
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

/* ---------------- 状态与侧边栏 ---------------- */

const MODE_ICONS = {
  auto: '<path d="M12 2a10 10 0 1 0 10 10h-2a8 8 0 1 1-8-8V2z"/><path d="M12 6v6l4 2"/>',
  review: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  explain: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  test: '<path d="M9 3h6M10 3v5L4.5 18a2 2 0 0 0 1.8 3h11.4a2 2 0 0 0 1.8-3L14 8V3"/><path d="m7 15 3 3 7-8"/>',
  refactor: '<path d="M14 4l6 6-6 6M20 10H9a5 5 0 0 0-5 5v3"/>',
  generate: '<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>',
};

const MODE_HINTS = {
  auto: "自动判断任务类型并规划工具调用",
  review: "定位 Bug 与质量问题，输出问题清单 + 修复代码",
  explain: "逐块讲解逻辑、复杂度分析、生成中文注释",
  test: "生成 pytest 用例并实际运行验证，失败自动修复",
  refactor: "识别坏味道，给出重构手法与前后对比代码",
  generate: "自然语言 → 带类型注解的实现 + 使用示例",
};

const SUGGESTIONS = {
  auto: [
    "审查 examples/buggy.py 的代码质量",
    "为 examples/buggy.py 生成单元测试并运行验证",
    "解释 examples/buggy.py 中 parse_positive 的逻辑",
    "分析 examples/buggy.py 的代码坏味道并给出重构建议",
  ],
  review: ["请审查 examples/buggy.py 的代码质量", "搜索工作区内所有 TODO 并评估风险"],
  explain: ["解释 examples/buggy.py 中 average 和 first_index_of 的逻辑"],
  test: ["为 examples/buggy.py 生成单元测试并运行验证"],
  refactor: ["分析 examples/buggy.py 的代码坏味道并给出重构建议"],
  generate: ["写一个 Python 函数 is_palindrome(s)，忽略大小写与非字母数字字符"],
};

async function refreshStatus() {
  state.status = await fetchJSON("/api/status");
  const s = state.status;
  $("config-banner").classList.toggle("hidden", true); // 向导已取代横幅
  if (!s.configured) {
    showWizard();
    return s;
  }
  $("setup-wizard").classList.add("hidden");
  renderModes(s.mode);
  $("st-model").textContent = s.model || "–";
  $("st-protocol").textContent = s.protocol || (s.mock ? "mock" : "–");
  const ws = $("st-workspace");
  ws.textContent = s.workspace ? s.workspace.split(/[\\/]/).pop() || s.workspace : "–";
  ws.title = s.workspace;
  $("st-memory").textContent = s.memory_turns;
  renderTools(s.tools);
  setBusy(s.busy && state.taskId != null);
  return s;
}

function renderModes(active) {
  const nav = $("modes");
  nav.innerHTML = "";
  for (const m of state.status.modes) {
    const item = document.createElement("div");
    item.className = "mode-item" + (m.id === active ? " active" : "");
    item.innerHTML = `
      <svg class="mi-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${MODE_ICONS[m.id] || ""}</svg>
      <span class="mi-label">${m.label}</span>
      <span class="mi-id">${m.id}</span>`;
    item.onclick = () => switchMode(m.id);
    nav.appendChild(item);
  }
  $("mode-title").textContent = (state.status.modes.find((m) => m.id === active) || {}).label || "综合助手";
  $("mode-hint").textContent = MODE_HINTS[active] || "";
  renderChips(active);
}

function renderTools(tools) {
  const ul = $("tools");
  ul.innerHTML = "";
  for (const t of tools || []) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="tname">${esc(t.name)}</span><span>${esc(t.description)}</span>`;
    ul.appendChild(li);
  }
}

function renderChips(mode) {
  const box = $("chips");
  box.innerHTML = "";
  const list = SUGGESTIONS[mode] || SUGGESTIONS.auto;
  list.forEach((text) => {
    const chip = document.createElement("button");
    chip.className = "chip";
    chip.textContent = text;
    chip.onclick = () => { inputEl.value = text; sendMessage(); };
    box.appendChild(chip);
  });
}

async function switchMode(mode) {
  if (state.busy) return toast("任务执行中，暂不能切换模式", "error");
  try {
    await fetchJSON("/api/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    await refreshStatus();
    toast(`已切换到 ${mode} 模式，对话记忆已清空`);
  } catch (e) {
    toast(e.message, "error");
  }
}

$("btn-reset").onclick = async () => {
  try {
    await fetchJSON("/api/reset", { method: "POST" });
    await refreshStatus();
    toast("已清空对话记忆");
  } catch (e) {
    toast(e.message, "error");
  }
};

$("tools-toggle").onclick = () => $("tools").classList.toggle("hidden");

/* ---------------- 空状态 ---------------- */

const FEAT_ICONS = {
  review: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  test: '<path d="M9 3h6M10 3v5L4.5 18a2 2 0 0 0 1.8 3h11.4a2 2 0 0 0 1.8-3L14 8V3"/><path d="m7 15 3 3 7-8"/>',
  explain: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  refactor: '<path d="M14 4l6 6-6 6M20 10H9a5 5 0 0 0-5 5v3"/>',
};

function renderEmptyState() {
  messagesEl.innerHTML = `
    <div class="empty-state">
      <div class="big-logo">C</div>
      <h3>你好，我是 CodeMentor</h3>
      <p>一个 ReAct 式代码助手 Agent —— 我会<b>真实读取你的工作区文件</b>、<br>执行代码、运行测试，再基于观察结果给出回答。</p>
      <div class="features">
        <div class="feat"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${FEAT_ICONS.review}</svg><span><b>代码审查</b>定位 Bug 与质量问题</span></div>
        <div class="feat"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${FEAT_ICONS.test}</svg><span><b>测试生成</b>生成用例并实跑验证</span></div>
        <div class="feat"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${FEAT_ICONS.explain}</svg><span><b>代码解释</b>分块讲解 + 中文注释</span></div>
        <div class="feat"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${FEAT_ICONS.refactor}</svg><span><b>重构建议</b>坏味道与前后对比</span></div>
      </div>
    </div>`;
}

/* ---------------- 消息渲染 ---------------- */

function addUserMessage(text) {
  messagesEl.querySelector(".empty-state")?.remove();
  const col = document.createElement("div");
  col.className = "message-col";
  col.innerHTML = `<div class="user-msg"><div class="user-bubble">${esc(text)}</div></div>`;
  messagesEl.appendChild(col);
  scrollToBottom();
}

function createEpisode() {
  const col = document.createElement("div");
  col.className = "message-col agent-msg";
  col.innerHTML = `
    <div class="trace-card" data-collapsed="false">
      <div class="trace-head">
        <span class="live-dot"></span>
        <span class="chev">▾</span>
        <span class="trace-title">推理过程</span>
        <span class="step-count">0 步</span>
      </div>
      <div class="trace-body"></div>
    </div>
    <div class="thinking hidden">
      <span class="dots"><span></span><span></span><span></span></span>
      <span class="thinking-text">Agent 正在思考…</span>
    </div>`;
  messagesEl.appendChild(col);
  scrollToBottom();

  const card = col.querySelector(".trace-card");
  const body = col.querySelector(".trace-body");
  const count = col.querySelector(".step-count");
  const thinking = col.querySelector(".thinking");
  const thinkingText = col.querySelector(".thinking-text");
  const title = col.querySelector(".trace-title");
  const liveDot = col.querySelector(".live-dot");
  col.querySelector(".trace-head").onclick = () => card.classList.toggle("collapsed");

  let steps = 0;
  const episode = {
    addEvent(kind, data) {
      const item = document.createElement("div");
      if (kind === "action") {
        steps += 1; count.textContent = `${steps} 步`;
        item.className = "trace-item t-action";
        const args = JSON.stringify(data.args ?? {});
        item.innerHTML = `
          <span class="t-tag">ACTION</span>
          <div class="t-content">
            <span class="tool-chip">${esc(data.tool)}</span>
            <span class="t-args" title="${esc(args)}">${esc(args)}</span>
          </div>`;
        thinkingText.textContent = `等待 ${esc(data.tool)} 的执行结果…`;
      } else if (kind === "observation") {
        item.className = "trace-item t-obs";
        item.innerHTML = `<span class="t-tag">OBSERVE</span><div class="t-content"><pre>${esc(data.text)}</pre></div>`;
        thinkingText.textContent = "Agent 正在思考…";
      } else if (kind === "thought" || kind === "reply") {
        return; // thought 已随 action 展示，独立轮不重复
      } else if (kind === "parse_error") {
        steps += 1; count.textContent = `${steps} 步`;
        item.className = "trace-item t-warn";
        item.innerHTML = `<span class="t-tag">FORMAT</span><div class="t-content">回复格式漂移，已回纠提示让模型自修复</div>`;
      } else if (kind === "llm_retry") {
        steps += 1; count.textContent = `${steps} 步`;
        item.className = "trace-item t-warn";
        item.innerHTML = `<span class="t-tag">RETRY</span><div class="t-content">LLM 调用失败，自动重试中…（${esc(data.error || "")}）</div>`;
      } else if (kind === "error") {
        steps += 1; count.textContent = `${steps} 步`;
        episode._hadError = true;
        item.className = "trace-item t-error";
        item.innerHTML = `<span class="t-tag">ERROR</span><div class="t-content">${esc(data.message)}</div>`;
      } else {
        return;
      }
      body.appendChild(item);
      card.classList.remove("collapsed");
      scrollToBottom();
    },
    finalize(final) {
      thinking.classList.add("hidden");
      liveDot.remove();
      title.textContent = `推理过程 · ${final.iterations} 轮 LLM 调用`;
      const finalCard = document.createElement("div");
      finalCard.className = "final-card";
      finalCard.innerHTML = `
        <div class="final-head">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6 9 17l-5-5"/></svg>
          最终答复
        </div>
        <div class="final-body"></div>
        <div class="final-foot">
          <span>${final.iterations} 轮</span>
          <span>${final.tool_calls.length} 次工具调用</span>
          <span>${final.tool_calls.join(" → ") || "无工具调用"}</span>
          ${final.truncated ? '<span class="badge-trunc">达到轮数上限，已强制总结</span>' : ""}
        </div>`;
      finalCard.querySelector(".final-body").appendChild(renderMarkdown(final.answer));
      col.appendChild(finalCard);
      scrollToBottom();
    },
    fail(message) {
      thinking.classList.add("hidden");
      liveDot.remove();
      if (episode._hadError) return; // 已有 ERROR 事件，不重复提示
      const item = document.createElement("div");
      item.className = "trace-item t-error";
      item.innerHTML = `<span class="t-tag">ERROR</span><div class="t-content">${esc(message)}</div>`;
      body.appendChild(item);
    },
  };
  return episode;
}

/* ---------------- 发送与轮询 ---------------- */

function setBusy(busy) {
  state.busy = busy;
  sendBtn.disabled = busy;
  $("busy-badge").classList.toggle("hidden", !busy);
}

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text || state.busy) return;
  inputEl.value = "";
  autoResize();
  addUserMessage(text);
  state.episode = createEpisode();
  setBusy(true);
  try {
    const { task_id } = await fetchJSON("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    state.taskId = task_id;
    state.since = 0;
    pollLoop();
  } catch (e) {
    state.episode.fail(e.message);
    state.episode = null;
    setBusy(false);
    toast(e.message, "error");
  }
}

async function pollLoop() {
  if (state.pollTimer) clearTimeout(state.pollTimer);
  try {
    const data = await fetchJSON(`/api/task/${state.taskId}?since=${state.since}`);
    state.since = data.next_since;
    for (const ev of data.events) {
      if (ev.kind === "final") continue; // final 由 /api/task 的结构化字段渲染
      state.episode?.addEvent(ev.kind, ev.data);
    }
    if (data.done) {
      if (data.final) {
        state.episode?.finalize(data.final);
      } else {
        state.episode?.fail("任务结束但没有产生最终答复（可能发生错误）");
      }
      state.episode = null;
      state.taskId = null;
      setBusy(false);
      refreshStatus().catch(() => {});
      return;
    }
  } catch (e) {
    state.episode?.fail(e.message);
    state.episode = null;
    setBusy(false);
    return;
  }
  state.pollTimer = setTimeout(pollLoop, 700);
}

/* ---------------- 输入框 ---------------- */

function autoResize() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 180) + "px";
}

inputEl.addEventListener("input", autoResize);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    sendMessage();
  }
});
sendBtn.onclick = sendMessage;

/* ---------------- 配置向导 ---------------- */

let presets = [];
let selectedPreset = null;

function applyPreset(preset) {
  selectedPreset = preset;
  const isCustom = preset.id === "custom";
  $("w-baseurl").value = preset.base_url || "";
  $("w-model").value = (preset.models && preset.models[0]) || "";
  const datalist = $("w-model-list");
  datalist.innerHTML = "";
  (preset.models || []).forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m;
    datalist.appendChild(opt);
  });
  // 自定义接口：显示协议选择，且地址/模型留空手填
  $("w-protocol-row").classList.toggle("hidden", !isCustom);
  $("w-protocol").classList.toggle("hidden", !isCustom);
  if (isCustom) {
    $("w-baseurl").placeholder = "https://你的中转或自建端点/v1";
    $("w-model").placeholder = "填写模型名";
  } else {
    $("w-baseurl").placeholder = "https://...";
    $("w-model").placeholder = "";
  }
}

async function showWizard() {
  $("setup-wizard").classList.remove("hidden");
  const providerSel = $("w-provider");
  if (!presets.length) {
    try {
      presets = (await fetchJSON("/api/presets")).presets;
    } catch (e) {
      toast("预设加载失败: " + e.message, "error");
      presets = [];
    }
    providerSel.innerHTML = "";
    // 按后端分组渲染 optgroup
    const groups = [...new Set(presets.map((p) => p.group || "其他"))];
    for (const g of groups) {
      const og = document.createElement("optgroup");
      og.label = g;
      presets.filter((p) => (p.group || "其他") === g).forEach((p) => {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = p.label;
        og.appendChild(opt);
      });
      providerSel.appendChild(og);
    }
    providerSel.onchange = () => {
      const p = presets.find((x) => x.id === providerSel.value);
      if (p) applyPreset(p);
    };
  }
  if (presets.length) applyPreset(presets[0]);
  $("w-apikey").focus();
}

async function submitSetup() {
  const errBox = $("w-error");
  const btn = $("w-submit");
  errBox.classList.add("hidden");
  const isCustom = selectedPreset && selectedPreset.id === "custom";
  const payload = {
    api_key: $("w-apikey").value.trim(),
    protocol: isCustom ? $("w-protocol").value : (selectedPreset ? selectedPreset.protocol : "openai"),
    base_url: $("w-baseurl").value.trim(),
    model: $("w-model").value.trim(),
  };
  if (!payload.api_key) {
    errBox.textContent = "请填写 API Key";
    errBox.classList.remove("hidden");
    return;
  }
  btn.disabled = true;
  btn.textContent = "正在保存…";
  try {
    await fetchJSON("/api/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    await refreshStatus();
    toast("配置已保存到 .env，下次启动自动使用");
  } catch (e) {
    errBox.textContent = e.message;
    errBox.classList.remove("hidden");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M20 6 9 17l-5-5"/></svg>
      保存并开始使用`;
  }
}

$("w-submit").onclick = submitSetup;

/* ---------------- 启动 ---------------- */

renderEmptyState();
refreshStatus().catch((e) => toast(`状态加载失败: ${e.message}`, "error"));
