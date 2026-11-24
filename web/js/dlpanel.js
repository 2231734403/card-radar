// 统一下载与超分管理面板（左下角可拖动 FAB）
// 强化项：
//  - 准确展示全部四模块形态标签（kindLabel，修复原版全显示「突破前」Bug）
//  - 筛选标签页（全部 / 进行中 / 已完成 / 失败）
//  - 失败与服务重启中断任务支持一键「↻ 重试」
//  - 严守 T9：面板展开使用 display:flex + 列表 flex:1; min-height:0 保证平滑滚动
import {
  downloadProgress,
  downloadJobs,
  removeJob,
  clearFinishedJobs,
  superresImage,
  retryJob,
} from './api.js?v=2.0.0';
import { getSettings } from './userSettings.js?v=2.0.0';
import { toast } from './ui.js?v=2.0.0';

const FAB_POS_KEY = 'dlfab_pos';

const state = {
  jobs: new Map(),
  open: false,
  polling: false,
  filter: 'all', // all | running | done | error
  _timer: null,
};
let fabEl = null;
let panelEl = null;
let listEl = null;

function applyFabPos() {
  if (!fabEl) return;
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(FAB_POS_KEY) || 'null');
  } catch { /* 忽略损坏记录 */ }
  if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
    const x = Math.min(Math.max(8, saved.x), Math.max(8, window.innerWidth - 62));
    const y = Math.min(Math.max(8, saved.y), Math.max(8, window.innerHeight - 62));
    fabEl.style.left = `${x}px`;
    fabEl.style.top = `${y}px`;
    fabEl.style.bottom = 'auto';
  } else {
    fabEl.style.left = '';
    fabEl.style.top = '';
    fabEl.style.bottom = '';
  }
}

function placePanelNearFab() {
  if (!panelEl || !fabEl) return;
  const fr = fabEl.getBoundingClientRect();
  const pw = panelEl.offsetWidth || 380;
  const ph = panelEl.offsetHeight || 360;
  let x = fr.left;
  let y = fr.top - ph - 12;
  if (y < 8) y = fr.bottom + 12;
  x = Math.min(Math.max(8, x), Math.max(8, window.innerWidth - pw - 8));
  y = Math.min(Math.max(8, y), Math.max(8, window.innerHeight - ph - 8));
  panelEl.style.left = `${Math.round(x)}px`;
  panelEl.style.top = `${Math.round(y)}px`;
  panelEl.style.bottom = 'auto';
}

function setupFabDrag() {
  fabEl.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    const rect = fabEl.getBoundingClientRect();
    const dx = e.clientX - rect.left;
    const dy = e.clientY - rect.top;
    let moved = false;
    const onMove = ev => {
      const nx = ev.clientX - dx;
      const ny = ev.clientY - dy;
      if (!moved && (Math.abs(nx - rect.left) > 4 || Math.abs(ny - rect.top) > 4)) moved = true;
      if (!moved) return;
      const x = Math.round(Math.min(Math.max(8, nx), window.innerWidth - 62));
      const y = Math.round(Math.min(Math.max(8, ny), window.innerHeight - 62));
      fabEl.style.left = `${x}px`;
      fabEl.style.top = `${y}px`;
      fabEl.style.bottom = 'auto';
      if (state.open) placePanelNearFab();
    };
    const onUp = () => {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
      if (moved) {
        try {
          const r = fabEl.getBoundingClientRect();
          localStorage.setItem(FAB_POS_KEY, JSON.stringify({ x: Math.round(r.left), y: Math.round(r.top) }));
        } catch { /* 忽略 */ }
        if (state.open) placePanelNearFab();
      } else {
        setOpen(!state.open);
      }
    };
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
    e.preventDefault();
  });
}

export function resetFabPos() {
  try { localStorage.removeItem(FAB_POS_KEY); } catch { /* 忽略 */ }
  applyFabPos();
  placePanelNearFab();
}

function ensureDom() {
  if (fabEl) return;
  fabEl = document.createElement('button');
  fabEl.className = 'dlpanel-fab';
  fabEl.title = '下载管理 · 按住可拖动，轻点开合面板';
  fabEl.innerHTML = `<span class="dlpanel-fab-ico">
      <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
        <path d="M12 3v11m0 0l-5-5m5 5l5-5M5 20h14" stroke="#fff" stroke-width="2.6"
              stroke-linecap="round" stroke-linejoin="round" fill="none"/>
      </svg>
    </span>
    <span class="dlpanel-badge" style="display:none">0</span>`;
  setupFabDrag();

  panelEl = document.createElement('div');
  panelEl.className = 'dlpanel';
  panelEl.style.display = 'none';
  panelEl.innerHTML = `
    <div class="dlpanel-head">
      <span class="dlpanel-title">⬇️ 下载与超分队列</span>
      <span class="dlpanel-hint" id="dlpanel-hint"></span>
      <button class="dlpanel-act" id="dlpanel-clear" title="清除已结束的任务">🧹</button>
      <button class="dlpanel-act" id="dlpanel-close" title="收起">✕</button>
    </div>
    <div class="dlpanel-tabs" id="dlpanel-tabs">
      <button class="dltab on" data-f="all">全部</button>
      <button class="dltab" data-f="running">进行中</button>
      <button class="dltab" data-f="done">已完成</button>
      <button class="dltab" data-f="error">失败</button>
    </div>
    <div class="dlpanel-list" id="dlpanel-list"></div>`;
  document.body.append(fabEl, panelEl);
  listEl = panelEl.querySelector('#dlpanel-list');

  panelEl.querySelector('#dlpanel-close').addEventListener('click', () => setOpen(false));
  panelEl.querySelector('#dlpanel-clear').addEventListener('click', async () => {
    for (const [id, j] of [...state.jobs]) {
      if (j.state !== 'running') state.jobs.delete(id);
    }
    clearFinishedJobs().catch(() => {});
    renderPanel();
  });
  panelEl.querySelectorAll('.dltab').forEach(btn => {
    btn.addEventListener('click', () => {
      state.filter = btn.dataset.f;
      panelEl.querySelectorAll('.dltab').forEach(x => x.classList.toggle('on', x === btn));
      renderPanel();
    });
  });
  applyFabPos();
}

export function setOpen(v) {
  ensureDom();
  state.open = v;
  panelEl.style.display = v ? 'flex' : 'none';
  if (v) {
    placePanelNearFab();
    renderPanel();
  }
}

function escAttr(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

function fmtMB(n) { return ((n || 0) / 1048576).toFixed(1); }

function kindText(j) {
  if (j.kindLabel) return j.kindLabel;
  if (j.kind === 'after_training') return '突破后';
  if (j.kind === 'fes') return '特训后';
  if (j.kind === 'support') return '支援卡';
  if (j.kind === 'card') return '角色卡';
  return '突破前';
}

function itemHtml(j) {
  const isSR = j.type === 'superres';
  const dir = kindText(j);
  const name = j.filename || j.label || `卡面 #${j.card}`;
  let status = '';
  let fill = 0;
  let indet = false;

  if (j.state === 'running') {
    if (isSR && j.phase === 'download') {
      const pct = j.total ? Math.min(100, Math.round((j.downloaded / j.total) * 100)) : 0;
      fill = j.total ? pct : 8;
      status = `前置下载原图 ${pct}% · ${fmtMB(j.downloaded)} / ${fmtMB(j.total)}MB · ${j.source || ''}`;
    } else if (isSR && j.phase === 'ai') {
      const pct = Math.max(0, Math.min(100, j.srProgress || 0));
      fill = pct;
      indet = !pct;
      status = `🧪 AI 超分推理中（GPU 串行保护）${pct ? ` ${pct}%` : ''}`;
    } else if (isSR) {
      indet = true;
      status = '✨ Pillow 渐进抗锯齿超分中…';
    } else {
      const pct = j.total ? Math.min(100, Math.round((j.downloaded / j.total) * 100)) : 0;
      fill = j.total ? pct : 8;
      status = j.total
        ? `下载中 ${pct}% · ${fmtMB(j.downloaded)} / ${fmtMB(j.total)}MB · ${j.source || ''}`
        : `正在连接源站…（已收 ${fmtMB(j.downloaded)}MB）`;
    }
  } else if (j.state === 'done') {
    const engTag = !isSR ? '' : j.engine === 'ai' ? ' · AI' : j.engineFallback ? ' · AI失败回退' : ' · Pillow';
    status = (j.already ? '已存在于「下载」目录' : '✓ 已保存到「下载」目录') + engTag;
  } else if (j.state === 'error') {
    status = `✕ ${j.error || '未知失败'}`;
  }

  let actBtn = '';
  if (!isSR && j.state === 'done' && j.card) {
    actBtn = `<button class="dlitem-btn" onclick="window.__dlSR('${escAttr(j.jobId)}');event.stopPropagation()" title="按设置页档位发起超分">✨ 超分</button>`;
  } else if (j.state === 'error') {
    actBtn = `<button class="dlitem-btn retry" onclick="window.__dlRetry('${escAttr(j.jobId)}');event.stopPropagation()" title="重新执行该任务">↻ 重试</button>`;
  }

  const viewUrl = j.state === 'done' ? (j.url || '') : '';
  const delBtn = j.state !== 'running'
    ? `<button class="dlitem-del" onclick="window.__dlDel('${escAttr(j.jobId)}');event.stopPropagation()" title="删除记录">✕</button>`
    : '';

  return `
  <div class="dlitem ${j.state}" ${j.state === 'done' && viewUrl ? `title="点击查看大图" data-open="${escAttr(viewUrl)}"` : ''}>
    <div class="dlitem-ico">${isSR ? '✨' : j.state === 'done' ? '🖼️' : j.state === 'error' ? '⚠️' : '⏳'}</div>
    <div class="dlitem-body">
      <div class="dlitem-name" title="${escAttr(name)}">${escAttr(name)}</div>
      ${j.state === 'running' ? `
      <div class="dlitem-bar"><div class="dlitem-fill ${indet ? 'indet' : ''}" style="width:${indet ? 40 : fill}%"></div></div>` : ''}
      <div class="dlitem-status">${escAttr(status)}${j.state !== 'running' ? ` · ${escAttr(dir)}` : ''}${actBtn}</div>
    </div>
    ${delBtn}
  </div>`;
}

function renderPanel() {
  if (!panelEl) return;
  const allJobs = [...state.jobs.values()].sort((a, b) => (b.jobId || '').localeCompare(a.jobId || ''));
  const filtered = state.filter === 'all' ? allJobs : allJobs.filter(j => j.state === state.filter);
  listEl.innerHTML = filtered.length
    ? filtered.map(itemHtml).join('')
    : '<div class="dlpanel-empty">暂无匹配的下载记录</div>';

  const running = allJobs.filter(j => j.state === 'running').length;
  const badge = fabEl.querySelector('.dlpanel-badge');
  badge.textContent = running;
  badge.style.display = running ? 'grid' : 'none';
  const hint = panelEl.querySelector('#dlpanel-hint');
  hint.textContent = running ? `${running} 个进行中` : (allJobs.length ? `共 ${allJobs.length} 条` : '');

  listEl.querySelectorAll('.dlitem.done[data-open]').forEach(el => {
    el.onclick = () => {
      if (el.dataset.open) window.open(el.dataset.open, '_blank', 'noopener');
    };
  });
}

async function tick() {
  const running = [...state.jobs.entries()].filter(([, j]) => j.state === 'running');
  for (const [id, j] of running) {
    try {
      const s = await downloadProgress(id);
      state.jobs.set(id, { ...j, ...s, jobId: id });
      if (s.state === 'done') {
        window.dispatchEvent(new CustomEvent('dl:done', {
          detail: { mod: s.mod, cardId: s.card, kind: s.kind, type: s.type, tier: s.tier, filename: s.filename },
        }));
      } else if (s.state === 'error') {
        window.dispatchEvent(new CustomEvent('dl:error', {
          detail: { mod: s.mod, cardId: s.card, kind: s.kind, error: s.error },
        }));
      }
    } catch { /* 单任务查询失败忽略 */ }
  }
  renderPanel();
  if (![...state.jobs.values()].some(j => j.state === 'running') && state.polling) {
    state.polling = false;
    clearInterval(state._timer);
    state._timer = null;
  }
}

function startPolling() {
  if (state.polling) return;
  state.polling = true;
  state._timer = setInterval(tick, 750);
  tick();
}

export function registerJob(jobId, label, extra = {}) {
  ensureDom();
  state.jobs.set(jobId, {
    jobId,
    label,
    state: 'running',
    downloaded: 0,
    total: 0,
    source: '',
    filename: '',
    error: '',
    already: false,
    card: null,
    kind: null,
    type: 'download',
    ...extra,
  });
  renderPanel();
  startPolling();
}

export async function refreshJobsFromServer() {
  ensureDom();
  try {
    const { jobs } = await downloadJobs();
    for (const j of jobs || []) {
      state.jobs.set(j.jobId, j);
    }
    renderPanel();
    if ([...state.jobs.values()].some(j => j.state === 'running')) startPolling();
  } catch { /* 静默 */ }
}

window.__dlDel = jobId => {
  removeJob(jobId).then(r => {
    if ((r && r.ok) || (r && r.error && r.error.includes('不存在'))) {
      state.jobs.delete(jobId);
    }
    renderPanel();
  }).catch(() => {});
};

window.__dlRetry = async jobId => {
  try {
    const r = await retryJob(jobId);
    if (r && r.ok && r.jobId) {
      await refreshJobsFromServer();
      toast('已重新加入队列 ↻');
    }
  } catch (e) {
    toast(`重试失败：${e.message}`, true);
  }
};

window.__dlSR = jobId => {
  const j = state.jobs.get(jobId);
  if (!j || !j.card) return;
  const tier = getSettings().srTarget || '4k';
  const engine = getSettings().srEngine || 'ai';
  const mod = j.mod || 'pjsk';
  const tierLabel = tier === '2k' ? '2K' : '4K';
  superresImage(j.card, j.kind, tier, engine, mod).then(r => {
    if (r.ok && r.jobId) {
      registerJob(r.jobId, `${j.label} · ${engine === 'ai' ? 'AI' : ''}超分${tierLabel}`, {
        type: 'superres',
        card: j.card,
        kind: j.kind,
        kindLabel: j.kindLabel,
        tier,
        engine,
        mod,
      });
      toast('已加入超分队列 ✨');
    } else {
      toast(r.error || '超分任务创建失败', true);
    }
  }).catch(e => toast(`超分失败：${e.message}`, true));
};

export async function initDlPanel() {
  ensureDom();
  await refreshJobsFromServer();
}
