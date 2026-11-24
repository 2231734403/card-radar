// 设置页 v2：外观模式（浅色/深色/跟随系统）、超分配置、全四模块缓存精细清理、源站探活、收藏档案备份导入导出
import { MODULES } from '../modules/registry.js?v=2.0.0';
import { esc, toast, openShortcutsModal } from '../ui.js?v=2.0.0';
import {
  getSettings,
  setSetting,
  getFavorites,
  getGroups,
  replaceUserData,
} from '../userSettings.js?v=2.0.0';
import { resetFabPos } from '../dlpanel.js?v=2.0.0';
import { cacheStats, cacheClear, fetchHealth, probeSources } from '../api.js?v=2.0.0';

const MODE_OPTIONS = [
  { v: 'light', title: '☀️ 浅色模式', desc: '明快通透 · Apple 扁平风格', tag: '默认' },
  { v: 'dark', title: '🌙 深色模式', desc: '低眩光护眼 · 夜间刷卡首选', tag: '护眼' },
  { v: 'auto', title: '🖥️ 跟随系统', desc: '自动同步 Windows 深浅色设置', tag: '自适应' },
];

const SR_OPTIONS = [
  { v: '4k', title: '4K 超清', desc: '长边 3840 · 壁纸级细节', tag: '壁纸首选 · 推荐' },
  { v: '2k', title: '2K 高清', desc: '长边 2560 · 体积更轻、速度更快', tag: '轻量' },
];

const SR_ENGINE_OPTIONS = [
  { v: 'ai', title: 'AI 超分（GPU 串行保护）', desc: 'Real-ESRGAN Vulkan 动漫模型 · 批量任务自动串行防爆显存', tag: '首选 · 推荐' },
  { v: 'pillow', title: '经典管线', desc: 'Pillow 渐进抗锯齿放大 · 零显卡要求 · 稳定回退', tag: '备选' },
];

export function renderSettings(app) {
  const s = getSettings();
  app.innerHTML = `
  <div class="detail-head">
    <div>
      <div class="page-title">⚙️ <span class="hl">设置与工具</span></div>
      <div class="page-desc">外观、超分引擎、全模块缓存治理、数据源状态检测与收藏档案备份</div>
    </div>
    <button class="btn small" id="s-shortcuts">⌨️ 快捷键一览</button>
  </div>
  <div class="section-gap"></div>
  <div class="info-grid">
    <div class="card-panel">
      <h3 style="margin-bottom:8px">🎨 外观模式（与四游戏主题色正交组合）</h3>
      <p class="panel-sub">切换游戏主题色与深浅外观均支持平滑过渡，按快捷键 <kbd>D</kbd> 可随时切换。</p>
      <div class="option-cards" id="mode-opts">
        ${MODE_OPTIONS.map(o => `
          <button class="opt-card ${s.colorMode === o.v ? 'on' : ''}" data-v="${o.v}">
            <b>${esc(o.title)}</b><span>${esc(o.desc)}</span><em>${esc(o.tag)}</em>
          </button>`).join('')}
      </div>
    </div>

    <div class="card-panel">
      <h3 style="margin-bottom:8px">✨ 超分辨率档位</h3>
      <p class="panel-sub">下载面板、详情页与批量超分统一遵循此处档位设定；2K / 4K 可共存并支持画质滑块对比。</p>
      <div class="option-cards" id="sr-opts">
        ${SR_OPTIONS.map(o => `
          <button class="opt-card ${s.srTarget === o.v ? 'on' : ''}" data-v="${o.v}">
            <b>${esc(o.title)}</b><span>${esc(o.desc)}</span><em>${esc(o.tag)}</em>
          </button>`).join('')}
      </div>
    </div>

    <div class="card-panel">
      <h3 style="margin-bottom:8px">🚀 超分引擎</h3>
      <p class="panel-sub">AI 引擎由独立 GPU 信号量保护，批量任务自动排队不爆显存；缺失或失败自动回退 Pillow。<span id="ai-engine-state"></span></p>
      <div class="option-cards" id="sr-engine-opts">
        ${SR_ENGINE_OPTIONS.map(o => `
          <button class="opt-card ${s.srEngine === o.v ? 'on' : ''}" data-v="${o.v}">
            <b>${esc(o.title)}</b><span>${esc(o.desc)}</span><em>${esc(o.tag)}</em>
          </button>`).join('')}
      </div>
    </div>

    <div class="card-panel">
      <h3 style="margin-bottom:8px">🧹 全模块缓存管理</h3>
      <p class="panel-sub">统计并按模块清理 <code>data/originals*</code> 内部缓存（系统「下载」文件夹中的成品绝不受影响）。</p>
      <div id="cache-stats-box" style="font-size:13px;color:var(--text-3)">统计中…</div>
      <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn small" id="cache-clear-all">🗑️ 清空全部模块缓存</button>
      </div>
    </div>

    <div class="card-panel">
      <h3 style="margin-bottom:8px">🌐 四数据源连通性探测</h3>
      <p class="panel-sub">实时检测各公网数据源通过直连 / 本机代理（7890 / 7897）的可达性与延迟。</p>
      <div id="probe-box" class="probe-list"><div class="muted-sm">点击下方按钮立即探测…</div></div>
      <button class="btn small" id="btn-probe" style="margin-top:12px">🔍 立即探测源站</button>
    </div>

    <div class="card-panel">
      <h3 style="margin-bottom:8px">💾 收藏档案与下载面板</h3>
      <p class="panel-sub">收藏夹已自动持久化到 <code>data/user_profile.json</code>，也可手动导出/导入 JSON 备份。</p>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
        <button class="btn small" id="btn-export-profile">📤 导出收藏备份 JSON</button>
        <button class="btn small" id="btn-import-profile">📥 导入收藏备份</button>
        <input type="file" id="import-profile-input" accept="application/json" style="display:none">
        <button class="btn small" id="reset-fab-pos">⌖ 复位下载球位置</button>
      </div>
    </div>
  </div>`;

  app.querySelector('#s-shortcuts').onclick = openShortcutsModal;

  app.querySelectorAll('#mode-opts .opt-card').forEach(el => {
    el.onclick = () => {
      setSetting('colorMode', el.dataset.v);
      app.querySelectorAll('#mode-opts .opt-card').forEach(x => x.classList.toggle('on', x === el));
    };
  });
  app.querySelectorAll('#sr-opts .opt-card').forEach(el => {
    el.onclick = () => {
      setSetting('srTarget', el.dataset.v);
      app.querySelectorAll('#sr-opts .opt-card').forEach(x => x.classList.toggle('on', x === el));
    };
  });
  app.querySelectorAll('#sr-engine-opts .opt-card').forEach(el => {
    el.onclick = () => {
      setSetting('srEngine', el.dataset.v);
      app.querySelectorAll('#sr-engine-opts .opt-card').forEach(x => x.classList.toggle('on', x === el));
    };
  });

  fetchHealth().then(st => {
    const el = app.querySelector('#ai-engine-state');
    if (!el) return;
    el.innerHTML = st.aiEngine
      ? ' <span style="color:var(--primary-strong);font-weight:700">✓ 引擎就绪（Real-ESRGAN Vulkan）</span>'
      : ' <span style="color:var(--danger)">⚠ 未检测到 ai_engine/，当前自动回退 Pillow</span>';
  }).catch(() => {});

  // 全模块缓存统计与按模块清理
  const cacheBox = app.querySelector('#cache-stats-box');
  const clearAllBtn = app.querySelector('#cache-clear-all');

  async function refreshCache() {
    try {
      const st = await cacheStats();
      clearAllBtn.disabled = !st.count;
      const rows = MODULES.map(m => {
        const mc = st.modules?.[m.apiMod] || { count: 0, mb: 0 };
        return `
        <div class="cache-row">
          <span>${m.icon} ${esc(m.name)}</span>
          <span class="muted-sm">${mc.count} 个文件 · ${mc.mb} MB</span>
          <button class="btn tiny" data-clear-mod="${esc(m.apiMod)}" ${mc.count ? '' : 'disabled'}>清理</button>
        </div>`;
      }).join('');
      cacheBox.innerHTML = `
        <div style="margin-bottom:8px">
          <span class="badge chip">📦 总计 ${st.count} 个文件</span>
          <span class="badge chip" style="margin-left:6px">💾 ${st.mb} MB</span>
        </div>
        <div class="cache-mod-list">${rows}</div>`;
      cacheBox.querySelectorAll('[data-clear-mod]').forEach(btn => {
        btn.onclick = async () => {
          btn.disabled = true;
          try {
            const r = await cacheClear(btn.dataset.clearMod);
            toast(`已清理 ${r.removed} 个缓存文件，释放 ${r.freedMB} MB`);
            refreshCache();
          } catch (e) { toast(`清理失败：${e.message}`, true); }
        };
      });
    } catch (e) {
      cacheBox.textContent = `统计失败：${e.message}`;
    }
  }
  refreshCache();

  clearAllBtn.onclick = async () => {
    clearAllBtn.disabled = true;
    try {
      const r = await cacheClear('all');
      toast(`已清空全部缓存：${r.removed} 个文件，释放 ${r.freedMB} MB`);
      refreshCache();
    } catch (e) {
      toast(`清空失败：${e.message}`, true);
    } finally {
      clearAllBtn.disabled = false;
    }
  };

  // 数据源探活
  const probeBox = app.querySelector('#probe-box');
  const probeBtn = app.querySelector('#btn-probe');
  async function runProbe(force = false) {
    probeBtn.disabled = true;
    probeBox.innerHTML = '<div class="muted-sm">正在并发探测四大数据源…</div>';
    try {
      const res = await probeSources(force);
      probeBox.innerHTML = MODULES.map(m => {
        const info = res.sources?.[m.apiMod] || {};
        return `
        <div class="probe-row">
          <span>${m.icon} ${esc(m.shortName)}</span>
          <span class="source-pill ${info.ok ? 'ok' : 'offline'}">
            ${info.ok ? `● 在线 (${esc(info.channel)} · ${info.latencyMs}ms)` : `● 不可达 (${esc(info.error || '超时')})`}
          </span>
        </div>`;
      }).join('');
    } catch (e) {
      probeBox.innerHTML = `<div style="color:var(--danger);font-size:13px">探测失败：${esc(e.message)}</div>`;
    } finally {
      probeBtn.disabled = false;
    }
  }
  probeBtn.onclick = () => runProbe(true);
  runProbe(false);

  // 导出/导入用户档案
  app.querySelector('#btn-export-profile').onclick = () => {
    const payload = {
      exportedAt: new Date().toISOString(),
      favorites: getFavorites(),
      groups: getGroups(),
      settings: getSettings(),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `card-radar-backup-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    toast('收藏档案备份已导出');
  };

  const fileInput = app.querySelector('#import-profile-input');
  app.querySelector('#btn-import-profile').onclick = () => fileInput.click();
  fileInput.onchange = async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      replaceUserData(parsed);
      toast('收藏与分组档案导入成功 ✓');
    } catch (e) {
      toast(`导入失败：${e.message}`, true);
    }
    fileInput.value = '';
  };

  app.querySelector('#reset-fab-pos').onclick = () => {
    resetFabPos();
    toast('下载球已复位到左下角 ⌖');
  };
}
