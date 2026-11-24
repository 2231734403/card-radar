// 四游戏统一卡面详情页引擎（彻底取代旧 detail.js + module.js 的 750 行重复逻辑）
// 核心能力：
//  - 两段式秒开渲染（索引骨架立即出图，详情接口异步补全）
//  - 支持原图下载 + 一键超分 + 原图 vs 2K/4K 超分交互对比滑块
//  - 收藏星标与自定义分组即时管理
//  - 键盘 ← / → 翻卡（自动清理监听）
//  - 监听 dl:done 对全部四个游戏实时刷新，出现「在线查看 / 画质对比」按钮
import { getModule } from '../modules/registry.js?v=2.0.0';
import { fetchCardDetail, downloadOriginal, superresImage } from '../api.js?v=2.0.0';
import { ensureModuleIndex, getModuleCard, getModuleCards } from '../store.js?v=2.0.0';
import { render, setPageCleanup } from '../router.js?v=2.0.0';
import {
  esc,
  attrDot,
  rarityLabel,
  fmtDate,
  fmtReleaseLabel,
  openImageModal,
  openCompareModal,
  confirmCopyrightIfNeeded,
  toast,
} from '../ui.js?v=2.0.0';
import { registerJob } from '../dlpanel.js?v=2.0.0';
import {
  getSettings,
  isFavorite,
  getFavoriteEntry,
  toggleFavorite,
  setFavoriteGroup,
  getGroups,
} from '../userSettings.js?v=2.0.0';

const PJSK_SOURCE_NAMES = { card: '卡牌服装', shop: '商店购买', other: '其他' };
const PJSK_PART_NAMES = { body: '服装', hair: '发型', head: '头饰' };
const BANDORI_TYPE_NAMES = {
  permanent: '常驻', event: '活动', limited: '限定', dreamfes: 'Dreamfes',
  campaign: '活动奖励', birthday: '生日', kirafes: 'KiraFes', special: '特殊',
  initial: '初始', others: '其他',
};

function artBoxesFor(mod, card, detail) {
  const media = detail?.media || {};
  if (mod.apiMod === 'onotes') {
    const k = card.cardKind === 'support' ? 'support' : 'card';
    return [{
      kind: k,
      label: k === 'support' ? '支援卡图' : '卡面图（1440×1920）',
      disabled: false,
      note: '高清原档 · PNG 无损转出 · 可直接超分与画质对比',
      thumb: mod.thumbUrl(card, k),
      media: media[k] || { hasOriginal: Boolean(detail?.hasOriginal) },
    }];
  }
  if (mod.apiMod === 'shinycolors') {
    const boxes = [{
      kind: 'normal',
      label: '卡面图',
      disabled: false,
      note: '优先 2272×1280 高清档 · 无损 PNG 输出',
      thumb: mod.thumbUrl(card, 'normal'),
      media: media.normal || { hasOriginal: Boolean(detail?.hasOriginal) },
    }];
    if (card.trainable) {
      boxes.push({
        kind: 'fes',
        label: 'Fes 卡面（特训后）',
        disabled: false,
        note: '优先 2272×1280 高清档 · 无损 PNG 输出',
        thumb: mod.thumbUrl(card, 'fes'),
        media: media.fes || { hasOriginal: Boolean(detail?.hasFesOriginal) },
      });
    }
    return boxes;
  }
  // PJSK & Bandori 双图盒
  return [
    {
      kind: 'normal',
      label: '突破前',
      disabled: false,
      note: 'PNG 无损原档 · 进度见左下角「下载管理」',
      thumb: mod.thumbUrl(card, 'normal'),
      media: media.normal || {},
    },
    {
      kind: 'after_training',
      label: '突破后（特训）',
      disabled: !card.trainable,
      disabledText: mod.apiMod === 'pjsk' ? '该卡为低稀有度 / 生日卡，无突破卡面' : '该卡无突破后独立卡面',
      note: 'PNG 无损原档 · 进度见左下角「下载管理」',
      thumb: mod.thumbUrl(card, 'after_training'),
      media: media.after_training || {},
    },
  ];
}

function renderArtBoxHtml(mod, card, box) {
  const m = box.media || {};
  const hasOrig = Boolean(m.hasOriginal);
  const origUrl = m.originalUrl || `/api/v2/modules/${mod.apiMod}/originals/${card.id}/${box.kind}`;
  const srUrl = m.has4k ? m.url4k : (m.has2k ? m.url2k : '');
  const srTag = m.has4k ? '4K 超分' : (m.has2k ? '2K 超分' : '');

  return `
  <div class="art-box">
    <div class="tag">${esc(box.label)}</div>
    ${box.disabled
      ? '<div class="img-wrap disabled-art">🌙 无突破卡面</div>'
      : `<div class="img-wrap" data-zoom-src="${esc(hasOrig ? origUrl : box.thumb)}" data-zoom-cap="${esc(`${card.prefix} · ${box.label}`)}">
          <img src="${esc(box.thumb)}" loading="lazy" alt="${esc(box.label)}"
               onerror="this.parentElement.innerHTML='<div class=\\'disabled-art\\'>暂无卡面图片</div>'">
        </div>`}
    <div class="actions">
      ${box.disabled
        ? `<span class="note" style="margin:0">${esc(box.disabledText)}</span>`
        : `<button class="btn primary" data-act="dl" data-kind="${esc(box.kind)}">⬇️ 下载原图</button>
           <button class="btn sr" data-act="sr" data-kind="${esc(box.kind)}">✨ 超分</button>
           ${hasOrig ? `<a class="btn small" href="${esc(origUrl)}" target="_blank" rel="noopener">👁 查看原图</a>` : ''}
           ${hasOrig && srUrl ? `<button class="btn small compare-btn" data-act="cmp" data-orig="${esc(origUrl)}" data-sr="${esc(srUrl)}" data-sr-tag="${esc(srTag)}">⚖️ 对比${esc(srTag)}</button>` : ''}
           ${!hasOrig ? `<span class="note">${esc(box.note)}</span>` : ''}`}
    </div>
  </div>`;
}

function renderBasicInfoRows(mod, card, detail) {
  const loading = detail ? '' : ' <span style="color:var(--text-3)">（加载中…）</span>';
  if (mod.apiMod === 'pjsk') {
    const ch = detail?.character || {};
    return `
      <tr><th>卡牌编号</th><td>#${card.id}（seq ${card.seq ?? '—'}）</td></tr>
      <tr><th>卡面名称</th><td>${esc(card.prefix)}</td></tr>
      <tr><th>角色</th><td>${esc(card.characterFullName || card.characterName)}</td></tr>
      <tr><th>所属组合</th><td>${esc(card.unitName)}</td></tr>
      <tr><th>属性</th><td>${attrDot(card.attr, mod.attrColors, mod.attrNames)} ${esc(mod.attrNames[card.attr] || card.attr)}</td></tr>
      <tr><th>稀有度</th><td><span class="rarity-stars">${'★'.repeat(card.rarity || 1)}</span>（${esc(rarityLabel(card))}）</td></tr>
      <tr><th>日服上线</th><td>${fmtReleaseLabel(card.releaseJp || card.releaseAt)}</td></tr>
      <tr><th>资源标识</th><td class="mono">${esc(card.assetbundleName || '')}</td></tr>
      ${ch.birthday ? `<tr><th>角色生日</th><td>${esc(ch.birthday)}</td></tr>` : ''}`;
  }
  if (mod.apiMod === 'bandori') {
    const cType = detail?.cardType || card.cardType;
    return `
      <tr><th>卡面编号</th><td>#${card.id}</td></tr>
      <tr><th>卡面名称</th><td>${esc(card.prefix || '（未命名）')}</td></tr>
      <tr><th>角色</th><td>${esc(card.characterName)}</td></tr>
      <tr><th>所属乐团</th><td>${esc(card.unitName)}</td></tr>
      <tr><th>属性</th><td>${attrDot(card.attr, mod.attrColors, mod.attrNames)} ${esc(mod.attrNames[card.attr] || card.attr)}</td></tr>
      <tr><th>稀有度</th><td><span class="rarity-stars">${'★'.repeat(card.rarity || 1)}</span>（${card.rarity}★）</td></tr>
      <tr><th>卡面种类</th><td>${esc(BANDORI_TYPE_NAMES[cType] || cType || '—')}${loading}</td></tr>
      <tr><th>日服上线</th><td>${fmtReleaseLabel(card.releaseJp || card.releaseAt)}</td></tr>
      <tr><th>国服上线</th><td>${fmtReleaseLabel(card.releaseCn)}</td></tr>
      <tr><th>资源标识</th><td class="mono">${esc(card.assetbundleName || '')}</td></tr>`;
  }
  if (mod.apiMod === 'shinycolors') {
    const idol = detail?.idol || {};
    return `
      <tr><th>卡面编号</th><td>#${card.id}</td></tr>
      <tr><th>卡面名称</th><td>${esc(card.prefix || '（未命名）')}</td></tr>
      <tr><th>角色</th><td>${esc(idol.idolName || card.characterName)}</td></tr>
      <tr><th>所属组合</th><td>${esc(card.unitName)}</td></tr>
      <tr><th>稀有度</th><td><b>${esc(card.rarity)}</b></td></tr>
      <tr><th>卡面种类</th><td>${card.cardKind === 'P' ? 'Produce（P 卡）' : 'Support（S 卡）'}</td></tr>
      <tr><th>实装日期</th><td>${fmtReleaseLabel(card.releaseAt)}</td></tr>
      <tr><th>资源编号</th><td class="mono">${esc(card.enzaId || '')}</td></tr>
      ${idol.birthday ? `<tr><th>角色生日</th><td>${esc(idol.birthday)}</td></tr>` : ''}
      ${idol.cv ? `<tr><th>声优</th><td>${esc(idol.cv)}</td></tr>` : ''}`;
  }
  // Our Notes
  const kind = card.cardKind === 'support' ? 'support' : 'card';
  const chars = detail?.characterLinks?.length
    ? detail.characterLinks.map(c => c.name).join('、')
    : card.characterName;
  const rDisp = rarityLabel({ rarity: detail?.rarity || card.rarity });
  return `
    <tr><th>卡面编号</th><td>#${card.id} · ${kind === 'support' ? '支援卡' : '角色卡'}</td></tr>
    <tr><th>卡面名称</th><td>${esc(card.prefix || '（未命名）')}</td></tr>
    <tr><th>${kind === 'support' ? '关联角色' : '角色'}</th><td>${esc(chars || '—')}</td></tr>
    <tr><th>乐队</th><td>${esc(detail?.band || card.unitName)}</td></tr>
    <tr><th>稀有度</th><td><b>${esc(rDisp)}</b></td></tr>
    ${card.attr ? `<tr><th>属性</th><td>${attrDot(card.attr, mod.attrColors, mod.attrNames)} ${esc(mod.attrNames[card.attr] || card.attr)}</td></tr>` : ''}
    <tr><th>Total Power</th><td>${esc(detail?.total ?? card.power ?? '—')}</td></tr>
    <tr><th>实装日期</th><td>${esc(detail?.release || card.releaseDate || '—')}</td></tr>
    ${detail?.servers ? `<tr><th>上线服务器</th><td>${esc(detail.servers)}</td></tr>` : ''}`;
}

function renderExtensionPanels(mod, card, detail) {
  if (mod.apiMod === 'pjsk') {
    const costumes = card.costumes || [];
    return `
    <div class="info-grid">
      <div class="card-panel skill-panel">
        <h3 style="margin-bottom:10px">⚡ 技能详情</h3>
        ${detail?.skill
          ? `<div class="sname">${esc(detail.skill.name || '—')}</div>
             <div class="sdesc">${esc(detail.skill.description || '暂无描述')}</div>`
          : `<div style="color:var(--text-3)">${detail ? '暂无技能数据' : '技能加载中…'}</div>`}
        <div class="sub-section">
          <h3 style="margin-bottom:8px">📖 卡牌剧情</h3>
          ${(detail?.episodes || []).length
            ? detail.episodes.map(e => `<div class="ep-row"><span>${esc(e.title || '')}</span><span class="muted-sm">${e.partType === 'second_part' ? '下篇' : '上篇'}</span></div>`).join('')
            : `<div class="muted-sm">${detail ? '暂无剧情' : '剧情加载中…'}</div>`}
        </div>
      </div>
      <div class="card-panel">
        <h3>👗 卡牌服装（${costumes.length} 套）</h3>
        ${costumes.length
          ? `<div class="costume-list">${costumes.map(cos => `
            <div class="costume-item">
              <img src="/api/v2/modules/pjsk/costume-thumb/${esc(cos.bodyAsset)}" loading="lazy" alt="" onerror="this.style.visibility='hidden'">
              <div>
                <div class="cname">${esc(cos.name || '未知服装')} <span class="muted-sm">· #${cos.costumeNumber}</span></div>
                <div class="csub">${(cos.partTypes || []).map(p => PJSK_PART_NAMES[p] || p).join(' / ') || '—'} · ${PJSK_SOURCE_NAMES[cos.source] || cos.source || '其他'}</div>
                ${cos.designer && cos.designer !== '-' ? `<div class="csub">设计：${esc(cos.designer)}</div>` : ''}
              </div>
            </div>`).join('')}</div>`
          : '<div class="muted-sm" style="margin-top:10px">该卡没有关联的 3D 服装</div>'}
      </div>
    </div>`;
  }

  if (mod.apiMod === 'bandori') {
    return `
    <div class="info-grid">
      <div class="card-panel skill-panel">
        <h3 style="margin-bottom:10px">⚡ 技能</h3>
        <div class="sname">${esc(detail?.skillName || card.skillName || (detail ? '—' : '加载中…'))}</div>
        ${(detail?.skillLines || []).length
          ? detail.skillLines.map(([tag, t]) => `<div class="sdesc-line ${tag === 'zh-Hans' ? '' : 'muted'}">${esc(t)}</div>`).join('')
          : `<div class="muted-sm" style="margin-top:6px">${detail ? '暂无技能描述' : '技能描述加载中…'}</div>`}
        ${detail?.gachaText ? `<div style="margin-top:12px;font-size:13.5px;color:var(--text-2)">🏷️ 招募语：${esc(detail.gachaText)}</div>` : ''}
        <div class="sub-section">
          <h3 style="margin-bottom:8px">📖 卡牌剧情</h3>
          ${(detail?.episodes || []).length
            ? detail.episodes.map(e => `
              <div class="ep-row">
                <span>${esc(e.title || '')}</span>
                <span class="muted-sm">Lv.${e.releaseLevel ?? '—'} · 属性加成 ${(e.append || []).filter(Boolean).join(' / ') || '—'}</span>
              </div>`).join('')
            : `<div class="muted-sm">${detail ? '暂无剧情' : '剧情加载中…'}</div>`}
        </div>
      </div>
      <div class="card-panel">
        <h3>ℹ️ 数据说明</h3>
        <div style="font-size:13.5px;color:var(--text-2);line-height:2">
          · 数据来源：<a href="https://bestdori.com/info/cards/${card.id}" target="_blank" rel="noopener">bestdori</a><br>
          · 区域回退链：JP 主源 → CN（bilibili 特有卡）→ EN 兜底<br>
          · 命名规范：<code>Bandori卡牌_编号_卡名_角色_突破前/后.png</code><br>
          · 属性图例：${Object.entries(mod.attrNames).map(([k, v]) => `${attrDot(k, mod.attrColors, mod.attrNames)} ${esc(v)}`).join('　')}
        </div>
      </div>
    </div>`;
  }

  if (mod.apiMod === 'shinycolors') {
    const st = detail?.status || {};
    return `
    <div class="info-grid">
      <div class="card-panel">
        <h3 style="margin-bottom:10px">📊 数值（满级）</h3>
        ${st.vocal !== undefined
          ? `<table class="info-table">
               <tr><th>Vo（Vocal）</th><td>${st.vocal ?? '—'}</td></tr>
               <tr><th>Da（Dance）</th><td>${st.dance ?? '—'}</td></tr>
               <tr><th>Vi（Visual）</th><td>${st.visual ?? '—'}</td></tr>
               <tr><th>Me（Mental）</th><td>${st.mental ?? '—'}</td></tr>
             </table>`
          : `<div class="muted-sm">${detail ? '暂无数值数据' : '数值加载中…'}</div>`}
      </div>
      <div class="card-panel">
        <h3 style="margin-bottom:10px">⚡ 技能与面板</h3>
        ${(detail?.panels || []).length
          ? detail.panels.slice(0, 8).map(p => `<div class="ep-row"><span>${esc(p.skillTitle || '')}</span><span class="muted-sm">${esc(p.skillDesc || '')}</span></div>`).join('')
          : `<div class="muted-sm">${detail ? '暂无面板技能' : '加载中…'}</div>`}
        ${(detail?.supportSkills || []).length ? `
          <div class="sub-section">
            <h3 style="margin-bottom:8px">🤝 支援技能</h3>
            ${detail.supportSkills.slice(0, 6).map(s => `<div class="ep-row"><span>${esc(s.skillName || '')}</span><span class="muted-sm">${esc(s.skillDesc || '')}</span></div>`).join('')}
          </div>` : ''}
      </div>
    </div>`;
  }

  // Our Notes
  const skills = detail?.skills || [];
  return `
  ${(detail?.pf || detail?.tc || detail?.vi) ? `
  <div class="card-panel">
    <h3 style="margin-bottom:10px">📊 三维数值</h3>
    <table class="info-table">
      <tr><th>Performance</th><td>${esc(detail.pf ?? '—')}</td></tr>
      <tr><th>Technic</th><td>${esc(detail.tc ?? '—')}</td></tr>
      <tr><th>Visual</th><td>${esc(detail.vi ?? '—')}</td></tr>
    </table>
  </div>
  <div class="section-gap"></div>` : ''}
  ${skills.length ? `
  <div class="card-panel">
    <h3 style="margin-bottom:10px">⚡ 技能等级表</h3>
    ${skills.map(s => `
      <div style="margin-bottom:16px">
        <div style="font-weight:700;margin-bottom:6px">${esc(s.name)}${s.kind ? ` <span class="muted-sm">（${esc(s.kind)}）</span>` : ''}</div>
        <table class="info-table">
          ${(s.levels || []).map(([lv, desc]) => `<tr><th>${esc(lv)}</th><td>${esc(desc)}</td></tr>`).join('')}
        </table>
      </div>`).join('')}
  </div>` : `<div class="card-panel"><div class="muted-sm">${detail ? '暂无技能详情' : '技能详情加载中…'}</div></div>`}`;
}

export async function renderDetail(app, modKey, id, kindParam = null) {
  const mod = getModule(modKey);
  const numId = Number(id);
  const kindForLookup = mod.compositeKey ? (kindParam === 'support' ? 'support' : 'card') : null;
  const favKind = kindForLookup || 'card';
  const expectedHash = location.hash;

  app.innerHTML = '<div class="loading-block">正在加载卡面详情…</div>';
  await ensureModuleIndex(mod.apiMod);
  const base = getModuleCard(mod.apiMod, numId, kindForLookup);
  if (!base) {
    app.innerHTML = `<div class="loading-block">找不到卡面 #${esc(id)}，<a href="#/${mod.routeId}/cards">返回图鉴</a></div>`;
    return;
  }

  // 同序列相邻翻页（Our Notes 在相同 card/support 序列内翻页防串台）
  const all = mod.compositeKey
    ? getModuleCards(mod.apiMod).filter(c => (c.cardKind === 'support' ? 'support' : 'card') === kindForLookup)
    : getModuleCards(mod.apiMod);
  const pos = all.findIndex(c => c.id === numId);
  const newer = pos > 0 ? all[pos - 1] : null;
  const older = pos >= 0 && pos < all.length - 1 ? all[pos + 1] : null;

  // 键盘 ← / → 翻卡
  const onKeyNav = e => {
    const tag = (e.target?.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    if (document.querySelector('[data-modal="1"]')) return;
    if (e.key === 'ArrowLeft' && newer) {
      e.preventDefault();
      location.hash = mod.detailHash(newer);
    } else if (e.key === 'ArrowRight' && older) {
      e.preventDefault();
      location.hash = mod.detailHash(older);
    }
  };
  window.addEventListener('keydown', onKeyNav);
  setPageCleanup(() => window.removeEventListener('keydown', onKeyNav));

  let latestDetail = null;

  function draw(detail) {
    if (location.hash !== expectedHash) return;
    latestDetail = detail;
    const card = { ...base, ...(detail?.card || {}) };
    const boxes = artBoxesFor(mod, card, detail);
    const fav = isFavorite(mod.apiMod, numId, favKind);
    const favEntry = getFavoriteEntry(mod.apiMod, numId, favKind);
    const groups = getGroups();

    app.innerHTML = `
    <div class="detail-head">
      <div>
        <a class="back" href="#/${mod.routeId}/cards">← 返回${esc(mod.shortName)}图鉴</a>
        <div class="page-title" style="margin-top:8px">
          ${mod.attrColors[card.attr] ? attrDot(card.attr, mod.attrColors, mod.attrNames) : ''}${esc(card.prefix || `卡面 #${card.id}`)}
        </div>
        <div class="page-desc">${esc(card.characterFullName || card.characterName || '—')} · ${esc(card.unitName || '—')} · ${esc(rarityLabel(card))} · #${card.id}</div>
      </div>
      <div class="detail-head-acts">
        ${card.spoiler ? '<span class="badge spoiler">剧透 · 未上线</span>' : ''}
        <button class="btn small ${fav ? 'primary' : ''}" id="det-fav-btn">${fav ? '★ 已收藏' : '☆ 收藏'}</button>
        ${fav ? `
        <select class="select small-sel" id="det-fav-group" title="收藏分组">
          ${groups.map(g => `<option value="${esc(g)}" ${favEntry?.group === g ? 'selected' : ''}>📁 ${esc(g)}</option>`).join('')}
        </select>` : ''}
      </div>
    </div>

    <div class="detail-pager">
      ${newer ? `<button class="btn small" onclick="location.hash='${mod.detailHash(newer)}'">← 较新 #${newer.id}</button>` : '<span></span>'}
      <span class="pager-pos">#${card.id} · 第 ${pos + 1} / ${all.length}（键盘 ← / → 翻卡）</span>
      ${older ? `<button class="btn small" onclick="location.hash='${mod.detailHash(older)}'">较旧 #${older.id} →</button>` : '<span></span>'}
    </div>

    <div class="detail-top">
      <div class="art-row ${boxes.length === 1 ? 'single' : ''}">
        ${boxes.map(b => renderArtBoxHtml(mod, card, b)).join('')}
      </div>
      <div class="card-panel">
        <h3 style="margin-bottom:10px">📋 基本资料</h3>
        <table class="info-table">${renderBasicInfoRows(mod, card, detail)}</table>
        ${detail?.flavor ? `<div class="sub-section"><div style="font-size:13px;color:var(--text-2);line-height:1.8">💬 ${esc(detail.flavor)}</div></div>` : ''}
      </div>
    </div>

    <div class="section-gap"></div>
    ${renderExtensionPanels(mod, card, detail)}`;

    // 绑定收藏与分组
    app.querySelector('#det-fav-btn').onclick = () => {
      const added = toggleFavorite(mod.apiMod, numId, favKind);
      toast(added ? '已加入收藏夹 ★' : '已取消收藏');
      draw(latestDetail);
    };
    const grpSel = app.querySelector('#det-fav-group');
    if (grpSel) {
      grpSel.onchange = () => {
        setFavoriteGroup(mod.apiMod, numId, favKind, grpSel.value);
        toast(`已移至分组「${grpSel.value}」`);
      };
    }

    // 绑定卡面放大查看
    app.querySelectorAll('.img-wrap[data-zoom-src]').forEach(el => {
      el.onclick = () => openImageModal(el.dataset.zoomSrc, el.dataset.zoomCap || '');
    });

    // 绑定下载 / 超分 / 对比滑块
    app.querySelectorAll('[data-act="dl"]').forEach(btn => {
      btn.onclick = async () => {
        if (!(await confirmCopyrightIfNeeded())) return;
        const k = btn.dataset.kind;
        try {
          const r0 = await downloadOriginal(numId, k, mod.apiMod);
          if (!r0.ok || !r0.jobId) throw new Error(r0.error || '任务创建失败');
          registerJob(r0.jobId, `${card.prefix || `卡面 #${numId}`}`, { card: numId, kind: k, mod: mod.apiMod });
          toast('已加入下载队列 · 进度见左下角「下载管理」');
        } catch (e) {
          toast(`下载失败：${e.message}`, true);
        }
      };
    });

    app.querySelectorAll('[data-act="sr"]').forEach(btn => {
      btn.onclick = async () => {
        if (!(await confirmCopyrightIfNeeded())) return;
        const k = btn.dataset.kind;
        const s = getSettings();
        const tier = s.srTarget || '4k';
        const engine = s.srEngine || 'ai';
        try {
          const r0 = await superresImage(numId, k, tier, engine, mod.apiMod);
          if (!r0.ok || !r0.jobId) throw new Error(r0.error || '超分任务创建失败');
          registerJob(r0.jobId, `${card.prefix || `卡面 #${numId}`} · ${tier.toUpperCase()}超分`, {
            type: 'superres', card: numId, kind: k, tier, engine, mod: mod.apiMod,
          });
          toast('已加入超分队列 ✨（原图缺失时自动级联下载）');
        } catch (e) {
          toast(`超分失败：${e.message}`, true);
        }
      };
    });

    app.querySelectorAll('[data-act="cmp"]').forEach(btn => {
      btn.onclick = () => openCompareModal(
        btn.dataset.orig,
        btn.dataset.sr,
        'PNG 原图',
        btn.dataset.srTag || '超分图',
      );
    });
  }

  // 两段渲染：先秒出骨架，再异步补齐详情与缓存矩阵
  draw(null);
  fetchCardDetail(mod.apiMod, numId, kindForLookup)
    .then(d => draw(d))
    .catch(() => { /* 详情拉取失败保留索引骨架 */ });
}

// 全模块下载/超分完成事件：自动刷新当前正浏览的该卡详情页（即时出现「查看原图 / ⚖️ 对比超分」）
if (!window.__cardRadarDetailListener) {
  window.__cardRadarDetailListener = true;
  window.addEventListener('dl:done', e => {
    const det = e.detail;
    if (!det) return;
    const h = location.hash;
    const hit = h.endsWith(`/${det.cardId}`) && (
      h.startsWith('#/card/')
      || h.startsWith('#/pjsk/card/')
      || h.startsWith('#/bandori/card/')
      || h.startsWith('#/sc/card/')
      || h.startsWith('#/onotes/card/')
    );
    if (hit) {
      toast(`已完成并保存：${det.filename}`);
      render();
    }
  });
  window.addEventListener('dl:error', e => {
    if (e.detail?.error) toast(`任务失败：${e.detail.error}`, true);
  });
}
