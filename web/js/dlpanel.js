// 统一下载面板（Edge 风格）：左下角下载球可拖拽到任意位置，
// 点击弹出的下载面板自动贴随在球旁边；下载与超分任务集中处理；
// 跨页面常驻（DOM 挂在 body 上）。
import { downloadProgress, downloadJobs, removeJob, superresImage } from './api.js?v=1.16.1';
import { getSettings } from './userSettings.js?v=1.16.1';

const FAB_POS_KEY = "dlfab_pos";

const state = {
  jobs: new Map(),   // jobId -> snapshot（含 label）
  open: false,
  polling: false,
};
let fabEl = null;
let panelEl = null;
let listEl = null;

/** 应用下载球位置：有记忆用记忆，否则回 CSS 默认（左下角） */
function applyFabPos() {
  if (!fabEl) return;
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(FAB_POS_KEY) || "null");
  } catch (e) { /* 忽略损坏记录 */ }
  if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
    fabEl.style.left = `${saved.x}px`;
    fabEl.style.top = `${saved.y}px`;
    fabEl.style.bottom = "auto";
  } else {
    fabEl.style.left = "";
    fabEl.style.top = "";
    fabEl.style.bottom = "";
  }
}

/** 面板贴随下载球：优先出现在球上方，空间不足放下方，水平对齐并钳制在视口内 */
function placePanelNearFab() {
  if (!panelEl || !fabEl) return;
  const fr = fabEl.getBoundingClientRect();
  const pw = panelEl.offsetWidth || 360;
  const ph = panelEl.offsetHeight || 300;
  let x = fr.left;
  let y = fr.top - ph - 12;
  if (y < 8) y = fr.bottom + 12;
  x = Math.min(Math.max(8, x), window.innerWidth - pw - 8);
  y = Math.min(Math.max(8, y), window.innerHeight - ph - 8);
  panelEl.style.left = `${Math.round(x)}px`;
  panelEl.style.top = `${Math.round(y)}px`;
  panelEl.style.bottom = "auto";
}

/** 下载球拖拽：按住即拖（移动 >4px 判定为拖拽），松开保存位置；
 *  轻点视为开关面板；拖动过程中面板实时跟随。 */
function setupFabDrag() {
  fabEl.addEventListener("pointerdown", e => {
    if (e.button !== 0) return;
    const rect = fabEl.getBoundingClientRect();
    const dx = e.clientX - rect.left;
    const dy = e.clientY - rect.top;
    let moved = false;
    const onMove = ev => {
      const nx = ev.clientX - dx;
      const ny = ev.clientY - dy;
      if (!moved && (Math.abs(nx - rect.left) > 4 || Math.abs(ny - rect.top) > 4)) {
        moved = true;
      }
      if (!moved) return;
      const x = Math.round(Math.min(Math.max(8, nx), window.innerWidth - 62));
      const y = Math.round(Math.min(Math.max(8, ny), window.innerHeight - 62));
      fabEl.style.left = `${x}px`;
      fabEl.style.top = `${y}px`;
      fabEl.style.bottom = "auto";
      if (state.open) placePanelNearFab();
    };
    const onUp = () => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      if (moved) {
        try {
          const r = fabEl.getBoundingClientRect();
          localStorage.setItem(FAB_POS_KEY,
            JSON.stringify({ x: Math.round(r.left), y: Math.round(r.top) }));
        } catch (err) { /* 保存失败仅影响记忆 */ }
        if (state.open) placePanelNearFab();
      } else {
        setOpen(!state.open);
      }
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    e.preventDefault();
  });
}

/** 复位下载球到左下角默认位置（设置页调用） */
export function resetFabPos() {
  try {
    localStorage.removeItem(FAB_POS_KEY);
  } catch (e) { /* 忽略 */ }
  applyFabPos();
  placePanelNearFab();
}

function ensureDom() {
  if (fabEl) return;
  fabEl = document.createElement("button");
  fabEl.className = "dlpanel-fab";
  fabEl.title = "下载管理 · 按住可拖动，轻点开合面板";
  // 纯白 SVG 下载箭头（emoji 自带彩色底块，与主题色球体冲突）
  fabEl.innerHTML = `<span class="dlpanel-fab-ico">
      <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
        <path d="M12 3v11m0 0l-5-5m5 5l5-5M5 20h14" stroke="#fff" stroke-width="2.6"
              stroke-linecap="round" stroke-linejoin="round" fill="none"/>
      </svg>
    </span>
    <span class="dlpanel-badge" style="display:none">0</span>`;
  setupFabDrag();

  panelEl = document.createElement("div");
  panelEl.className = "dlpanel";
  panelEl.style.display = "none";
  panelEl.innerHTML = `
    <div class="dlpanel-head">
      <span class="dlpanel-title">⬇️ 下载管理</span>
      <span class="dlpanel-hint" id="dlpanel-hint"></span>
      <button class="dlpanel-act" id="dlpanel-clear" title="清除已结束的任务">🧹</button>
      <button class="dlpanel-act" id="dlpanel-close" title="收起">✕</button>
    </div>
    <div class="dlpanel-list" id="dlpanel-list"></div>`;
  document.body.append(fabEl, panelEl);
  listEl = panelEl.querySelector("#dlpanel-list");
  panelEl.querySelector("#dlpanel-close").addEventListener("click", () => setOpen(false));
  panelEl.querySelector("#dlpanel-clear").addEventListener("click", () => {
    for (const [id, j] of [...state.jobs]) {
      if (j.state !== "running") {
        state.jobs.delete(id);
        removeJob(id).catch(() => {}); // 同步删除服务器记录，防止刷新面板后复活
      }
    }
    renderPanel();
  });
  applyFabPos();
}

function setOpen(v) {
  state.open = v;
  if (panelEl) {
    // 必须写 flex 而非 block：inline display 优先级高于类选择器，
    // 写 block 会顶掉 CSS 的 display:flex，列表 flex:1/min-height:0 失效 → 无法滚动
    panelEl.style.display = v ? "flex" : "none";
    if (v) placePanelNearFab();
  }
  if (v) renderPanel();
}

function escAttr(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

function fmtMB(n) { return ((n || 0) / 1048576).toFixed(1); }

function itemHtml(j) {
  const isSR = j.type === "superres";
  const dir = j.kind === "after_training" ? "突破后" : "突破前";
  const name = j.filename || j.label || `卡面 #${j.card}`;
  let status = "";
  let fill = 0;
  let indet = false;
  if (j.state === "running") {
    if (isSR && j.phase === "download") {
      // 超分级联：原图缺失 → 先竞速下载原图（复用下载进度条）
      const pct = j.total ? Math.min(100, Math.round(j.downloaded / j.total * 100)) : 0;
      fill = j.total ? pct : 8;
      status = `超分前置：原图未缓存，竞速下载 ${pct}% · ${fmtMB(j.downloaded)} / ${fmtMB(j.total)}MB · ${j.source || ""}`;
    } else if (isSR && j.phase === "ai") {
      // AI 引擎推理：引擎 stdout 实时百分比（无输出时退化为 indeterminate）
      const pct = Math.max(0, Math.min(100, j.srProgress || 0));
      fill = pct;
      indet = !pct;
      status = `🧪 AI 超分推理中…（Real-ESRGAN · 独立显卡）${pct ? ` ${pct}%` : ""}`;
    } else if (isSR) {
      indet = true;
      status = "✨ 超分强化中…（LANCZOS + 锐化，约 10~40 秒）";
    } else {
      const pct = j.total ? Math.min(100, Math.round(j.downloaded / j.total * 100)) : 0;
      fill = j.total ? pct : 8;
      status = j.total
        ? `竞速下载 ${pct}% · ${fmtMB(j.downloaded)} / ${fmtMB(j.total)}MB · ${j.source || ""}`
        : `正在连接源站…（已收 ${fmtMB(j.downloaded)}MB）`;
    }
  } else if (j.state === "done") {
    // 超分条目标注实际引擎；AI 失败回退经典管线时明确告知
    const engTag = !isSR ? "" : j.engine === "ai" ? " · AI"
      : j.engineFallback ? " · AI失败已回退" : "";
    status = (j.already ? "已存在于「下载」文件夹" : "✓ 已保存到「下载」文件夹") + engTag;
  } else if (j.state === "error") {
    status = `✕ 失败：${j.error || "未知原因"}`;
  }
  // 下载完成的条目提供面板内超分入口（只显示「✨ 超分」，档位由设置页决定）；
  // stopPropagation 防止点击按钮时冒泡触发条目的「查看大图」
  let srBtn = "";
  if (!isSR && j.state === "done" && j.card) {
    srBtn = `<button class="dlitem-btn" onclick="window.__dlSR('${escAttr(j.jobId)}');event.stopPropagation()" title="按设置页档位执行">✨ 超分</button>`;
  }
  const viewUrl = j.state === "done"
    ? (j.url || (isSR ? "" : `/api/originals/${j.card}_${j.kind}.png`))
    : "";
  // 已结束条目提供「单独删除」；进行中任务不渲染按钮（后台线程仍在写状态，删了会名存实亡）。
  // stopPropagation 防止点击删除时冒泡触发条目的「查看大图」（v1.8.3 超分按钮同款处理）
  const delBtn = j.state !== "running"
    ? `<button class="dlitem-del" onclick="window.__dlDel('${escAttr(j.jobId)}');event.stopPropagation()" title="删除该条记录">✕</button>`
    : "";
  return `
  <div class="dlitem ${j.state}" ${j.state === "done"
    ? `title="点击查看大图" data-open="${viewUrl}"` : ""}>
    <div class="dlitem-ico">${isSR ? "✨" : j.state === "done" ? "🖼️" : j.state === "error" ? "⚠️" : "⏳"}</div>
    <div class="dlitem-body">
      <div class="dlitem-name" title="${escAttr(name)}">${escAttr(name)}</div>
      ${j.state === "running" ? `
      <div class="dlitem-bar"><div class="dlitem-fill ${indet ? "indet" : ""}" style="width:${indet ? 40 : fill}%"></div></div>` : ""}
      <div class="dlitem-status">${escAttr(status)}${j.state !== "running" ? ` · ${dir}` : ""}${srBtn}</div>
    </div>
    ${delBtn}
  </div>`;
}

function renderPanel() {
  if (!panelEl) return;
  const jobs = [...state.jobs.values()].sort((a, b) => (b.jobId || "").localeCompare(a.jobId || ""));
  listEl.innerHTML = jobs.length
    ? jobs.map(itemHtml).join("")
    : '<div class="dlpanel-empty">暂无下载记录</div>';
  const running = jobs.filter(j => j.state === "running").length;
  const badge = fabEl.querySelector(".dlpanel-badge");
  badge.textContent = running;
  badge.style.display = running ? "grid" : "none";
  const hint = panelEl.querySelector("#dlpanel-hint");
  hint.textContent = running ? `${running} 个进行中` : "";
  listEl.querySelectorAll(".dlitem.done").forEach(el => {
    el.onclick = () => window.open(el.dataset.open, "_blank", "noopener");
  });
}

async function tick() {
  const running = [...state.jobs.entries()].filter(([, j]) => j.state === "running");
  for (const [id, j] of running) {
    try {
      const s = await downloadProgress(id);
      state.jobs.set(id, { ...j, ...s, jobId: id });
      if (s.state === "done") {
        window.dispatchEvent(new CustomEvent("dl:done", {
          detail: { cardId: s.card, kind: s.kind, filename: s.filename },
        }));
      } else if (s.state === "error") {
        window.dispatchEvent(new CustomEvent("dl:error", {
          detail: { cardId: s.card, kind: s.kind, error: s.error },
        }));
      }
    } catch (e) { /* 单个任务查询失败不影响其他任务 */ }
  }
  renderPanel();
  if (![...state.jobs.values()].some(j => j.state === "running") && state.polling) {
    state.polling = false;
    clearInterval(state._timer);
    state._timer = null;
  }
}

function startPolling() {
  if (state.polling) return;
  state.polling = true;
  state._timer = setInterval(tick, 700);
  tick();
}

/** 新任务入列（由详情页下载/超分按钮调用）：
 *  只在下载球角标显示队列数，不自动弹出面板。 */
export function registerJob(jobId, label, extra = {}) {
  ensureDom();
  state.jobs.set(jobId, {
    jobId, label, state: "running", downloaded: 0, total: 0,
    source: "", filename: "", error: "", already: false, card: null, kind: null,
    type: "download", ...extra,
  });
  renderPanel();
  startPolling();
}

/** 单独删除一条任务记录（仅已结束条目；运行中条目不渲染删除按钮）：
 *  服务器移除成功后同步删本地；「任务不存在」=服务器重启过（内存态清空），同样删本地。 */
window.__dlDel = jobId => {
  removeJob(jobId).then(r => {
    if ((r && r.ok) || (r && r.error && r.error.indexOf("任务不存在") !== -1)) {
      state.jobs.delete(jobId);
    }
    renderPanel();
  }).catch(() => { /* 网络失败：保留条目可重试 */ });
};

/** 面板内直接发起超分：读取条目卡牌信息，按设置档位创建超分任务
 *  （原图缓存缺失时服务器会自动级联先下载原图）。 */
window.__dlSR = jobId => {
  const j = state.jobs.get(jobId);
  if (!j || !j.card) return;
  const tier = getSettings().srTarget || "4k";
  const engine = getSettings().srEngine || "ai";
  const mod = j.mod || "pjsk";
  const tierLabel = tier === "2k" ? "2K" : "4K";
  superresImage(j.card, j.kind, tier, engine, mod).then(r => {
    if (r.ok && r.jobId) {
      registerJob(r.jobId, `${j.label} · ${engine === "ai" ? "AI" : ""}超分${tierLabel}`,
        { type: "superres", card: j.card, kind: j.kind, tier, engine, mod });
    } else {
      j.state = "error";
      j.error = r.error || "超分任务创建失败";
      renderPanel();
    }
  }).catch(e => {
    j.state = "error";
    j.error = e.message;
    renderPanel();
  });
};

/** 页面加载时：恢复下载球位置 + 拉取服务器上的历史任务 */
export async function initDlPanel() {
  ensureDom();
  try {
    const { jobs } = await downloadJobs();
    for (const j of jobs) {
      if (!state.jobs.has(j.jobId)) state.jobs.set(j.jobId, j);
    }
  } catch (e) { /* 静默：面板照常可用 */ }
  renderPanel();
  if ([...state.jobs.values()].some(j => j.state === "running")) startPolling();
}
