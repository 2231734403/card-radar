// 跨四游戏统一收藏夹与自定义分组页（#/favorites）
// 支持按分组/按游戏筛选、创建/删除分组、一键批量下载/超分与 ZIP 收藏包导出。
import { MODULES, getModule } from '../modules/registry.js?v=2.0.0';
import { ensureModuleIndex, getModuleCard } from '../store.js?v=2.0.0';
import {
  getFavorites,
  getGroups,
  addGroup,
  removeGroup,
  getSettings,
} from '../userSettings.js?v=2.0.0';
import { esc, cardCellHtml, toast, confirmCopyrightIfNeeded } from '../ui.js?v=2.0.0';
import { enqueueBatchJobs, exportZipPack } from '../api.js?v=2.0.0';
import { refreshJobsFromServer, setOpen as setDlPanelOpen } from '../dlpanel.js?v=2.0.0';

let activeGroup = 'ALL';
let activeMod = 'ALL';

export async function renderFavorites(app) {
  app.innerHTML = '<div class="loading-block">正在加载收藏夹…</div>';
  const favMap = getFavorites();
  const entries = Object.values(favMap).sort((a, b) => (b.addedAt || 0) - (a.addedAt || 0));

  // 按需并行加载收藏涉及的游戏索引
  const modsNeeded = [...new Set(entries.map(e => e.mod))];
  await Promise.all(modsNeeded.map(m => ensureModuleIndex(m).catch(() => null)));

  const groups = getGroups();
  if (activeGroup !== 'ALL' && !groups.includes(activeGroup)) activeGroup = 'ALL';

  const resolved = [];
  for (const e of entries) {
    const mod = getModule(e.mod);
    const card = getModuleCard(mod.apiMod, e.id, mod.compositeKey ? e.kind : null);
    if (!card) continue;
    resolved.push({ entry: e, mod, card });
  }

  const filtered = resolved.filter(item => {
    if (activeGroup !== 'ALL' && item.entry.group !== activeGroup) return false;
    if (activeMod !== 'ALL' && item.mod.apiMod !== activeMod) return false;
    return true;
  });

  app.innerHTML = `
  <div class="detail-head">
    <div>
      <div class="page-title">⭐ 我的<span class="hl">收藏夹</span></div>
      <div class="page-desc">跨四大游戏统一收藏 · 自动双写本地浏览器与 <code>data/user_profile.json</code> 防丢失</div>
    </div>
    <div class="head-quick-acts">
      <button class="btn small primary" id="fav-batch-dl" ${filtered.length ? '' : 'disabled'}>⬇️ 批量下载当前（${filtered.length}）</button>
      <button class="btn small sr" id="fav-batch-sr" ${filtered.length ? '' : 'disabled'}>✨ 批量超分</button>
      <button class="btn small" id="fav-export-zip" ${filtered.length ? '' : 'disabled'}>📦 导出 ZIP</button>
    </div>
  </div>
  <div class="section-gap"></div>
  <div class="toolbar-v2">
    <div class="trow chips-row">
      <span class="chip-label">分组</span>
      <button class="chip r-chip ${activeGroup === 'ALL' ? 'on' : ''}" data-grp="ALL">全部（${resolved.length}）</button>
      ${groups.map(g => {
        const n = resolved.filter(x => x.entry.group === g).length;
        return `<button class="chip r-chip ${activeGroup === g ? 'on' : ''}" data-grp="${esc(g)}">📁 ${esc(g)} (${n})</button>`;
      }).join('')}
      <button class="chip" id="grp-add">＋ 新建分组</button>
      ${activeGroup !== 'ALL' && groups.length > 1 ? '<button class="chip reset-chip" id="grp-del">🗑 删除当前分组</button>' : ''}
    </div>
    <div class="trow chips-row">
      <span class="chip-label">游戏</span>
      <button class="chip unit-chip ${activeMod === 'ALL' ? 'on' : ''}" data-m="ALL">全部游戏</button>
      ${MODULES.map(m => {
        const n = resolved.filter(x => x.mod.apiMod === m.apiMod).length;
        return `<button class="chip unit-chip ${activeMod === m.apiMod ? 'on' : ''}" data-m="${esc(m.apiMod)}">${m.icon} ${esc(m.shortName)} (${n})</button>`;
      }).join('')}
    </div>
  </div>
  ${filtered.length
    ? `<div class="card-grid">${filtered.map(item => cardCellHtml(item.card, item.mod.apiMod)).join('')}</div>`
    : `<div class="placeholder-hero">
         <div class="big">⭐</div>
         <h2>这里还没有收藏的卡面</h2>
         <p>在任意图鉴网格卡片右下角点亮 <b>☆</b>，或在详情页右上角点击「收藏」即可收录于此。</p>
         <div class="section-gap"></div>
         <button class="btn primary" onclick="location.hash='#/pjsk/cards'">去逛逛图鉴 →</button>
       </div>`}`;

  app.querySelectorAll('[data-grp]').forEach(btn => {
    btn.onclick = () => { activeGroup = btn.dataset.grp; renderFavorites(app); };
  });
  app.querySelectorAll('[data-m]').forEach(btn => {
    btn.onclick = () => { activeMod = btn.dataset.m; renderFavorites(app); };
  });
  app.querySelector('#grp-add').onclick = () => {
    const name = prompt('输入新收藏分组名称（如：本命 / 桌面壁纸）：');
    if (name && addGroup(name)) {
      toast(`已创建分组「${name.trim()}」`);
      renderFavorites(app);
    }
  };
  app.querySelector('#grp-del')?.addEventListener('click', () => {
    if (confirm(`确认删除分组「${activeGroup}」？组内卡面将自动移至默认分组。`)) {
      removeGroup(activeGroup);
      activeGroup = 'ALL';
      renderFavorites(app);
    }
  });

  const toBatchItems = () => filtered.map(item => ({
    mod: item.mod.apiMod,
    cardId: item.card.id,
    kind: item.mod.defaultArtKind(item.card),
  }));

  app.querySelector('#fav-batch-dl').onclick = async () => {
    if (!(await confirmCopyrightIfNeeded())) return;
    try {
      const r = await enqueueBatchJobs('download', toBatchItems());
      await refreshJobsFromServer();
      setDlPanelOpen(true);
      toast(`已提交 ${r.count} 个原图下载任务`);
    } catch (e) { toast(`提交失败：${e.message}`, true); }
  };

  app.querySelector('#fav-batch-sr').onclick = async () => {
    if (!(await confirmCopyrightIfNeeded())) return;
    const s = getSettings();
    try {
      const r = await enqueueBatchJobs('superres', toBatchItems(), s.srTarget || '4k', s.srEngine || 'ai');
      await refreshJobsFromServer();
      setDlPanelOpen(true);
      toast(`已提交 ${r.count} 个超分任务 ✨`);
    } catch (e) { toast(`提交失败：${e.message}`, true); }
  };

  app.querySelector('#fav-export-zip').onclick = async () => {
    if (!(await confirmCopyrightIfNeeded())) return;
    const btn = app.querySelector('#fav-export-zip');
    btn.disabled = true;
    btn.textContent = '📦 打包中…';
    try {
      const fname = await exportZipPack(toBatchItems(), 'unit', true);
      toast(`收藏包已导出：${fname}`);
    } catch (e) {
      toast(`导出失败：${e.message}`, true);
    } finally {
      btn.disabled = false;
      btn.textContent = '📦 导出 ZIP';
    }
  };
}
