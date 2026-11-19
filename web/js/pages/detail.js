// 卡牌详情：突破前后卡面（低清预览 + 按需下载 PNG 原图 → 统一下载面板处理下载与超分）、资料、技能、服装、剧情
import { fetchCardDetail, downloadOriginal } from '../api.js?v=1.16.2';
import { render } from '../router.js?v=1.16.2';
import { ensureIndex, getCard, getCards } from '../store.js?v=1.16.2';
import { esc, attrDot, rarityLabel, fmtDate, openImageModal, toast, ATTR_NAMES } from '../ui.js?v=1.16.2';
import { registerJob } from '../dlpanel.js?v=1.16.2';

const SOURCE_NAMES = { card: '卡牌服装', shop: '商店购买', other: '其他' };
const PART_NAMES = { body: '服装', hair: '发型', head: '头饰' };

function artBoxHtml(card, kind) {
  const trained = kind === 'trained';
  const key = trained ? 'trained' : 'normal';
  const cached = card._originals?.[key];
  const disabled = trained && !card.trainable;
  const label = trained ? '突破后（特训）' : '突破前';
  const url = `/api/thumbs/${card.id}_${key}.webp`;
  const zoomKind = trained ? 'after_training' : 'normal';
  return `
  <div class="art-box">
    <div class="tag">${label}</div>
    ${disabled
      ? `<div class="img-wrap" style="cursor:default;display:grid;place-items:center;aspect-ratio:1/1;color:var(--text-3);font-size:14px">🌙 无突破卡面</div>`
      : `<div class="img-wrap" onclick="window.__zoomCard(${card.id},'${zoomKind}',${!!cached})">
          <img src="${url}" loading="lazy" alt="${label}"
               onerror="this.parentElement.innerHTML='<div style=\\'display:grid;place-items:center;aspect-ratio:1/1;color:var(--text-3);font-size:14px\\'>暂无卡面图片</div>'">
        </div>`}
    <div class="actions" id="act-${kind}">
      ${disabled
        ? '<span class="note" style="margin:0">该卡为低稀有度 / 生日卡，无突破卡面</span>'
        : `<button class="btn primary" onclick="window.__download(${card.id},'${zoomKind}')">
             <span class="spinner" style="display:none"></span>⬇️ 下载原图</button>
           ${cached
             ? `<a class="btn small" href="/api/originals/${card.id}_${zoomKind}.png" target="_blank" rel="noopener">👁 在线查看原图</a>`
             : '<span class="note">PNG 原档 · 下载与超分都在左下角「下载管理」</span>'}`}
    </div>
  </div>`;
}

function costumeItemHtml(cos) {
  return `
  <div class="costume-item">
    <img src="/api/costume-thumb/${esc(cos.bodyAsset)}.webp" loading="lazy" alt=""
         onerror="this.style.visibility='hidden'">
    <div>
      <div class="cname">${esc(cos.name || '未知服装')} <span style="color:var(--text-3);font-weight:500">· #${cos.costumeNumber}</span></div>
      <div class="csub">${(cos.partTypes || []).map(p => PART_NAMES[p] || p).join(' / ') || '—'}
        · ${SOURCE_NAMES[cos.source] || cos.source || '其他'}
        · ${(cos.gender === 'female' ? '女' : cos.gender === 'male' ? '男' : '')}</div>
      <div class="csub">${cos.designer && cos.designer !== '-' ? `设计：${esc(cos.designer)}` : ''}</div>
    </div>
  </div>`;
}

export async function renderDetail(app, id) {
  app.innerHTML = '<div class="loading-block">正在加载卡牌详情…</div>';
  await ensureIndex();
  const base = getCard(id);
  if (!base) {
    app.innerHTML = `<div class="loading-block">找不到卡牌 #${esc(id)}</div>`;
    return;
  }
  let detail = {};
  try {
    detail = await fetchCardDetail(id);
  } catch (e) { /* 详情接口失败时仍可展示索引信息 */ }
  const card = { ...base, ...(detail.card || {}), _originals: detail.originals };
  const char = detail.character || {};

  // 相邻卡牌导航（索引按 #编号 降序，前一个是更新的一张）
  const all = getCards();
  const pos = all.findIndex(c => c.id === Number(id));
  const newer = pos > 0 ? all[pos - 1] : null;
  const older = pos >= 0 && pos < all.length - 1 ? all[pos + 1] : null;

  app.innerHTML = `
  <div class="detail-head">
    <div>
      <a class="back" href="#/cards">← 返回图鉴</a>
      <div class="page-title" style="margin-top:8px">${attrDot(card.attr)}${esc(card.prefix)}</div>
      <div class="page-desc">${esc(card.characterFullName || card.characterName)} · ${esc(card.unitName)} · ${rarityLabel(card)} · #${card.id}</div>
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      ${card.spoiler ? '<span class="badge spoiler">剧透 · 未上线</span>' : ''}
      ${card.spoiler ? '' : '<span class="badge new">已上线</span>'}
    </div>
  </div>
  <div class="detail-pager">
    ${newer ? `<button class="btn small" onclick="location.hash='#/card/${newer.id}'">← 较新 #${newer.id}</button>` : '<span></span>'}
    <span class="pager-pos">#${card.id} / ${all.length}</span>
    ${older ? `<button class="btn small" onclick="location.hash='#/card/${older.id}'">较旧 #${older.id} →</button>` : '<span></span>'}
  </div>

  <div class="detail-top">
    <div class="art-row">
      ${artBoxHtml(card, 'normal')}
      ${artBoxHtml(card, 'trained')}
    </div>
    <div class="card-panel">
      <h3 style="margin-bottom:10px">📋 基本资料</h3>
      <table class="info-table">
        <tr><th>卡牌编号</th><td>#${card.id}（seq ${card.seq ?? '—'}）</td></tr>
        <tr><th>卡面名称</th><td>${esc(card.prefix)}</td></tr>
        <tr><th>角色</th><td>${esc(card.characterFullName || card.characterName)}</td></tr>
        <tr><th>所属组合</th><td>${esc(card.unitName)}</td></tr>
        <tr><th>属性</th><td>${attrDot(card.attr)} ${esc(ATTR_NAMES[card.attr] || card.attr)}</td></tr>
        <tr><th>稀有度</th><td><span class="rarity-stars">${'★'.repeat(card.rarity)}</span>（${rarityLabel(card)}）</td></tr>
        <tr><th>发布时间</th><td>${fmtDate(card.releaseAt)}</td></tr>
        <tr><th>资源标识</th><td style="font-family:Consolas,monospace;font-size:13px">${esc(card.assetbundleName || '')}</td></tr>
        ${char.birthday ? `<tr><th>角色生日</th><td>${esc(char.birthday)}</td></tr>` : ''}
      </table>
    </div>
  </div>

  <div class="section-gap"></div>
  <div class="info-grid">
    <div class="card-panel skill-panel">
      <h3 style="margin-bottom:10px">⚡ 技能详情</h3>
      ${detail.skill
        ? `<div class="sname">${esc(detail.skill.name || '—')}</div>
           <div class="sdesc">${esc(detail.skill.description || '暂无描述')}</div>`
        : '<div style="color:var(--text-3)">暂无技能数据</div>'}
      <div style="margin-top:14px;border-top:1px dashed var(--border);padding-top:12px">
        <h3 style="margin-bottom:8px">📖 卡牌剧情</h3>
        ${(detail.episodes || []).length
          ? detail.episodes.map(e => `<div class="ep-row"><span>${esc(e.title || '')}</span><span style="color:var(--text-3);font-size:12.5px">${e.partType === 'second_part' ? '下篇' : '上篇'}</span></div>`).join('')
          : '<div style="color:var(--text-3);font-size:13px">暂无剧情</div>'}
      </div>
    </div>
    <div class="card-panel">
      <h3>👗 卡牌服装（${(card.costumes || []).length} 套）</h3>
      ${(card.costumes || []).length
        ? `<div class="costume-list">${card.costumes.map(costumeItemHtml).join('')}</div>`
        : '<div style="color:var(--text-3);font-size:13.5px;margin-top:10px">该卡没有关联的 3D 服装</div>'}
    </div>
  </div>`;
}

// 挂全局动作（内联 onclick 调用）
window.__zoomCard = (id, kind, cached) =>
  openImageModal(cached
    ? `/api/originals/${id}_${kind}.png`
    : `/api/thumbs/${id}_${kind === 'after_training' ? 'trained' : 'normal'}.webp`);

/** 下载 PNG 原图：创建任务后交给左下角「下载管理」面板统一展示进度。
 *  竞速抓取（VPN 开启主源快、关闭备源快，一切以速度为准）。 */
window.__download = async (cardId, kind) => {
  try {
    const base = getCard(cardId);
    const label = `${base?.prefix || `卡面 #${cardId}`} · ${kind === 'after_training' ? '突破后' : '突破前'}`;
    const r0 = await downloadOriginal(cardId, kind);
    if (!r0.ok || !r0.jobId) throw new Error(r0.error || '任务创建失败');
    registerJob(r0.jobId, label, { card: cardId, kind });
    toast('已加入下载队列 · 进度见左下角「下载管理」');
  } catch (e) {
    toast(`下载失败：${e.message}`, true);
  }
};

/** 下载完成/失败事件：当前详情页正是该卡时给出反馈并刷新（出现「在线查看 / 超分」） */
window.addEventListener('dl:done', e => {
  const m = location.hash.match(/^#\/card\/(\d+)/);
  if (m && e.detail && Number(m[1]) === e.detail.cardId) {
    toast(`已保存到「下载」文件夹：${e.detail.filename}`);
    render();
  }
});
window.addEventListener('dl:error', e => {
  const m = location.hash.match(/^#\/card\/(\d+)/);
  if (m && e.detail && Number(m[1]) === e.detail.cardId) {
    toast(`下载失败：${e.detail.error}`, true);
  }
});

