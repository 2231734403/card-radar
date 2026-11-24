// UI 公共组件库：卡片渲染（支持批量多选 & 收藏星标）、骨架屏、灯箱、原图 vs 超分交互对比滑块、快捷键弹窗、版权确认
import {
  ATTR_COLORS, ATTR_NAMES,
  BANDORI_ATTR_COLORS, BANDORI_ATTR_NAMES,
  ONOTES_ATTR_COLORS, ONOTES_ATTR_NAMES, ONOTES_RARITY_ICON,
  getModule, cardUniqueKey,
} from './modules/registry.js?v=2.0.0';
import { getSettings, setSetting, isFavorite, toggleFavorite } from './userSettings.js?v=2.0.0';

export {
  ATTR_COLORS, ATTR_NAMES,
  BANDORI_ATTR_COLORS, BANDORI_ATTR_NAMES,
  ONOTES_ATTR_COLORS, ONOTES_ATTR_NAMES, ONOTES_RARITY_ICON,
};

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

export function attrDot(attr, colors = ATTR_COLORS, names = ATTR_NAMES) {
  if (!attr) return '';
  const c = colors[attr] || '#999';
  const n = names[attr] || attr;
  return `<span class="attr-dot" style="background:${c}" title="属性：${esc(n)}"></span>`;
}

export function attrBadge(attr) {
  if (!attr) return '';
  const n = ATTR_NAMES[attr] || attr;
  return `<img class="attr-badge" src="/img/attr/attr_${esc(attr)}.png?v=3" alt="${esc(n)}"
           title="属性：${esc(n)}" draggable="false" loading="lazy">`;
}

export function rarityStars(n) {
  return `<span class="stars">${'<span>★</span>'.repeat(Number(n) || 1)}</span>`;
}

export function spoilerTag(isSpoiler) {
  return isSpoiler ? '<span class="spoiler-tag">剧透</span>' : '';
}

export function fmtDate(ms) {
  if (!ms) return '未知';
  const d = new Date(Number.isNaN(Number(ms)) ? ms : Number(ms));
  if (Number.isNaN(d.getTime())) return String(ms);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function fmtReleaseLabel(ts) {
  if (!ts) return '未上线';
  const d = new Date(Number(ts));
  if (Number.isNaN(d.getTime())) return '未知';
  if (d.getFullYear() > 2035) return '未公布';
  return fmtDate(ts);
}

export function rarityLabel(card) {
  if (card.rarityType === 'rarity_birthday') return '生日';
  if (typeof card.rarity === 'number' || /^\d+$/.test(String(card.rarity))) return `${card.rarity}★`;
  return String(card.rarity === '特殊' ? 'EX' : card.rarity || '—');
}

export function toast(msg, isError = false) {
  let el = document.querySelector('.toast');
  if (!el) {
    el = document.createElement('div');
    el.className = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.toggle('error', isError);
  requestAnimationFrame(() => el.classList.add('show'));
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 3600);
}

/** 骨架屏加载网格（替代纯文字「正在加载」） */
export function skeletonGridHtml(count = 12) {
  return `<div class="card-grid skeleton-grid">${Array.from({ length: count }, () => `
    <div class="skel-card">
      <div class="skel-thumb shimmer"></div>
      <div class="skel-meta">
        <div class="skel-line w80 shimmer"></div>
        <div class="skel-line w50 shimmer"></div>
      </div>
    </div>`).join('')}</div>`;
}

/** 简易图片放大弹窗（支持 Esc / 点击任意处关闭） */
export function openImageModal(src, caption = '') {
  closeTopModal();
  const mask = document.createElement('div');
  mask.className = 'modal-mask';
  mask.dataset.modal = '1';
  mask.innerHTML = `
    <div class="modal-img-stage">
      <img src="${esc(src)}" alt="预览">
      ${caption ? `<div class="modal-caption">${esc(caption)}</div>` : ''}
    </div>
    <span class="close-hint">点击空白处或按 Esc 关闭</span>`;
  mask.addEventListener('click', e => {
    if (e.target === mask || e.target.tagName === 'IMG' || e.target.classList.contains('close-hint')) {
      mask.remove();
    }
  });
  document.body.appendChild(mask);
}

/** 原图 vs 超分交互对比滑块（支持鼠标/触摸拖拽与左右方向键微调） */
export function openCompareModal(origUrl, srUrl, labelOrig = '原图', labelSr = '超分图') {
  closeTopModal();
  const mask = document.createElement('div');
  mask.className = 'modal-mask compare-modal';
  mask.dataset.modal = '1';
  mask.innerHTML = `
    <div class="compare-shell" role="dialog" aria-label="画质对比">
      <div class="compare-head">
        <div>
          <b>⚖️ 原图 vs 超分画质对比</b>
          <span class="compare-sub">拖动中间滑块或按 ← / → 微调分割线</span>
        </div>
        <div class="compare-head-acts">
          <a class="btn small" href="${esc(origUrl)}" target="_blank" rel="noopener">原图新窗</a>
          <a class="btn small primary" href="${esc(srUrl)}" target="_blank" rel="noopener">超分新窗</a>
          <button class="btn small" id="cmp-close">✕ 关闭</button>
        </div>
      </div>
      <div class="compare-stage" id="cmp-stage">
        <img class="compare-img compare-base" src="${esc(origUrl)}" alt="${esc(labelOrig)}" draggable="false">
        <div class="compare-after-wrap" id="cmp-after" style="clip-path: inset(0 0 0 50%)">
          <img class="compare-img" src="${esc(srUrl)}" alt="${esc(labelSr)}" draggable="false">
        </div>
        <span class="compare-tag left">${esc(labelOrig)}</span>
        <span class="compare-tag right">${esc(labelSr)}</span>
        <div class="compare-divider" id="cmp-divider" style="left:50%">
          <div class="compare-knob">↔</div>
        </div>
      </div>
    </div>`;

  const stage = mask.querySelector('#cmp-stage');
  const after = mask.querySelector('#cmp-after');
  const divider = mask.querySelector('#cmp-divider');
  let pct = 50;

  const setPct = v => {
    pct = Math.max(0, Math.min(100, v));
    after.style.clipPath = `inset(0 0 0 ${pct}%)`;
    divider.style.left = `${pct}%`;
  };

  const updateFromClientX = clientX => {
    const rect = stage.getBoundingClientRect();
    if (!rect.width) return;
    setPct(((clientX - rect.left) / rect.width) * 100);
  };

  let dragging = false;
  stage.addEventListener('pointerdown', e => {
    dragging = true;
    stage.setPointerCapture(e.pointerId);
    updateFromClientX(e.clientX);
  });
  stage.addEventListener('pointermove', e => {
    if (dragging) updateFromClientX(e.clientX);
  });
  stage.addEventListener('pointerup', () => { dragging = false; });

  const onKey = e => {
    if (e.key === 'ArrowLeft') { e.preventDefault(); setPct(pct - 5); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); setPct(pct + 5); }
    else if (e.key === 'Escape') { cleanup(); }
  };
  const cleanup = () => {
    window.removeEventListener('keydown', onKey);
    mask.remove();
  };

  window.addEventListener('keydown', onKey);
  mask.querySelector('#cmp-close').onclick = cleanup;
  mask.addEventListener('click', e => { if (e.target === mask) cleanup(); });
  document.body.appendChild(mask);
}

/** 首次下载/导出前的「仅个人学习研究使用」轻量二次确认（确认一次后记住） */
export function confirmCopyrightIfNeeded() {
  if (getSettings().copyrightAck) return Promise.resolve(true);
  return new Promise(resolve => {
    const mask = document.createElement('div');
    mask.className = 'modal-mask';
    mask.dataset.modal = '1';
    mask.innerHTML = `
      <div class="dialog-card">
        <h3>📜 素材使用提示</h3>
        <p>卡牌雷达抓取的卡面图像与游戏资料版权均归 <b>SEGA / Colorful Palette / Bushiroad / Craft Egg / Bandai Namco</b> 及相关权利方所有。</p>
        <p>下载的原图与超分图像<b>仅限个人欣赏、学习与研究用途</b>，请勿二次公开分发或用于任何商业行为。</p>
        <div class="dialog-actions">
          <button class="btn" id="cr-cancel">取消</button>
          <button class="btn primary" id="cr-ok">我已了解，继续下载</button>
        </div>
      </div>`;
    const finish = ok => {
      if (ok) setSetting('copyrightAck', true);
      mask.remove();
      resolve(ok);
    };
    mask.querySelector('#cr-cancel').onclick = () => finish(false);
    mask.querySelector('#cr-ok').onclick = () => finish(true);
    mask.addEventListener('click', e => { if (e.target === mask) finish(false); });
    document.body.appendChild(mask);
  });
}

/** 快捷键帮助弹窗 */
export function openShortcutsModal() {
  closeTopModal();
  const mask = document.createElement('div');
  mask.className = 'modal-mask';
  mask.dataset.modal = '1';
  mask.innerHTML = `
    <div class="dialog-card">
      <h3>⌨️ 键盘快捷键</h3>
      <div class="kbd-list">
        <div class="kbd-row"><span>聚焦图鉴搜索框</span><kbd>/</kbd></div>
        <div class="kbd-row"><span>详情页切换较新 / 较旧卡面</span><span><kbd>←</kbd> / <kbd>→</kbd></span></div>
        <div class="kbd-row"><span>切换浅色 / 深色外观</span><kbd>D</kbd></div>
        <div class="kbd-row"><span>打开本快捷键帮助</span><kbd>?</kbd></div>
        <div class="kbd-row"><span>关闭弹窗或清空搜索聚焦</span><kbd>Esc</kbd></div>
      </div>
      <div class="dialog-actions">
        <button class="btn primary" id="kbd-ok">知道了</button>
      </div>
    </div>`;
  mask.querySelector('#kbd-ok').onclick = () => mask.remove();
  mask.addEventListener('click', e => { if (e.target === mask) mask.remove(); });
  document.body.appendChild(mask);
}

export function closeTopModal() {
  const modals = document.querySelectorAll('[data-modal="1"]');
  if (modals.length) {
    modals[modals.length - 1].remove();
    return true;
  }
  return false;
}

/** 统一网格卡片渲染（支持普通浏览 / 批量选择模式 / 一键收藏星标）
 *  严守 T17：thumb-wrap 内 img 使用 absolute inset:0 锁死 1:1 比例 */
export function cardCellHtml(c, modKey = 'pjsk', opts = {}) {
  const mod = getModule(modKey);
  const apiMod = mod.apiMod;
  const bandori = apiMod === 'bandori';
  const shiny = apiMod === 'shinycolors';
  const onotes = apiMod === 'onotes';
  const kindForFav = onotes ? (c.cardKind === 'support' ? 'support' : 'card') : 'card';
  const key = cardUniqueKey(apiMod, c);
  const fav = isFavorite(apiMod, c.id, kindForFav);
  const batchMode = Boolean(opts.batchMode);
  const selected = Boolean(opts.selectedSet && opts.selectedSet.has(key));

  const thumb = mod.thumbUrl(c);
  const fallback = mod.fallbackThumbUrl(c);
  const hash = mod.detailHash(c);

  const badge = bandori
    ? `<img class="attr-badge" src="/img/attr/battr_${esc(c.attr)}.png?v=1" alt="${esc(BANDORI_ATTR_NAMES[c.attr] || c.attr)}"
             title="属性：${esc(BANDORI_ATTR_NAMES[c.attr] || c.attr)}" draggable="false" loading="lazy">`
    : (shiny || onotes ? '' : attrBadge(c.attr));

  const onotesRarityIcon = ONOTES_RARITY_ICON[String(c.rarity)];
  const onotesBadges = onotes ? `
    <div class="cell-badges">
      ${c.attr ? `<img class="onotes-attr" src="/img/attr/onotes_attr_${esc(c.attr)}.png" alt="${esc(ONOTES_ATTR_NAMES[c.attr] || c.attr)}"
        title="属性：${esc(ONOTES_ATTR_NAMES[c.attr] || c.attr)}" draggable="false" loading="lazy">` : ''}
    </div>` : '';
  const onotesRarity = onotes && onotesRarityIcon ? `
    <img class="onotes-rarity" src="/img/attr/onotes_rarity_${esc(onotesRarityIcon)}.png" alt="${esc(c.rarity)}"
         title="稀有度：${esc(c.rarity)}" draggable="false" loading="lazy">` : '';

  const checkHtml = batchMode
    ? `<span class="cell-check ${selected ? 'checked' : ''}">${selected ? '✓' : ''}</span>`
    : `<button class="cell-fav ${fav ? 'on' : ''}" data-fav-mod="${esc(apiMod)}" data-fav-id="${c.id}"
         data-fav-kind="${esc(kindForFav)}" title="${fav ? '取消收藏' : '加入收藏'}"
         onclick="window.__toggleCardFav(this);event.stopPropagation()">${fav ? '★' : '☆'}</button>`;

  const clickAttr = batchMode
    ? `data-batch-key="${esc(key)}" data-card-id="${c.id}" data-mod="${esc(apiMod)}" data-kind="${esc(mod.defaultArtKind(c))}"`
    : `onclick="location.hash='${hash}'"`;

  return `
  <div class="card-cell ${batchMode ? 'batch-item' : ''} ${selected ? 'selected' : ''}" ${clickAttr}>
    <div class="thumb-wrap">
      <img src="${thumb}" loading="lazy" alt="${esc(c.prefix)}"
           onerror="if(!this.dataset.fb){this.dataset.fb=1;this.src='${fallback}'}else{this.onerror=null;this.style.display='none';this.parentElement.classList.add('no-thumb')}">
      ${badge}
      ${spoilerTag(c.spoiler)}
      ${onotes ? onotesBadges + onotesRarity
        : shiny ? `<span class="rarity-badge rb-${esc(String(c.rarity).toLowerCase())}"><b>${esc(c.rarity)}</b></span>`
        : rarityStars(c.rarity)}
      ${checkHtml}
    </div>
    <div class="meta">
      <div class="prefix" title="${esc(c.prefix)}">${esc(c.prefix)}</div>
      <div class="sub">
        <span>${esc(c.characterName || '—')}</span>
        <span>#${c.id}</span>
      </div>
    </div>
  </div>`;
}

/** 统一列表行视图 */
export function cardRowHtml(c, modKey = 'pjsk', opts = {}) {
  const mod = getModule(modKey);
  const apiMod = mod.apiMod;
  const onotes = apiMod === 'onotes';
  const kindForFav = onotes ? (c.cardKind === 'support' ? 'support' : 'card') : 'card';
  const key = cardUniqueKey(apiMod, c);
  const fav = isFavorite(apiMod, c.id, kindForFav);
  const batchMode = Boolean(opts.batchMode);
  const selected = Boolean(opts.selectedSet && opts.selectedSet.has(key));
  const thumb = mod.thumbUrl(c, onotes ? kindForFav : 'normal');
  const hash = mod.detailHash(c);
  const clickAttr = batchMode
    ? `data-batch-key="${esc(key)}" data-card-id="${c.id}" data-mod="${esc(apiMod)}" data-kind="${esc(mod.defaultArtKind(c))}"`
    : `onclick="location.hash='${hash}'"`;

  return `
  <div class="card-cell ${batchMode ? 'batch-item' : ''} ${selected ? 'selected' : ''}" ${clickAttr}>
    <div class="thumb-wrap">
      <img src="${thumb}" loading="lazy" alt="${esc(c.prefix)}"
           onerror="this.style.display='none';this.parentElement.classList.add('no-thumb')">
      ${batchMode ? `<span class="cell-check ${selected ? 'checked' : ''}">${selected ? '✓' : ''}</span>` : ''}
    </div>
    <div class="meta">
      <div class="prefix">
        ${attrDot(c.attr, mod.attrColors, mod.attrNames)}${esc(c.prefix)}
        ${c.spoiler ? '<span class="badge spoiler">剧透</span>' : ''}
      </div>
      <div class="sub">
        <span>${esc(c.characterName || '—')}</span>
        <span>${esc(c.unitName || '')}</span>
        <span>${esc(rarityLabel(c))}</span>
        <span>#${c.id}</span>
        ${!batchMode ? `<button class="btn tiny fav-inline ${fav ? 'on' : ''}"
          data-fav-mod="${esc(apiMod)}" data-fav-id="${c.id}" data-fav-kind="${esc(kindForFav)}"
          onclick="window.__toggleCardFav(this);event.stopPropagation()">${fav ? '★ 已收藏' : '☆ 收藏'}</button>` : ''}
      </div>
    </div>
  </div>`;
}

// 挂载全局卡片收藏切换（内联 onclick 零闪烁更新）
window.__toggleCardFav = btn => {
  const mod = btn.dataset.favMod;
  const id = Number(btn.dataset.favId);
  const kind = btn.dataset.favKind;
  const added = toggleFavorite(mod, id, kind);
  btn.classList.toggle('on', added);
  if (btn.classList.contains('fav-inline')) {
    btn.textContent = added ? '★ 已收藏' : '☆ 收藏';
  } else {
    btn.textContent = added ? '★' : '☆';
    btn.title = added ? '取消收藏' : '加入收藏';
  }
  toast(added ? '已加入收藏夹 ★' : '已从收藏夹移除');
};
