// 卡牌图鉴（pjsk / bandori / onotes / shinycolors 四模块）：风格化筛选（彩色属性 pill / 稀有度 chip / 自定义角色下拉 / 分段排序）
import { ensureIndex, ensureBandoriIndex, ensureShinyIndex, ensureOnotesIndex, filterCards, characters, bandoriCharacters, shinyCharacters, onotesCharacters,
         getCards, getBandoriCards, getShinyCards, getOnotesCards } from '../store.js?v=1.16.0';
import { esc, cardCellHtml, attrDot, ATTR_COLORS, ATTR_NAMES,
         BANDORI_ATTR_COLORS, BANDORI_ATTR_NAMES, ONOTES_ATTR_COLORS, ONOTES_ATTR_NAMES } from '../ui.js?v=1.16.0';

const PAGE = 60;
const filters = { q: '', unit: '', characterId: '', attr: '', rarity: '', kind: '', sort: 'id_desc' };
let view = 'grid';
let shown = PAGE;
let lastMod = null;
let filtersOpen = false;

function listRowHtml(c, mod) {
  const bandori = mod === 'bandori';
  const shiny = mod === 'shinycolors';
  const onotes = mod === 'onotes';
  const dir = bandori ? '/api/bandori/thumbs'
    : shiny ? '/api/shinycolors/thumbs'
    : onotes ? '/api/onotes/thumbs' : '/api/thumbs';
  const hash = bandori ? `#/bandori/card/${c.id}`
    : shiny ? `#/sc/card/${c.id}`
    : onotes ? `#/onotes/card/${c.cardKind === 'support' ? 'support' : 'card'}/${c.id}`
    : `#/card/${c.id}`;
  const colors = onotes ? ONOTES_ATTR_COLORS : bandori ? BANDORI_ATTR_COLORS : ATTR_COLORS;
  const names = onotes ? ONOTES_ATTR_NAMES : bandori ? BANDORI_ATTR_NAMES : ATTR_NAMES;
  const thumbFile = onotes ? `${c.id}_${c.cardKind === 'support' ? 'support' : 'card'}.webp`
    : `${c.id}_normal.webp`;
  return `
  <div class="card-cell" onclick="location.hash='${hash}'">
    <div class="thumb-wrap"><img src="${dir}/${thumbFile}" loading="lazy" alt=""></div>
    <div class="meta">
      <div class="prefix">${attrDot(c.attr, colors, names)}${esc(c.prefix)} ${c.spoiler ? '<span class="badge spoiler">剧透</span>' : ''}</div>
      <div class="sub"><span>${esc(c.characterName)}</span><span>${mod === "shinycolors" || onotes ? c.rarity : c.rarity + "★"}</span><span>#${c.id}</span></div>
    </div>
  </div>`;
}

const CFG = {
  pjsk: {
    ensure: ensureIndex,
    getCards,
    characters,
    filter: f => filterCards(f),
    attrColors: ATTR_COLORS,
    attrNames: ATTR_NAMES,
    unitOrder: ['Leo/need', 'MORE MORE JUMP!', 'Vivid BAD SQUAD',
                'Wonderlands×Showtime', '25时，Nightcord见。', '虚拟歌手'],
    unitLabel: '组合',
    rarityChips: [
      { v: '4', label: '4★' }, { v: '3', label: '3★' }, { v: '2', label: '2★' },
      { v: '1', label: '1★' }, { v: 'birthday', label: '生日' },
    ],
    title: '卡牌图鉴',
    desc: '浏览本地镜像的全部卡牌 · 数据每两周自动更新（周一 · JP 服务器 · 中文显示）',
    cell: c => cardCellHtml(c, 'pjsk'),
    row: c => listRowHtml(c, 'pjsk'),
    emptyIcon: '📦',
    emptyTitle: '还没有卡牌数据',
    emptyHint: '请先运行项目里的 <code>scripts\\run_scrape.cmd</code> 完成首次抓取，然后刷新本页面。',
  },
  shinycolors: {
    ensure: ensureShinyIndex,
    getCards: getShinyCards,
    characters: shinyCharacters,
    filter: f => filterCards(f, getShinyCards()),
    attrColors: {},
    attrNames: {},
    // 主组合 8 团；283pro 及其之后的组合（事务所/衍生团体）划入「特殊组合」栏
    unitOrder: ['illumination STARS', "L'Antica", '放課後クライマックスガールズ',
                'ALSTROEMERIA', 'Straylight', 'noctchill', 'SHHis', 'CoMETIK'],
    specialUnits: ['２８３プロ', 'B小町', '劇団ララライ'],
    rarityChips: [
      { v: 'UR', label: 'UR' }, { v: 'SSR', label: 'SSR' }, { v: 'SR', label: 'SR' },
      { v: 'R', label: 'R' }, { v: 'N', label: 'N' },
    ],
    kindLabel: '卡面种类',
    kindChips: [
      { v: 'P', label: 'Produce' }, { v: 'S', label: 'Support' },
    ],
    unitLabel: '組合',
    title: '卡面图鉴',
    desc: '浏览本地镜像的全部闪耀色彩卡面 · 数据每两周自动更新（shinycolors.moe · 日文显示）',
    cell: c => cardCellHtml(c, 'shinycolors'),
    row: c => listRowHtml(c, 'shinycolors'),
    rarityText: true,
    emptyIcon: '✨',
    emptyTitle: '还没有闪耀色彩卡面数据',
    emptyHint: '请先运行项目里的 <code>scripts\\run_shinycolors_scrape.cmd</code> 完成首次抓取，然后刷新本页面。',
  },
  // Our Notes（bdon.moe）：角色卡（R/SR/SSR/BD，五属性）+ 支援卡（稀有度 3/4/10，无属性）
  onotes: {
    ensure: ensureOnotesIndex,
    getCards: getOnotesCards,
    characters: onotesCharacters,
    filter: f => filterCards(f, getOnotesCards()),
    attrColors: ONOTES_ATTR_COLORS,
    attrNames: ONOTES_ATTR_NAMES,
    unitOrder: ['MyGO!!!!!', 'Ave Mujica', '梦限大MewType', 'millsage', '一家Dumb Rock!'],
    unitLabel: '乐队',
    // 支援卡稀有度经爬虫映射为官方显示名：R/SR/SSR/EX（特殊档官方图标即 EX 艺术字）
    rarityChips: [
      { v: 'SSR', label: 'SSR' }, { v: 'SR', label: 'SR' }, { v: 'R', label: 'R' },
      { v: 'BD', label: 'BD' }, { v: '特殊', label: 'EX' },
    ],
    kindLabel: '卡面种类',
    kindChips: [
      { v: 'card', label: '角色卡' }, { v: 'support', label: '支援卡' },
    ],
    title: '卡面图鉴',
    desc: '浏览本地镜像的全部 Our Notes 卡面 · 数据每两周自动更新（bdon.moe · 简体中文）',
    cell: c => cardCellHtml(c, 'onotes'),
    row: c => listRowHtml(c, 'onotes'),
    emptyIcon: '🎶',
    emptyTitle: '还没有 Our Notes 卡面数据',
    emptyHint: '请先运行项目里的 <code>scripts\\run_onotes_scrape.cmd</code> 完成首次抓取，然后刷新本页面。',
  },
  bandori: {
    ensure: ensureBandoriIndex,
    getCards: getBandoriCards,
    characters: bandoriCharacters,
    filter: f => filterCards(f, getBandoriCards()),
    attrColors: BANDORI_ATTR_COLORS,
    attrNames: BANDORI_ATTR_NAMES,
    unitOrder: ["Poppin'Party", 'Afterglow', 'Hello, Happy World!', 'Pastel*Palettes',
                'Roselia', 'Morfonica', 'RAISE A SUILEN', 'MyGO!!!!!'],
    unitLabel: '乐团',
    rarityChips: [
      { v: '5', label: '5★' }, { v: '4', label: '4★' }, { v: '3', label: '3★' },
      { v: '2', label: '2★' }, { v: '1', label: '1★' },
    ],
    title: '卡面图鉴',
    desc: '浏览本地镜像的全部邦多利卡面 · 数据每两周自动更新（周一 · bestdori · 中文显示）',
    cell: c => cardCellHtml(c, 'bandori'),
    row: c => listRowHtml(c, 'bandori'),
    emptyIcon: '🎸',
    emptyTitle: '还没有邦多利卡面数据',
    emptyHint: '请先运行项目里的 <code>scripts\\run_bandori_scrape.cmd</code> 完成首次抓取，然后刷新本页面。',
  },
};

export async function renderCards(app, mod = 'pjsk') {
  const cfg = CFG[mod] || CFG.pjsk;
  // 切换游戏模块时清空筛选：filters 是模块级共享状态，跨模块残留会把
  // 另一个模块筛空（如闪彩的 kind=P / unit=illumination STARS 对 pjsk 全部不命中）
  if (lastMod !== mod) {
    Object.assign(filters, { q: '', unit: '', characterId: '', attr: '', rarity: '', kind: '' });
    lastMod = mod;
  }
  app.innerHTML = '<div class="loading-block">正在加载图鉴…</div>';
  await cfg.ensure();
  if (!cfg.getCards().length) {
    app.innerHTML = `
    <div class="placeholder-hero">
      <div class="big">${cfg.emptyIcon}</div>
      <h2>${cfg.emptyTitle}</h2>
      <p>${cfg.emptyHint}</p>
    </div>`;
    return;
  }
  // 角色 → 所属团体映射（两级筛选：团体 chip 收窄角色下拉）
  const unitOfChar = new Map(cfg.getCards().map(c => [c.characterId, c.unitName]));
  const present = [...new Set(cfg.getCards().map(c => c.unitName).filter(Boolean))];
  const specialSet = new Set(cfg.specialUnits || []);
  const units = [
    ...cfg.unitOrder.filter(u => present.includes(u)),
    ...present.filter(u => !cfg.unitOrder.includes(u) && !specialSet.has(u)).sort(),
  ];
  // 特殊组合（283pro 及其之后的衍生组合）：与主组合共用 filters.unit
  const specialUnits = (cfg.specialUnits || []).filter(u => present.includes(u));
  const visibleChars = () => cfg.characters().filter(([id]) =>
    !filters.unit || unitOfChar.get(Number(id)) === filters.unit);
  const chars = visibleChars();
  const hasAttrRow = Object.keys(cfg.attrNames).length > 0;
  const hasKindRow = (cfg.kindChips || []).length > 0;
  // 筛选栏收缩状态（跨页面保持）；激活中的筛选数量显示在收起按钮上，
  // 避免收起时看不到当前有筛选在生效
  const filterActiveCount =
    (filters.q ? 1 : 0) + (filters.unit ? 1 : 0) + (filters.characterId ? 1 : 0) +
    (filters.attr ? 1 : 0) + (filters.rarity ? 1 : 0) + (filters.kind ? 1 : 0);

  app.innerHTML = `
  <div class="detail-head">
    <div>
      <div class="page-title">${mod === 'bandori' ? '邦多利' : ''}卡面<span class="hl">图鉴</span></div>
      <div class="page-desc">${esc(cfg.desc)}</div>
    </div>
  </div>
  <div class="section-gap"></div>
  <div class="toolbar-v2 ${filtersOpen ? 'open' : ''}">
    <div class="trow">
      <input class="input search" id="f-q" placeholder="搜索卡名 / 角色名 / 编号…" value="${esc(filters.q)}">
      <div class="seg" id="sort-seg">
        <button data-v="id_desc" class="${filters.sort === 'id_desc' ? 'on' : ''}" title="编号从新到旧">最新</button>
        <button data-v="id_asc" class="${filters.sort === 'id_asc' ? 'on' : ''}" title="编号从旧到旧">最早</button>
        <button data-v="release_desc" class="${filters.sort === 'release_desc' ? 'on' : ''}" title="按发布时间">发布 ↓</button>
      </div>
      <div class="view-toggle">
        <button id="v-grid" class="${view === 'grid' ? 'on' : ''}" title="网格视图">▦</button>
        <button id="v-list" class="${view === 'list' ? 'on' : ''}" title="列表视图">☰</button>
      </div>
      <button class="chip f-toggle ${filtersOpen ? 'on' : ''}" id="f-toggle"
              title="展开/收起筛选栏">${filtersOpen ? '▾ 收起筛选' : '▸ 展开筛选'}${filterActiveCount ? ` <b>${filterActiveCount}</b>` : ''}</button>
    </div>
    <div class="filter-rows" ${filtersOpen ? '' : 'hidden'}>
    <div class="trow chips-row">
      <span class="chip-label">${cfg.unitLabel}</span>
      ${units.map(u => `
        <button class="chip unit-chip ${filters.unit === u ? 'on' : ''}" data-unit="${esc(u)}">${esc(u)}</button>`).join('')}
    </div>
    ${specialUnits.length ? `
    <div class="trow chips-row">
      <span class="chip-label">特殊组合</span>
      ${specialUnits.map(u => `
        <button class="chip unit-chip special ${filters.unit === u ? 'on' : ''}" data-unit="${esc(u)}">${esc(u)}</button>`).join('')}
    </div>` : ''}
    ${hasAttrRow ? `
    <div class="trow chips-row">
      <span class="chip-label">属性</span>
      ${Object.entries(cfg.attrNames).map(([k, v]) => `
        <button class="chip attr-chip ${filters.attr === k ? 'on' : ''}" data-attr="${k}"
                style="--c:${cfg.attrColors[k]}"><i></i>${esc(v)}</button>`).join('')}
    </div>` : ''}
    <div class="trow chips-row">
      <span class="chip-label">稀有度</span>
      ${cfg.rarityChips.map(r => `
        <button class="chip r-chip ${filters.rarity === r.v ? 'on' : ''}" data-r="${r.v}">${r.label}</button>`).join('')}
    </div>
    ${hasKindRow ? `
    <div class="trow chips-row">
      <span class="chip-label">${cfg.kindLabel}</span>
      ${cfg.kindChips.map(k => `
        <button class="chip kind-chip ${filters.kind === k.v ? 'on' : ''}" data-kind="${k.v}">${k.label}</button>`).join('')}
    </div>` : ''}
    <div class="trow chips-row">
      <span class="chip-label">角色</span>
      <div class="char-dd" id="char-dd">
        <button class="chip dd-btn" id="char-dd-btn">👤 <span id="char-dd-label">${filters.characterId ? esc(chars.find(([id]) => String(id) === String(filters.characterId))?.[1] || '全部角色') : '全部角色'}</span> ▾</button>
        <div class="dd-panel" id="char-dd-panel" style="display:none">
          <button class="dd-item ${filters.characterId ? '' : 'on'}" data-v="">全部角色</button>
          ${chars.map(([id, name]) => `
            <button class="dd-item ${String(filters.characterId) === String(id) ? 'on' : ''}" data-v="${id}">${esc(name)}</button>`).join('')}
        </div>
      </div>
      ${filters.unit ? '' : `<span style="font-size:12px;color:var(--text-3)">提示：先选上方${esc(cfg.unitLabel)}可缩小角色范围</span>`}
      <button class="chip reset-chip" id="f-reset">↺ 重置</button>
    </div>
    </div>
  </div>
  <div class="card-grid ${view === 'list' ? 'list-view' : ''}" id="grid"></div>
  <div class="load-more-wrap" id="more"></div>`;

  const grid = app.querySelector('#grid');
  const more = app.querySelector('#more');

  function visibleHtml(list) {
    const part = list.slice(0, shown);
    return (view === 'grid' ? part.map(cfg.cell) : part.map(cfg.row)).join('');
  }

  function updateMore(list) {
    if (shown >= list.length) {
      more.textContent = list.length ? `已显示全部 ${list.length} 张卡牌` : '没有匹配的卡牌';
      more.onclick = null;
    } else {
      more.innerHTML = `已显示 ${shown} / ${list.length} · <a href="javascript:void 0" id="load-more">加载更多</a>`;
      more.querySelector('#load-more').onclick = () => {
        const cur = cfg.filter(filters);
        const from = shown;
        shown += PAGE;
        const chunk = cur.slice(from, shown);
        grid.insertAdjacentHTML('beforeend',
          (view === 'grid' ? chunk.map(cfg.cell) : chunk.map(cfg.row)).join(''));
        updateMore(cur);
      };
    }
  }

  function refresh() {
    const list = cfg.filter(filters);
    shown = PAGE;
    grid.classList.toggle('list-view', view === 'list');
    grid.innerHTML = visibleHtml(list);
    updateMore(list);
  }

  function syncChipActive() {
    app.querySelectorAll('.unit-chip').forEach(el =>
      el.classList.toggle('on', el.dataset.unit === filters.unit));
    app.querySelectorAll('.attr-chip').forEach(el =>
      el.classList.toggle('on', el.dataset.attr === filters.attr));
    app.querySelectorAll('.r-chip').forEach(el =>
      el.classList.toggle('on', el.dataset.r === filters.rarity));
    app.querySelectorAll('.kind-chip').forEach(el =>
      el.classList.toggle('on', el.dataset.kind === filters.kind));
  }

  // 搜索
  let qTimer = null;
  app.querySelector('#f-q').addEventListener('input', e => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { filters.q = e.target.value; refresh(); }, 200);
  });
  // 团体 chip（单选，再点取消）：两级筛选第一步——切换后角色下拉按团体收窄，
  // 已选角色不属于新团体时自动清空
  app.querySelectorAll('.unit-chip').forEach(el => {
    el.onclick = () => {
      filters.unit = filters.unit === el.dataset.unit ? '' : el.dataset.unit;
      if (filters.unit && filters.characterId &&
          unitOfChar.get(Number(filters.characterId)) !== filters.unit) {
        filters.characterId = '';
        app.querySelector('#char-dd-label').textContent = '全部角色';
      }
      ddPanel.innerHTML = `
        <button class="dd-item ${filters.characterId ? '' : 'on'}" data-v="">全部角色</button>
        ${visibleChars().map(([id, name]) => `
          <button class="dd-item ${String(filters.characterId) === String(id) ? 'on' : ''}" data-v="${id}">${esc(name)}</button>`).join('')}`;
      bindCharItems();
      syncChipActive(); refresh();
    };
  });
  // 属性 chip（单选，再点取消）
  app.querySelectorAll('.attr-chip').forEach(el => {
    el.onclick = () => {
      filters.attr = filters.attr === el.dataset.attr ? '' : el.dataset.attr;
      syncChipActive(); refresh();
    };
  });
  // 稀有度 chip（单选，再点取消）
  app.querySelectorAll('.r-chip').forEach(el => {
    el.onclick = () => {
      filters.rarity = filters.rarity === el.dataset.r ? '' : el.dataset.r;
      syncChipActive(); refresh();
    };
  });
  // 卡面种类 chip（Produce/Support，单选，再点取消）
  app.querySelectorAll('.kind-chip').forEach(el => {
    el.onclick = () => {
      filters.kind = filters.kind === el.dataset.kind ? '' : el.dataset.kind;
      syncChipActive(); refresh();
    };
  });
  // 角色自定义下拉
  const dd = app.querySelector('#char-dd');
  const ddPanel = app.querySelector('#char-dd-panel');
  function bindCharItems() {
    ddPanel.querySelectorAll('.dd-item').forEach(el => {
      el.onclick = () => {
        filters.characterId = el.dataset.v;
        app.querySelector('#char-dd-label').textContent =
          el.textContent.trim() || '全部角色';
        ddPanel.querySelectorAll('.dd-item').forEach(x => x.classList.toggle('on', x === el));
        refresh();
      };
    });
  }
  bindCharItems();
  app.querySelector('#char-dd-btn').onclick = e => {
    e.stopPropagation();
    ddPanel.style.display = ddPanel.style.display === 'none' ? 'block' : 'none';
  };
  ddPanel.addEventListener('click', e => e.stopPropagation());
  document.addEventListener('click', () => { ddPanel.style.display = 'none'; }, { once: true });
  // 重置
  app.querySelector('#f-reset').onclick = () => {
    filters.q = ''; filters.unit = ''; filters.characterId = '';
    filters.attr = ''; filters.rarity = ''; filters.kind = '';
    app.querySelector('#f-q').value = '';
    app.querySelector('#char-dd-label').textContent = '全部角色';
    ddPanel.innerHTML = `
      <button class="dd-item on" data-v="">全部角色</button>
      ${chars.map(([id, name]) => `
        <button class="dd-item" data-v="${id}">${esc(name)}</button>`).join('')}`;
    bindCharItems();
    syncChipActive(); refresh();
  };
  // 排序分段控件
  app.querySelectorAll('#sort-seg button').forEach(el => {
    el.onclick = () => {
      filters.sort = el.dataset.v;
      app.querySelectorAll('#sort-seg button').forEach(x => x.classList.toggle('on', x === el));
      refresh();
    };
  });
  // 筛选栏展开/收起（收缩时只留搜索框行，不遮挡视线）
  app.querySelector('#f-toggle').onclick = () => {
    filtersOpen = !filtersOpen;
    const rows = app.querySelector('.filter-rows');
    rows.hidden = !filtersOpen;
    const btn = app.querySelector('#f-toggle');
    btn.classList.toggle('on', filtersOpen);
    btn.innerHTML = `${filtersOpen ? '▾ 收起筛选' : '▸ 展开筛选'}${filterActiveCount ? ` <b>${filterActiveCount}</b>` : ''}`;
  };
  // 视图切换
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

  refresh();
}
