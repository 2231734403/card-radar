// UI 公共组件与常量
export const ATTR_COLORS = {
  cool: '#4f8ef7',
  cute: '#f76fa4',
  happy: '#f7a94f',
  pure: '#55c96e',
  mysterious: '#9b6ef7',
};
// 属性用原名（Cool/Cute/Happy/Pure/Mysterious），不翻译，以颜色区分
export const ATTR_NAMES = {
  cool: 'Cool', cute: 'Cute', happy: 'Happy', pure: 'Pure', mysterious: 'Mysterious',
};

// 邦多利属性（官方配色：红/蓝/绿/橙）
export const BANDORI_ATTR_COLORS = {
  powerful: '#ff396a',
  cool: '#49c1e8',
  pure: '#5ee282',
  happy: '#f6a231',
};
export const BANDORI_ATTR_NAMES = {
  powerful: 'Powerful', cool: 'Cool', pure: 'Pure', happy: 'Happy',
};

// Our Notes 属性（官方配色 + 官方原名，ja 页口径：紅赤/翡翠/紫苑/紺碧/山吹）
export const ONOTES_ATTR_COLORS = {
  Red: '#ff396a', Blue: '#49c1e8', Green: '#5ee282',
  Yellow: '#f6c231', Purple: '#9b6ef7',
};
export const ONOTES_ATTR_NAMES = {
  Red: '紅赤', Blue: '紺碧', Green: '翡翠', Yellow: '山吹', Purple: '紫苑',
};
// 稀有度图标文件名（特殊档官方图标是 SP_CardRarityIcon_EX，文件名 EX）
export const ONOTES_RARITY_ICON = {
  R: 'R', SR: 'SR', SSR: 'SSR', BD: 'BD', 特殊: 'EX',
};

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

export function attrDot(attr, colors = ATTR_COLORS, names = ATTR_NAMES) {
  const c = colors[attr] || '#999';
  const n = names[attr] || attr;
  return `<span class="attr-dot" style="background:${c}" title="属性：${esc(n)}"></span>`;
}

/** 缩略图左上角的属性角标（官网同款图案图标：星/花/心/月/蝶） */
export function attrBadge(attr) {
  const n = ATTR_NAMES[attr] || attr;
  return `<img class="attr-badge" src="/img/attr/attr_${esc(attr)}.png?v=3" alt="${esc(n)}"
           title="属性：${esc(n)}" draggable="false" loading="lazy">`;
}

export function rarityStars(n) {
  return `<span class="stars">${'<span>★</span>'.repeat(n || 1)}</span>`;
}

export function spoilerTag(isSpoiler) {
  return isSpoiler ? '<span class="spoiler-tag">剧透</span>' : '';
}

export function fmtDate(ms) {
  if (!ms) return '未知';
  // 兼容毫秒时间戳与 ISO 字符串（bandori state.lastRun 是 ISO）
  const d = new Date(isNaN(Number(ms)) ? ms : Number(ms));
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** 稀有度显示名（生日卡特殊） */
export function rarityLabel(card) {
  return card.rarityType === 'rarity_birthday' ? '生日' : `${card.rarity}★`;
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

/** 简易图片放大弹窗 */
export function openImageModal(src) {
  const mask = document.createElement('div');
  mask.className = 'modal-mask';
  mask.innerHTML = `<img src="${esc(src)}" alt="预览"><span class="close-hint">点击任意处关闭</span>`;
  mask.addEventListener('click', () => mask.remove());
  document.body.appendChild(mask);
}

/** 图鉴网格卡片（首页与图鉴页共用）。3★/4★ 用特训后卡面，加载失败回退突破前。
 *  mod: pjsk（官网图案角标 + #/card/:id）| bandori（图案角标）| onotes（属性色 pill + 稀有度白胶囊）
 *  | shinycolors（稀有度白胶囊） */
export function cardCellHtml(c, mod = 'pjsk') {
  const bandori = mod === 'bandori';
  const shiny = mod === 'shinycolors';
  const onotes = mod === 'onotes';
  const dir = bandori ? '/api/bandori/thumbs'
    : shiny ? '/api/shinycolors/thumbs'
    : onotes ? '/api/onotes/thumbs' : '/api/thumbs';
  const thumb = onotes
    ? `${dir}/${c.id}_${c.cardKind === 'support' ? 'support' : 'card'}.webp`
    : (c.trainable ? `${dir}/${c.id}_trained.webp` : `${dir}/${c.id}_normal.webp`);
  const fallback = onotes ? thumb : `${dir}/${c.id}_normal.webp`;
  // Our Notes 角色卡/支援卡 ID 序列重叠 → 详情路由必须带 kind
  const onotesKind = c.cardKind === 'support' ? 'support' : 'card';
  const hash = bandori ? `#/bandori/card/${c.id}`
    : shiny ? `#/sc/card/${c.id}`
    : onotes ? `#/onotes/card/${onotesKind}/${c.id}` : `#/card/${c.id}`;
  const badge = bandori
    ? `<img class="attr-badge" src="/img/attr/battr_${esc(c.attr)}.png?v=1" alt="${esc(BANDORI_ATTR_NAMES[c.attr] || c.attr)}"
             title="属性：${esc(BANDORI_ATTR_NAMES[c.attr] || c.attr)}" draggable="false" loading="lazy">`
    : (shiny || onotes ? '' : attrBadge(c.attr));
  // Our Notes：左上角属性图标（资源站同款）+ 右上角稀有度艺术字（与左上角分开）。
  // 稀有度图标文件名经 ONOTES_RARITY_ICON 映射（特殊→EX）
  const onotesRarityIcon = ONOTES_RARITY_ICON[String(c.rarity)];
  const onotesBadges = onotes ? `
    <div class="cell-badges">
      ${c.attr ? `<img class="onotes-attr" src="/img/attr/onotes_attr_${esc(c.attr)}.png" alt="${esc(ONOTES_ATTR_NAMES[c.attr] || c.attr)}"
        title="属性：${esc(ONOTES_ATTR_NAMES[c.attr] || c.attr)}" draggable="false" loading="lazy">` : ''}
    </div>` : '';
  const onotesRarity = onotes && onotesRarityIcon ? `
    <img class="onotes-rarity" src="/img/attr/onotes_rarity_${esc(onotesRarityIcon)}.png" alt="${esc(c.rarity)}"
         title="稀有度：${esc(c.rarity)}" draggable="false" loading="lazy">` : '';
  return `
  <div class="card-cell" onclick="location.hash='${hash}'">
    <div class="thumb-wrap">
      <img src="${thumb}" loading="lazy" alt="${esc(c.prefix)}"
           onerror="if(!this.dataset.fb){this.dataset.fb=1;this.src='${fallback}'}else{this.onerror=null;this.style.display='none';this.parentElement.classList.add('no-thumb')}">
      ${badge}
      ${spoilerTag(c.spoiler)}
      ${onotes ? onotesBadges + onotesRarity
        : shiny ? `<span class="rarity-badge rb-${esc(String(c.rarity).toLowerCase())}"><b>${esc(c.rarity)}</b></span>`
        : rarityStars(c.rarity)}
    </div>
    <div class="meta">
      <div class="prefix" title="${esc(c.prefix)}">${esc(c.prefix)}</div>
      <div class="sub">
        <span>${esc(c.characterName)}</span>
        <span>#${c.id}</span>
      </div>
    </div>
  </div>`;
}
