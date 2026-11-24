// 四游戏统一图鉴页：两级筛选 + 收藏/近30天新卡过滤 + 批量选择/下载/超分/ZIP打包导出 + 骨架屏
import { getModule, cardUniqueKey } from '../modules/registry.js?v=2.0.0';
import {
  ensureModuleIndex,
  getModuleCards,
  getModuleCharacters,
  filterCards,
} from '../store.js?v=2.0.0';
import { setPageCleanup } from '../router.js?v=2.0.0';
import {
  esc,
  cardCellHtml,
  cardRowHtml,
  skeletonGridHtml,
  toast,
  confirmCopyrightIfNeeded,
} from '../ui.js?v=2.0.0';
import { getFavorites, getSettings } from '../userSettings.js?v=2.0.0';
import { enqueueBatchJobs, exportZipPack } from '../api.js?v=2.0.0';
import { refreshJobsFromServer, setOpen as setDlPanelOpen } from '../dlpanel.js?v=2.0.0';

const PAGE = 60;
const filters = {
  q: '',
  unit: '',
  characterId: '',
  attr: '',
  rarity: '',
  kind: '',
  favOnly: false,
  recentDays: 0,
  sort: 'id_desc',
};
let view = 'grid';
let shown = PAGE;
let lastMod = null;
let filtersOpen = false;
let batchMode = false;
const selectedMap = new Map(); // uniqueKey -> { mod, cardId, kind }

function countActiveFilters() {
  return (
    (filters.q ? 1 : 0)
    + (filters.unit ? 1 : 0)
    + (filters.characterId ? 1 : 0)
    + (filters.attr ? 1 : 0)
    + (filters.rarity ? 1 : 0)
    + (filters.kind ? 1 : 0)
    + (filters.favOnly ? 1 : 0)
    + (filters.recentDays ? 1 : 0)
  );
}

export async function renderCards(app, modKey = 'pjsk') {
  const mod = getModule(modKey);

  // 严守 T14：跨模块切换必须清空筛选与批量选中状态
  if (lastMod !== mod.apiMod) {
    Object.assign(filters, {
      q: '', unit: '', characterId: '', attr: '', rarity: '', kind: '',
      favOnly: false, recentDays: 0, sort: mod.latestSort === 'release_desc' ? 'id_desc' : 'id_desc',
    });
    selectedMap.clear();
    batchMode = false;
    lastMod = mod.apiMod;
  }

  // 来自首页「近期新卡」快捷入口
  if (sessionStorage.getItem('cardRadar.openRecent') === mod.routeId) {
    sessionStorage.removeItem('cardRadar.openRecent');
    filters.recentDays = 30;
    filters.sort = 'release_desc';
  }

  app.innerHTML = `
    <div class="detail-head">
      <div>
        <div class="page-title">${esc(mod.shortName)}卡面<span class="hl">图鉴</span></div>
        <div class="page-desc">${esc(mod.cardsDesc)}</div>
      </div>
    </div>
    <div class="section-gap"></div>
    ${skeletonGridHtml(12)}`;

  await ensureModuleIndex(mod.apiMod);
  const allCards = getModuleCards(mod.apiMod);
  if (!allCards.length) {
    app.innerHTML = `
    <div class="placeholder-hero">
      <div class="big">${mod.icon}</div>
      <h2>还没有 ${esc(mod.name)} 数据</h2>
      <p>请先运行 <code>${esc(mod.emptyCmd)}</code> 完成首次抓取，然后刷新本页面。</p>
    </div>`;
    return;
  }

  const unitOfChar = new Map(allCards.map(c => [String(c.characterId), c.unitName]));
  const presentUnits = [...new Set(allCards.map(c => c.unitName).filter(Boolean))];
  const specialSet = new Set(mod.specialUnits || []);
  const units = [
    ...mod.unitOrder.filter(u => presentUnits.includes(u)),
    ...presentUnits.filter(u => !mod.unitOrder.includes(u) && !specialSet.has(u)).sort(),
  ];
  const specialUnits = (mod.specialUnits || []).filter(u => presentUnits.includes(u));
  const allChars = getModuleCharacters(mod.apiMod);
  const visibleChars = () => allChars.filter(([id]) => !filters.unit || unitOfChar.get(String(id)) === filters.unit);

  const hasAttrRow = Object.keys(mod.attrNames).length > 0;
  const hasKindRow = (mod.kindChips || []).length > 0;

  app.innerHTML = `
  <div class="detail-head">
    <div>
      <div class="page-title">${esc(mod.shortName)}卡面<span class="hl">图鉴</span></div>
      <div class="page-desc">${esc(mod.cardsDesc)}</div>
    </div>
    <div class="head-quick-acts">
      <button class="chip ${filters.favOnly ? 'on r-chip' : ''}" id="q-fav">⭐ 仅看收藏</button>
      <button class="chip ${filters.recentDays ? 'on r-chip' : ''}" id="q-recent">🆕 近 30 天</button>
      <button class="chip ${batchMode ? 'on r-chip' : ''}" id="q-batch">☑️ 批量选择</button>
    </div>
  </div>
  <div class="section-gap"></div>
  <div class="toolbar-v2 ${filtersOpen ? 'open' : ''}">
    <div class="trow">
      <input class="input search" id="f-q" placeholder="搜索卡名 / 角色 / 乐队 / 编号…（按 / 聚焦）" value="${esc(filters.q)}">
      <div class="seg" id="sort-seg">
        <button data-v="id_desc" class="${filters.sort === 'id_desc' ? 'on' : ''}" title="编号从新到旧">最新</button>
        <button data-v="id_asc" class="${filters.sort === 'id_asc' ? 'on' : ''}" title="编号从旧到新">最早</button>
        <button data-v="release_desc" class="${filters.sort === 'release_desc' ? 'on' : ''}" title="按发布时间倒序">发布 ↓</button>
      </div>
      <div class="view-toggle">
        <button id="v-grid" class="${view === 'grid' ? 'on' : ''}" title="网格视图">▦</button>
        <button id="v-list" class="${view === 'list' ? 'on' : ''}" title="列表视图">☰</button>
      </div>
      <button class="chip f-toggle ${filtersOpen ? 'on' : ''}" id="f-toggle" title="展开/收起详细筛选"></button>
    </div>
    <div class="filter-rows" ${filtersOpen ? '' : 'hidden'}>
      <div class="trow chips-row">
        <span class="chip-label">${esc(mod.unitLabel)}</span>
        ${units.map(u => `<button class="chip unit-chip ${filters.unit === u ? 'on' : ''}" data-unit="${esc(u)}">${esc(u)}</button>`).join('')}
      </div>
      ${specialUnits.length ? `
      <div class="trow chips-row">
        <span class="chip-label">特殊组合</span>
        ${specialUnits.map(u => `<button class="chip unit-chip special ${filters.unit === u ? 'on' : ''}" data-unit="${esc(u)}">${esc(u)}</button>`).join('')}
      </div>` : ''}
      ${hasAttrRow ? `
      <div class="trow chips-row">
        <span class="chip-label">属性</span>
        ${Object.entries(mod.attrNames).map(([k, v]) => `
          <button class="chip attr-chip ${filters.attr === k ? 'on' : ''}" data-attr="${esc(k)}"
                  style="--c:${mod.attrColors[k]}"><i></i>${esc(v)}</button>`).join('')}
      </div>` : ''}
      <div class="trow chips-row">
        <span class="chip-label">稀有度</span>
        ${mod.rarityChips.map(r => `<button class="chip r-chip ${filters.rarity === r.v ? 'on' : ''}" data-r="${esc(r.v)}">${esc(r.label)}</button>`).join('')}
      </div>
      ${hasKindRow ? `
      <div class="trow chips-row">
        <span class="chip-label">${esc(mod.kindLabel)}</span>
        ${mod.kindChips.map(k => `<button class="chip kind-chip ${filters.kind === k.v ? 'on' : ''}" data-kind="${esc(k.v)}">${esc(k.label)}</button>`).join('')}
      </div>` : ''}
      <div class="trow chips-row">
        <span class="chip-label">角色</span>
        <div class="char-dd" id="char-dd">
          <button class="chip dd-btn" id="char-dd-btn">👤 <span id="char-dd-label">${filters.characterId ? esc(allChars.find(([id]) => String(id) === String(filters.characterId))?.[1] || '全部角色') : '全部角色'}</span> ▾</button>
          <div class="dd-panel" id="char-dd-panel" style="display:none"></div>
        </div>
        <span class="dd-tip" id="dd-tip" style="font-size:12px;color:var(--text-3)">${filters.unit ? '' : `提示：先选上方${esc(mod.unitLabel)}可缩小角色范围`}</span>
        <button class="chip reset-chip" id="f-reset">↺ 重置筛选</button>
      </div>
    </div>
  </div>
  <div class="cards-meta-bar" id="cards-meta-bar"></div>
  <div class="card-grid ${view === 'list' ? 'list-view' : ''}" id="grid"></div>
  <div class="load-more-wrap" id="more"></div>
  <div class="batch-bar" id="batch-bar" style="display:none">
    <div class="batch-info">已选择 <b id="batch-count">0</b> 张卡面</div>
    <div class="batch-acts">
      <button class="btn small" id="b-sel-vis">全选当前显示</button>
      <button class="btn small" id="b-clear">清空</button>
      <button class="btn small primary" id="b-dl">⬇️ 批量下载原图</button>
      <button class="btn small sr" id="b-sr">✨ 批量超分</button>
      <select class="select batch-zip-sel" id="b-zip-group" title="ZIP 目录结构">
        <option value="unit">按乐队分目录</option>
        <option value="rarity">按稀有度分目录</option>
        <option value="flat">平铺打包</option>
      </select>
      <button class="btn small" id="b-zip">📦 导出 ZIP</button>
      <button class="btn small" id="b-exit">退出批量</button>
    </div>
  </div>`;

  const grid = app.querySelector('#grid');
  const more = app.querySelector('#more');
  const metaBar = app.querySelector('#cards-meta-bar');
  const ddPanel = app.querySelector('#char-dd-panel');
  const toggleBtn = app.querySelector('#f-toggle');
  const batchBar = app.querySelector('#batch-bar');

  let currentList = [];

  function updateToggleLabel() {
    const cnt = countActiveFilters();
    toggleBtn.classList.toggle('on', filtersOpen);
    toggleBtn.innerHTML = `${filtersOpen ? '▾ 收起筛选' : '▸ 展开筛选'}${cnt ? ` <b>${cnt}</b>` : ''}`;
  }

  function updateBatchBar() {
    batchBar.style.display = batchMode ? 'flex' : 'none';
    app.querySelector('#batch-count').textContent = selectedMap.size;
    app.querySelector('#q-batch').classList.toggle('on', batchMode);
    app.querySelector('#q-batch').classList.toggle('r-chip', batchMode);
  }

  function renderCharDropdown() {
    const list = visibleChars();
    ddPanel.innerHTML = `
      <button class="dd-item ${filters.characterId ? '' : 'on'}" data-v="">全部角色（${list.length}）</button>
      ${list.map(([id, name]) => `
        <button class="dd-item ${String(filters.characterId) === String(id) ? 'on' : ''}" data-v="${id}">${esc(name)}</button>`).join('')}`;
    ddPanel.querySelectorAll('.dd-item').forEach(el => {
      el.onclick = () => {
        filters.characterId = el.dataset.v;
        app.querySelector('#char-dd-label').textContent = el.dataset.v ? el.textContent.trim() : '全部角色';
        ddPanel.style.display = 'none';
        renderCharDropdown();
        refresh();
      };
    });
    const tip = app.querySelector('#dd-tip');
    if (tip) tip.textContent = filters.unit ? '' : `提示：先选上方${mod.unitLabel}可缩小角色范围`;
  }

  function getFiltered() {
    const favMap = getFavorites();
    const favSet = new Set(Object.keys(favMap));
    return filterCards(filters, allCards, {
      favSet,
      keyFn: c => cardUniqueKey(mod.apiMod, c),
    });
  }

  function renderCardChunk(chunk) {
    const opts = { batchMode, selectedSet: selectedMap };
    return (view === 'grid'
      ? chunk.map(c => cardCellHtml(c, mod.apiMod, opts))
      : chunk.map(c => cardRowHtml(c, mod.apiMod, opts))).join('');
  }

  function bindBatchClicks(container) {
    if (!batchMode) return;
    container.querySelectorAll('.card-cell.batch-item').forEach(el => {
      if (el.dataset.bound) return;
      el.dataset.bound = '1';
      el.addEventListener('click', () => {
        const key = el.dataset.batchKey;
        if (selectedMap.has(key)) {
          selectedMap.delete(key);
          el.classList.remove('selected');
          const chk = el.querySelector('.cell-check');
          if (chk) { chk.classList.remove('checked'); chk.textContent = ''; }
        } else {
          selectedMap.set(key, {
            mod: el.dataset.mod,
            cardId: Number(el.dataset.cardId),
            kind: el.dataset.kind,
          });
          el.classList.add('selected');
          const chk = el.querySelector('.cell-check');
          if (chk) { chk.classList.add('checked'); chk.textContent = '✓'; }
        }
        updateBatchBar();
      });
    });
  }

  function updateMore() {
    if (shown >= currentList.length) {
      more.textContent = currentList.length ? `已显示全部 ${currentList.length} 张卡面` : '没有匹配的卡面';
    } else {
      more.innerHTML = `已显示 ${shown} / ${currentList.length} · <a href="javascript:void 0" id="load-more">加载更多（+${PAGE}）</a>`;
      more.querySelector('#load-more').onclick = () => {
        const from = shown;
        shown += PAGE;
        grid.insertAdjacentHTML('beforeend', renderCardChunk(currentList.slice(from, shown)));
        bindBatchClicks(grid);
        updateMore();
      };
    }
  }

  function syncChipActive() {
    app.querySelectorAll('.unit-chip').forEach(el => el.classList.toggle('on', el.dataset.unit === filters.unit));
    app.querySelectorAll('.attr-chip').forEach(el => el.classList.toggle('on', el.dataset.attr === filters.attr));
    app.querySelectorAll('.r-chip[data-r]').forEach(el => el.classList.toggle('on', el.dataset.r === filters.rarity));
    app.querySelectorAll('.kind-chip').forEach(el => el.classList.toggle('on', el.dataset.kind === filters.kind));
    const qFav = app.querySelector('#q-fav');
    qFav.classList.toggle('on', filters.favOnly);
    qFav.classList.toggle('r-chip', filters.favOnly);
    const qRec = app.querySelector('#q-recent');
    qRec.classList.toggle('on', Boolean(filters.recentDays));
    qRec.classList.toggle('r-chip', Boolean(filters.recentDays));
    updateToggleLabel();
  }

  function refresh() {
    currentList = getFiltered();
    shown = PAGE;
    grid.classList.toggle('list-view', view === 'list');
    grid.innerHTML = renderCardChunk(currentList.slice(0, shown));
    bindBatchClicks(grid);
    metaBar.textContent = `匹配 ${currentList.length} / 共 ${allCards.length} 张卡面${batchMode ? ' · 点击卡面即可多选' : ''}`;
    updateMore();
    updateToggleLabel();
    updateBatchBar();
  }

  // 事件绑定
  let qTimer = null;
  app.querySelector('#f-q').addEventListener('input', e => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { filters.q = e.target.value; refresh(); }, 180);
  });

  app.querySelectorAll('.unit-chip').forEach(el => {
    el.onclick = () => {
      filters.unit = filters.unit === el.dataset.unit ? '' : el.dataset.unit;
      if (filters.unit && filters.characterId && unitOfChar.get(String(filters.characterId)) !== filters.unit) {
        filters.characterId = '';
        app.querySelector('#char-dd-label').textContent = '全部角色';
      }
      renderCharDropdown();
      syncChipActive();
      refresh();
    };
  });

  app.querySelectorAll('.attr-chip').forEach(el => {
    el.onclick = () => {
      filters.attr = filters.attr === el.dataset.attr ? '' : el.dataset.attr;
      syncChipActive();
      refresh();
    };
  });

  app.querySelectorAll('.r-chip[data-r]').forEach(el => {
    el.onclick = () => {
      filters.rarity = filters.rarity === el.dataset.r ? '' : el.dataset.r;
      syncChipActive();
      refresh();
    };
  });

  app.querySelectorAll('.kind-chip').forEach(el => {
    el.onclick = () => {
      filters.kind = filters.kind === el.dataset.kind ? '' : el.dataset.kind;
      syncChipActive();
      refresh();
    };
  });

  app.querySelector('#q-fav').onclick = () => {
    filters.favOnly = !filters.favOnly;
    syncChipActive();
    refresh();
  };

  app.querySelector('#q-recent').onclick = () => {
    filters.recentDays = filters.recentDays ? 0 : 30;
    if (filters.recentDays) {
      filters.sort = 'release_desc';
      app.querySelectorAll('#sort-seg button').forEach(b => b.classList.toggle('on', b.dataset.v === 'release_desc'));
    }
    syncChipActive();
    refresh();
  };

  app.querySelector('#q-batch').onclick = () => {
    batchMode = !batchMode;
    if (!batchMode) selectedMap.clear();
    refresh();
  };

  // 修复原版下拉外部点击 { once: true } 导致二次失效的问题，并在离页时自动解绑
  const onDocClick = () => { ddPanel.style.display = 'none'; };
  document.addEventListener('click', onDocClick);
  setPageCleanup(() => document.removeEventListener('click', onDocClick));

  app.querySelector('#char-dd-btn').onclick = e => {
    e.stopPropagation();
    ddPanel.style.display = ddPanel.style.display === 'none' ? 'block' : 'none';
  };
  ddPanel.addEventListener('click', e => e.stopPropagation());

  app.querySelector('#f-reset').onclick = () => {
    Object.assign(filters, {
      q: '', unit: '', characterId: '', attr: '', rarity: '', kind: '', favOnly: false, recentDays: 0,
    });
    app.querySelector('#f-q').value = '';
    app.querySelector('#char-dd-label').textContent = '全部角色';
    renderCharDropdown();
    syncChipActive();
    refresh();
  };

  app.querySelectorAll('#sort-seg button').forEach(el => {
    el.onclick = () => {
      filters.sort = el.dataset.v;
      app.querySelectorAll('#sort-seg button').forEach(x => x.classList.toggle('on', x === el));
      refresh();
    };
  });

  toggleBtn.onclick = () => {
    filtersOpen = !filtersOpen;
    app.querySelector('.filter-rows').hidden = !filtersOpen;
    updateToggleLabel();
  };

  app.querySelector('#v-grid').onclick = () => {
    view = 'grid';
    app.querySelector('#v-grid').classList.add('on');
    app.querySelector('#v-list').classList.remove('on');
    refresh();
  };
  app.querySelector('#v-list').onclick = () => {
    view = 'list';
    app.querySelector('#v-list').classList.add('on');
    app.querySelector('#v-grid').classList.remove('on');
    refresh();
  };

  // 批量操作栏事件
  app.querySelector('#b-sel-vis').onclick = () => {
    for (const c of currentList.slice(0, shown)) {
      selectedMap.set(cardUniqueKey(mod.apiMod, c), {
        mod: mod.apiMod,
        cardId: c.id,
        kind: mod.defaultArtKind(c),
      });
    }
    refresh();
  };
  app.querySelector('#b-clear').onclick = () => {
    selectedMap.clear();
    refresh();
  };
  app.querySelector('#b-exit').onclick = () => {
    batchMode = false;
    selectedMap.clear();
    refresh();
  };

  async function runBatch(action) {
    const items = [...selectedMap.values()];
    if (!items.length) { toast('请先勾选至少一张卡面', true); return; }
    if (!(await confirmCopyrightIfNeeded())) return;
    const s = getSettings();
    try {
      const r = await enqueueBatchJobs(action, items, s.srTarget || '4k', s.srEngine || 'ai');
      await refreshJobsFromServer();
      setDlPanelOpen(true);
      toast(`已提交 ${r.count} 个${action === 'superres' ? '超分（GPU 串行保护）' : '下载'}任务`);
    } catch (e) {
      toast(`批量提交失败：${e.message}`, true);
    }
  }

  app.querySelector('#b-dl').onclick = () => runBatch('download');
  app.querySelector('#b-sr').onclick = () => runBatch('superres');
  app.querySelector('#b-zip').onclick = async () => {
    const items = [...selectedMap.values()];
    if (!items.length) { toast('请先勾选至少一张卡面', true); return; }
    if (!(await confirmCopyrightIfNeeded())) return;
    const btn = app.querySelector('#b-zip');
    const groupBy = app.querySelector('#b-zip-group').value;
    btn.disabled = true;
    btn.textContent = '📦 打包中…';
    try {
      const fname = await exportZipPack(items, groupBy, true);
      toast(`已导出压缩包：${fname}`);
    } catch (e) {
      toast(`打包失败：${e.message}`, true);
    } finally {
      btn.disabled = false;
      btn.textContent = '📦 导出 ZIP';
    }
  };

  renderCharDropdown();
  syncChipActive();
  refresh();
}
