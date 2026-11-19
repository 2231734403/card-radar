// 游戏模块页面：邦多利 / Our Notes / 闪耀色彩（真数据）。
// 各模块首页/详情页按 pjsk 模块同款格式渲染（下载/超分走统一下载面板）。
import { esc, cardCellHtml, attrDot, fmtDate, openImageModal, toast,
         BANDORI_ATTR_COLORS, BANDORI_ATTR_NAMES, ONOTES_ATTR_COLORS, ONOTES_ATTR_NAMES } from '../ui.js?v=1.16.2';
import { fetchBandoriStatus, fetchBandoriCardDetail, downloadOriginal,
         fetchShinyStatus, fetchShinyCardDetail,
         fetchOnotesStatus, fetchOnotesCardDetail } from '../api.js?v=1.16.2';
import { ensureBandoriIndex, getBandoriCards, getBandoriCard, getBandoriUpdatedAt,
         ensureShinyIndex, getShinyCards, getShinyCard, getShinyUpdatedAt,
         ensureOnotesIndex, getOnotesCards, getOnotesCard, getOnotesUpdatedAt } from '../store.js?v=1.16.2';
import { registerJob } from '../dlpanel.js?v=1.16.2';

// 闪耀色彩占位（数据未接入）
const SC_META = {
  name: '闪耀色彩卡面', icon: '✨',
  desc: 'SHINY COLORS（闪耀色彩）· 卡面数据模块',
  points: [
    '每两周自动同步官方公开数据源',
    '图鉴浏览 / 筛选 / 原图下载（规范命名）',
    '与 PJSK 相同的 AI 超分与下载面板体验',
  ],
};

/** 闪耀色彩占位首页 */
export function renderModuleHome(app) {
  const m = SC_META;
  app.innerHTML = `
  <div class="hero">
    <h1>${esc(m.name)} <span class="hl">· 卡牌雷达</span></h1>
    <p>${esc(m.desc)}。模块框架已就绪，数据接入后即可上线。</p>
    <div class="actions">
      <button class="btn primary" onclick="location.hash='#/sc/cards'">🃏 卡面图鉴（筹备中）</button>
      <button class="btn" onclick="location.hash='#/about'">📅 通用策略说明</button>
    </div>
  </div>
  <div class="stats">
    <div class="stat-tile"><div class="label">模块状态</div><div class="value" style="font-size:22px">🏗️ 筹备中</div><div class="hint">界面已就绪 · 数据爬取待接入</div></div>
    <div class="stat-tile"><div class="label">卡面总数</div><div class="value">—</div><div class="hint">接入数据源后显示</div></div>
    <div class="stat-tile"><div class="label">主题配色</div><div class="value" style="font-size:22px">${m.icon}</div><div class="hint">随模块切换 · 全站顺滑过渡</div></div>
    <div class="stat-tile"><div class="label">预计能力</div><div class="value" style="font-size:22px">📷 ✨</div><div class="hint">原图下载 · AI 超分 · 中文显示</div></div>
  </div>
  <div class="section-gap"></div>
  <div class="card-panel">
    <h3 style="margin-bottom:10px">🚧 该模块将提供</h3>
    <div style="font-size:14px;color:var(--text-2);line-height:2.1">
      ${m.points.map(p => `· ${esc(p)}<br>`).join('')}
    </div>
  </div>`;
}

/** 闪耀色彩占位图鉴页 */
export function renderModuleCards(app) {
  const m = SC_META;
  const chips = ['属性', '稀有度', '角色', '排序'];
  app.innerHTML = `
  <div class="detail-head">
    <div>
      <div class="page-title">${esc(m.name)} · <span class="hl">卡面图鉴</span></div>
      <div class="page-desc">${esc(m.desc)} —— 图鉴框架已就绪，等待数据接入</div>
    </div>
  </div>
  <div class="section-gap"></div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
    ${chips.map(c => `<span style="background:var(--surface-2);color:var(--text-3);padding:8px 16px;border-radius:99px;font-size:13px;font-weight:600">${c}</span>`).join('')}
    <span style="font-size:12.5px;color:var(--text-3)">筛选器将在数据接入后启用</span>
  </div>
  <div class="section-gap"></div>
  <div class="placeholder-hero" style="margin-top:6px">
    <div class="big">${m.icon}</div>
    <h2>数据筹备中 · 敬请期待</h2>
    <p>卡面爬取模块尚未接入该游戏的数据源；界面与交互已按统一风格就绪，<br>数据一到即可浏览、下载原图与 AI 超分。</p>
    <div class="section-gap"></div>
    <button class="btn primary" onclick="location.hash='#/sc/home'">返回${esc(m.name)}首页 →</button>
  </div>`;
}

/** 邦多利首页：与 pjsk 首页同款布局（hero + 统计 + 最新卡面网格） */
export async function renderBandoriHome(app) {
  app.innerHTML = '<div class="loading-block">正在加载邦多利卡面…</div>';
  try {
    const [, st] = await Promise.all([
      ensureBandoriIndex(),
      fetchBandoriStatus().catch(() => null),
    ]);
    const cards = getBandoriCards();
    if (!cards.length) {
      app.innerHTML = `
      <div class="placeholder-hero">
        <div class="big">📦</div>
        <h2>还没有邦多利卡面数据</h2>
        <p>请先运行项目里的 <code>scripts\\run_bandori_scrape.cmd</code> 完成首次抓取，然后刷新本页面。</p>
      </div>`;
      return;
    }
    // 「最新」按发布时间排序（编号顺序≠发布顺序：未实装/复刻卡会插队）
    const latest = [...cards]
      .sort((a, b) => (b.releaseAt || 0) - (a.releaseAt || 0))
      .slice(0, 12);
    const maxId = cards.length ? Math.max(...cards.map(c => c.id)) : 0;
    const updated = getBandoriUpdatedAt() ? fmtDate(getBandoriUpdatedAt()) : '—';
    const cnt = st?.lastCounts;
    const cntHint = cnt
      ? `（新下载 ${cnt.downloaded ?? 0} · 跳过 ${cnt.skipped ?? 0}${cnt.failed ? ` · 失败 ${cnt.failed}` : ''}）`
      : '增量模式 · 已有卡面自动跳过';
    const partial = st?.lastResult === 'partial';

    app.innerHTML = `
  <div class="hero">
    <h1>卡牌雷达 · <span class="hl">邦多利卡面图鉴</span></h1>
    <p>每两周自动同步 BanG Dream!（邦多利）的卡面数据库（周一 09:20）：低清预览常驻本地，PNG 原图点击下载时才抓取，数据来源 bestdori～</p>
    <div class="actions">
      <button class="btn primary" onclick="location.hash='#/bandori/cards'">🗂️ 浏览全部卡面</button>
      <button class="btn" onclick="location.hash='#/about'">📅 更新与存储策略</button>
    </div>
  </div>
  <div class="stats">
    <div class="stat-tile"><div class="label">卡面总数</div><div class="value">${cards.length}</div><div class="hint">bestdori 数据 · 自动更新 · 中文显示</div></div>
    <div class="stat-tile"><div class="label">最新卡面</div><div class="value">#${maxId}</div><div class="hint">${esc(cards[0]?.prefix || '')}</div></div>
    <div class="stat-tile"><div class="label">上次抓取</div><div class="value" style="font-size:16px;line-height:1.4">${st?.lastRun ? fmtDate(st.lastRun) : '—'}</div><div class="hint">${partial ? '<span style="color:#b45309">⚠ 部分图片失败，详见 data/logs/bandori_scrape.log</span>　' : ''}${cntHint}</div></div>
    <div class="stat-tile"><div class="label">下次自动抓取</div><div class="value" style="font-size:16px;line-height:1.4">每两周 · 周一 09:20</div><div class="hint">Windows 计划任务 · 失败会弹窗提醒</div></div>
  </div>
  <div class="home-sec-head">
    <h2>🆕 最新卡面</h2>
    <a href="#/bandori/cards">查看全部 →</a>
  </div>
  <div class="card-grid">${latest.map(c => cardCellHtml(c, 'bandori')).join('')}</div>
  <div class="section-gap"></div>
  <div class="card-panel" style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
    <span style="font-size:22px">🎸</span>
    <div style="flex:1;min-width:240px">
      <div style="font-weight:700">镜像服务运行中${st ? '' : ''}</div>
      <div style="font-size:12.5px;color:var(--text-3)">数据目录 data/bandori · 缩略图 ${cards.length} 组 · 原图按需抓取</div>
    </div>
    <button class="btn small" onclick="location.hash='#/about'">了解更多</button>
  </div>`;
  } catch (e) {
    app.innerHTML = `
    <div class="placeholder-hero">
      <div class="big">🔌</div>
      <h2>数据服务未就绪</h2>
      <p>${esc(e.message)}。请运行 <code>scripts\\verify_setup.cmd</code> 自检修复。</p>
    </div>`;
  }
}

const TYPE_NAMES = {
  permanent: '常驻', event: '活动', limited: '限定', dreamfes: 'Dreamfes',
  campaign: '活动奖励', birthday: '生日', kirafes: 'KiraFes', special: '特殊',
  initial: '初始', others: '其他',
};

function bdArtBoxHtml(card, kind, cached) {
  const trained = kind === 'trained';
  const disabled = trained && !card.trainable;
  const label = trained ? '突破后（特训）' : '突破前';
  const url = `/api/bandori/thumbs/${card.id}_${kind}.webp`;
  const zoomKind = trained ? 'after_training' : 'normal';
  return `
  <div class="art-box">
    <div class="tag">${label}</div>
    ${disabled
      ? `<div class="img-wrap" style="cursor:default;display:grid;place-items:center;aspect-ratio:1/1;color:var(--text-3);font-size:14px">🌙 无突破卡面</div>`
      : `<div class="img-wrap" onclick="window.__bdZoomCard(${card.id},'${zoomKind}',${!!cached})">
          <img src="${url}" loading="lazy" alt="${label}"
               onerror="this.parentElement.innerHTML='<div style=\\'display:grid;place-items:center;aspect-ratio:1/1;color:var(--text-3);font-size:14px\\'>暂无卡面图片</div>'">
        </div>`}
    <div class="actions" id="bd-act-${kind}">
      ${disabled
        ? '<span class="note" style="margin:0">该卡为低稀有度卡面，无突破卡面</span>'
        : `<button class="btn primary" onclick="window.__bdDownload(${card.id},'${zoomKind}')">
             <span class="spinner" style="display:none"></span>⬇️ 下载原图</button>
           ${cached
             ? `<a class="btn small" href="/api/bandori/originals/${card.id}_${zoomKind}.png" target="_blank" rel="noopener">👁 在线查看原图</a>`
             : '<span class="note">PNG 原档 · 下载与超分都在左下角「下载管理」</span>'}`}
    </div>
  </div>`;
}

/** 邦多利卡面详情页：与 pjsk 详情同款布局。
 *  两段渲染：先按 index 数据立即出完整框架（打开即进，不等网络），
 *  详情接口（本地缓存命中秒回 / 未命中走 bestdori）返回后原地补齐技能/剧情/卡种。 */
export async function renderBandoriDetail(app, id) {
  app.innerHTML = '<div class="loading-block">正在加载卡面详情…</div>';
  await ensureBandoriIndex();
  const base = getBandoriCard(id);
  if (!base) {
    app.innerHTML = `<div class="loading-block">找不到卡面 #${esc(id)}</div>`;
    return;
  }
  const hashAt = `#/bandori/card/${id}`;
  const draw = d => {
    // 用户已切走（其它卡/页面）时不再覆盖 DOM
    if (location.hash === hashAt) renderBandoriDetailView(app, id, base, d);
  };
  draw(null); // 立即渲染骨架
  fetchBandoriCardDetail(id)
    .then(d => draw(d))
    .catch(() => { /* 详情失败保持骨架：index 数据已可用 */ });
}

function renderBandoriDetailView(app, id, base, detail) {
  const card = { ...base, ...(detail?.card || {}), _originals: detail?.originals || null };
  const colors = BANDORI_ATTR_COLORS;
  const names = BANDORI_ATTR_NAMES;

  // 相邻卡面导航
  const all = getBandoriCards();
  const pos = all.findIndex(c => c.id === Number(id));
  const newer = pos > 0 ? all[pos - 1] : null;
  const older = pos >= 0 && pos < all.length - 1 ? all[pos + 1] : null;

  // 双服上线时间（JP/CN）：bestdori releasedAt 数组序 [日,英,台,国,韩]
  // 2100 年占位时间戳 → 「未公布」；国服未上线明确标注
  const relLabel = (ts) => {
    if (!ts) return '未上线';
    const y = new Date(Number(ts)).getFullYear();
    return y > 2035 ? '未公布' : fmtDate(ts);
  };
  const loadingHint = detail ? '' : '<span style="color:var(--text-3)">（详情加载中…）</span>';

  app.innerHTML = `
  <div class="detail-head">
    <div>
      <a class="back" href="#/bandori/cards">← 返回图鉴</a>
      <div class="page-title" style="margin-top:8px">${attrDot(card.attr, colors, names)}${esc(card.prefix || `卡面 #${card.id}`)}</div>
      <div class="page-desc">${esc(card.characterName)} · ${esc(card.unitName)} · ${card.rarity}★ · #${card.id}</div>
    </div>
  </div>
  <div class="detail-pager">
    ${newer ? `<button class="btn small" onclick="location.hash='#/bandori/card/${newer.id}'">← 较新 #${newer.id}</button>` : '<span></span>'}
    <span class="pager-pos">#${card.id} / ${all.length}</span>
    ${older ? `<button class="btn small" onclick="location.hash='#/bandori/card/${older.id}'">较旧 #${older.id} →</button>` : '<span></span>'}
  </div>

  <div class="detail-top">
    <div class="art-row">
      ${bdArtBoxHtml(card, 'normal', card._originals?.normal)}
      ${bdArtBoxHtml(card, 'trained', card._originals?.trained)}
    </div>
    <div class="card-panel">
      <h3 style="margin-bottom:10px">📋 基本资料</h3>
      <table class="info-table">
        <tr><th>卡面编号</th><td>#${card.id}</td></tr>
        <tr><th>卡面名称</th><td>${esc(card.prefix || '（未命名）')}</td></tr>
        <tr><th>角色</th><td>${esc(card.characterName)}</td></tr>
        <tr><th>所属乐队</th><td>${esc(card.unitName)}</td></tr>
        <tr><th>属性</th><td>${attrDot(card.attr, colors, names)} ${esc(names[card.attr] || card.attr)}</td></tr>
        <tr><th>稀有度</th><td><span class="rarity-stars">${'★'.repeat(card.rarity)}</span>（${card.rarity}★）</td></tr>
        <tr><th>卡面种类</th><td>${esc(TYPE_NAMES[detail?.cardType || card.cardType] || detail?.cardType || card.cardType || '—')}${loadingHint}</td></tr>
        <tr><th>日服上线</th><td>${relLabel(card.releaseJp || card.releaseAt)}</td></tr>
        <tr><th>国服上线</th><td>${relLabel(card.releaseCn)}</td></tr>
        <tr><th>资源标识</th><td style="font-family:Consolas,monospace;font-size:13px">${esc(card.assetbundleName || '')}</td></tr>
      </table>
    </div>
  </div>

  <div class="section-gap"></div>
  <div class="info-grid">
    <div class="card-panel skill-panel">
      <h3 style="margin-bottom:10px">⚡ 技能</h3>
      <div class="sname">${esc(detail?.skillName || card.skillName || (detail ? '—' : '加载中…'))}</div>
      ${(detail?.skillLines || []).length
        ? detail.skillLines.map(([tag, t]) => `
          <div class="sdesc-line ${tag === 'zh-Hans' ? '' : 'muted'}">${esc(t)}</div>`).join('')
        : '<div class="sdesc" style="color:var(--text-3);margin-top:6px">技能描述加载中…</div>'}
      ${detail?.gachaText ? `<div style="margin-top:12px;font-size:13.5px;color:var(--text-2)">🏷️ 招募语：${esc(detail.gachaText)}</div>` : ''}
      <div style="margin-top:14px;border-top:1px dashed var(--border);padding-top:12px">
        <h3 style="margin-bottom:8px">📖 卡牌剧情</h3>
        ${(detail?.episodes || []).length
          ? detail.episodes.map(e => `
            <div class="ep-row">
              <span>${esc(e.title || '')}</span>
              <span style="color:var(--text-3);font-size:12.5px">
                Lv.${e.releaseLevel ?? '—'} · 属性加成 ${(e.append || []).filter(x => x).join(' / ') || '—'}
              </span>
            </div>`).join('')
          : `<div style="color:var(--text-3);font-size:13px">${detail ? '暂无剧情' : '剧情加载中…'}</div>`}
      </div>
    </div>
    <div class="card-panel">
      <h3>ℹ️ 说明</h3>
      <div style="font-size:13.5px;color:var(--text-2);line-height:2">
        · 数据来源：<a href="https://bestdori.com/info/cards/${card.id}" target="_blank" rel="noopener">bestdori</a>（BanG Dream! 资源站）<br>
        · 原图按需抓取自官方资产，命名规范：<code>Bandori卡牌_编号_卡名_角色_突破前/后.png</code><br>
        · 下载与 AI 超分统一在左下角「下载管理」面板处理<br>
        · 属性图例：${Object.entries(names).map(([k, v]) =>
          `${attrDot(k, colors, names)} ${esc(v)}`).join('　')}
      </div>
    </div>
  </div>`;
}

// 邦多利详情页的全局动作
window.__bdZoomCard = (id, kind, cached) =>
  openImageModal(cached
    ? `/api/bandori/originals/${id}_${kind}.png`
    : `/api/bandori/thumbs/${id}_${kind === 'after_training' ? 'trained' : 'normal'}.webp`);

window.__bdDownload = async (cardId, kind) => {
  try {
    const base = getBandoriCard(cardId);
    const label = `${base?.prefix || `卡面 #${cardId}`} · ${kind === 'after_training' ? '突破后' : '突破前'}`;
    const r0 = await downloadOriginal(cardId, kind, 'bandori');
    if (!r0.ok || !r0.jobId) throw new Error(r0.error || '任务创建失败');
    registerJob(r0.jobId, label, { card: cardId, kind, mod: 'bandori' });
    toast('已加入下载队列 · 进度见左下角「下载管理」');
  } catch (e) {
    toast(`下载失败：${e.message}`, true);
  }
};


// ================= 闪耀色彩模块（真数据） =================
// 数据源 shinycolors.moe：卡面单图（无属性色体系，无属性角标），
// P 卡的 fes_card 变体立绘展示为「Fes 卡面」。

function shinyRarityLabel(c) {
  return c.rarity || "—";
}

/** 闪耀色彩首页：与 pjsk/bandori 首页同款布局 */
export async function renderShinyHome(app) {
  app.innerHTML = '<div class="loading-block">正在加载闪耀色彩卡面…</div>';
  try {
    const [, st] = await Promise.all([
      ensureShinyIndex(),
      fetchShinyStatus().catch(() => null),
    ]);
    const cards = getShinyCards();
    if (!cards.length) {
      app.innerHTML = `
      <div class="placeholder-hero">
        <div class="big">📦</div>
        <h2>还没有闪耀色彩卡面数据</h2>
        <p>请先运行项目里的 <code>scripts\\run_shinycolors_scrape.cmd</code> 完成首次抓取，然后刷新本页面。</p>
      </div>`;
      return;
    }
    // 「最新」按实装日排序（shinycolors.moe 未实装卡为占位日期，取实装序）
    const latest = [...cards]
      .sort((a, b) => (b.releaseAt || 0) - (a.releaseAt || 0))
      .slice(0, 12);
    const maxId = cards.length ? Math.max(...cards.map(c => c.id)) : 0;
    const updated = getShinyUpdatedAt() ? fmtDate(getShinyUpdatedAt()) : "—";
    const cnt = st?.lastCounts;
    const cntHint = cnt
      ? `（新下载 ${cnt.downloaded ?? 0} · 跳过 ${cnt.skipped ?? 0}${cnt.failed ? ` · 失败 ${cnt.failed}` : ""}）`
      : "增量模式 · 已有卡面自动跳过";
    const partial = st?.lastResult === "partial";

    app.innerHTML = `
  <div class="hero">
    <h1>卡牌雷达 · <span class="hl">闪耀色彩卡面图鉴</span></h1>
    <p>每两周自动同步 SHINY COLORS（闪耀色彩）的卡面数据库：低清预览常驻本地，原图点击下载时才抓取，数据来源 shinycolors.moe～</p>
    <div class="actions">
      <button class="btn primary" onclick="location.hash='#/sc/cards'">🗂️ 浏览全部卡面</button>
      <button class="btn" onclick="location.hash='#/about'">📅 更新与存储策略</button>
    </div>
  </div>
  <div class="stats">
    <div class="stat-tile"><div class="label">卡面总数</div><div class="value">${cards.length}</div><div class="hint">shinycolors.moe 数据 · 自动更新</div></div>
    <div class="stat-tile"><div class="label">最新卡面</div><div class="value">#${maxId}</div><div class="hint">${esc(cards[0]?.prefix || "")}</div></div>
    <div class="stat-tile"><div class="label">上次抓取</div><div class="value" style="font-size:16px;line-height:1.4">${st?.lastRun ? fmtDate(st.lastRun) : "—"}</div><div class="hint">${partial ? '<span style="color:#b45309">⚠ 部分图片失败，详见 data/logs/shinycolors_scrape.log</span>　' : ""}${cntHint}</div></div>
    <div class="stat-tile"><div class="label">下次自动抓取</div><div class="value" style="font-size:16px;line-height:1.4">每两周周一 09:40</div><div class="hint">Windows 计划任务 · 失败会弹窗提醒</div></div>
  </div>
  <div class="home-sec-head">
    <h2>🆕 最新卡面</h2>
    <a href="#/sc/cards">查看全部 →</a>
  </div>
  <div class="card-grid">${latest.map(c => cardCellHtml(c, "shinycolors")).join("")}</div>
  <div class="section-gap"></div>
  <div class="card-panel" style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
    <span style="font-size:22px">✨</span>
    <div style="flex:1;min-width:240px">
      <div style="font-weight:700">镜像服务运行中</div>
      <div style="font-size:12.5px;color:var(--text-3)">数据目录 data/shinycolors · 缩略图 ${cards.length} 组 · 原图按需抓取</div>
    </div>
    <button class="btn small" onclick="location.hash='#/about'">了解更多</button>
  </div>`;
  } catch (e) {
    app.innerHTML = `
    <div class="placeholder-hero">
      <div class="big">🔌</div>
      <h2>数据服务未就绪</h2>
      <p>${esc(e.message)}。请运行 <code>scripts\\verify_setup.cmd</code> 自检修复。</p>
    </div>`;
  }
}

function shinyArtBox(card, kind, cached) {
  const normal = kind === "normal";
  const label = normal ? "卡面图" : "Fes 卡面（特训后）";
  const thumbKind = normal ? "normal" : "trained";
  const url = `/api/shinycolors/thumbs/${card.id}_${thumbKind}.webp`;
  return `
  <div class="art-box">
    <div class="tag">${label}</div>
    <div class="img-wrap" onclick="window.__scZoomCard(${card.id},'${kind}',${!!cached})">
      <img src="${url}" loading="lazy" alt="${label}"
           onerror="this.parentElement.innerHTML='<div style=\'display:grid;place-items:center;aspect-ratio:1/1;color:var(--text-3);font-size:14px\'>暂无卡面图片</div>'">
    </div>
    <div class="actions" id="sc-act-${kind}">
      <button class="btn primary" onclick="window.__scDownload(${card.id},'${kind}')">
        <span class="spinner" style="display:none"></span>⬇️ 下载原图</button>
      ${cached
        ? `<a class="btn small" href="/api/shinycolors/originals/${card.id}${normal ? "" : "_fes"}.png" target="_blank" rel="noopener">👁 在线查看原图</a>`
        : '<span class="note">1136×640 原档 · PNG 无损转出，超分见左下角「下载管理」</span>'}
    </div>
  </div>`;
}

/** 闪耀色彩卡面详情页：资料 / 数值 / 技能（数据源 shinycolors.moe，日文原文） */
export async function renderShinyDetail(app, id) {
  app.innerHTML = '<div class="loading-block">正在加载卡面详情…</div>';
  await ensureShinyIndex();
  const base = getShinyCard(id);
  if (!base) {
    app.innerHTML = `<div class="loading-block">找不到卡面 #${esc(id)}</div>`;
    return;
  }
  const draw = (d) => {
    // 用户已切走时不覆盖
    if (location.hash !== `#/sc/card/${id}`) return;
    const detail = d || {};
    const card = { ...base, ...(detail.card || {}),
                   _hasOriginal: detail.hasOriginal,
                   _hasFesOriginal: detail.hasFesOriginal,
                   _hasTrained: detail.hasTrained };
    const idol = detail.idol || {};
    const st = detail.status || {};

    const all = getShinyCards();
    const pos = all.findIndex(c => c.id === Number(id));
    const newer = pos > 0 ? all[pos - 1] : null;
    const older = pos >= 0 && pos < all.length - 1 ? all[pos + 1] : null;
    const relYear = card.releaseAt ? new Date(Number(card.releaseAt)).getFullYear() : 0;
    const releaseLabel = relYear > 2035 ? "未公布" : fmtDate(card.releaseAt);

    app.innerHTML = `
  <div class="detail-head">
    <div>
      <a class="back" href="#/sc/cards">← 返回图鉴</a>
      <div class="page-title" style="margin-top:8px">${esc(card.prefix || `卡面 #${card.id}`)}</div>
      <div class="page-desc">${esc(card.characterName)} · ${esc(card.unitName)} · ${esc(card.rarity)} · #${card.id}</div>
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      ${card.spoiler ? '<span class="badge spoiler">剧透 · 未上线</span>' : '<span class="badge new">已上线</span>'}
    </div>
  </div>
  <div class="detail-pager">
    ${newer ? `<button class="btn small" onclick="location.hash='#/sc/card/${newer.id}'">← 较新 #${newer.id}</button>` : "<span></span>"}
    <span class="pager-pos">#${card.id} / ${all.length}</span>
    ${older ? `<button class="btn small" onclick="location.hash='#/sc/card/${older.id}'">较旧 #${older.id} →</button>` : "<span></span>"}
  </div>

  <div class="detail-top">
    <div class="art-row">
      ${shinyArtBox(card, "normal", card._hasOriginal)}
      ${card.trainable ? shinyArtBox(card, "fes", card._hasFesOriginal) : ""}
    </div>
    <div class="card-panel">
      <h3 style="margin-bottom:10px">📋 基本资料</h3>
      <table class="info-table">
        <tr><th>卡面编号</th><td>#${card.id}</td></tr>
        <tr><th>卡面名称</th><td>${esc(card.prefix || "（未命名）")}</td></tr>
        <tr><th>角色</th><td>${esc(idol.idolName || card.characterName)}</td></tr>
        <tr><th>所属组合</th><td>${esc(card.unitName)}</td></tr>
        <tr><th>稀有度</th><td><span class="rarity-text">${esc(card.rarity)}</span></td></tr>
        <tr><th>卡面种类</th><td>${esc(card.cardKind === "P" ? "Produce" : "Support")}</td></tr>
        <tr><th>实装日期</th><td>${releaseLabel}</td></tr>
        <tr><th>资源编号</th><td style="font-family:Consolas,monospace;font-size:13px">${esc(card.enzaId || "")}</td></tr>
        ${idol.birthday ? `<tr><th>角色生日</th><td>${esc(idol.birthday)}</td></tr>` : ""}
        ${idol.cv ? `<tr><th>声优</th><td>${esc(idol.cv)}</td></tr>` : ""}
      </table>
    </div>
  </div>

  <div class="section-gap"></div>
  <div class="info-grid">
    <div class="card-panel">
      <h3 style="margin-bottom:10px">📊 数值（满级）</h3>
      ${st.vocal !== undefined
        ? `<table class="info-table">
             <tr><th>Vo（Vocal）</th><td>${st.vocal ?? "—"}</td></tr>
             <tr><th>Da（Dance）</th><td>${st.dance ?? "—"}</td></tr>
             <tr><th>Vi（Visual）</th><td>${st.visual ?? "—"}</td></tr>
             <tr><th>Me（Mental）</th><td>${st.mental ?? "—"}</td></tr>
           </table>`
        : '<div style="color:var(--text-3);font-size:13px">数值加载中…</div>'}
    </div>
    <div class="card-panel">
      <h3 style="margin-bottom:10px">⚡ 技能与面板</h3>
      ${(detail.panels || []).length
        ? detail.panels.slice(0, 8).map(p => `
          <div class="ep-row"><span>${esc(p.skillTitle || "")}</span>
            <span style="color:var(--text-3);font-size:12.5px">${esc(p.skillDesc || "")}</span></div>`).join("")
        : '<div style="color:var(--text-3);font-size:13px">加载中…</div>'}
      ${(detail.supportSkills || []).length ? `
        <div style="margin-top:14px;border-top:1px dashed var(--border);padding-top:12px">
          <h3 style="margin-bottom:8px">🤝 支援技能</h3>
          ${detail.supportSkills.slice(0, 6).map(s => `
            <div class="ep-row"><span>${esc(s.skillName || "")}</span>
              <span style="color:var(--text-3);font-size:12.5px">${esc(s.skillDesc || "")}</span></div>`).join("")}
        </div>` : ""}
    </div>
  </div>`;
  };

  draw(null); // 立即渲染（index 数据）
  fetchShinyCardDetail(id)
    .then(d => draw(d))
    .catch(() => { /* 详情失败保持骨架 */ });
}

// 闪耀色彩详情页的全局动作（kind: normal 突破前 / fes 特训后）
window.__scZoomCard = (id, kind = "normal", cached) =>
  openImageModal(cached
    ? `/api/shinycolors/originals/${id}${kind === "fes" ? "_fes" : ""}.png`
    : `/api/shinycolors/thumbs/${id}_${kind === "fes" ? "trained" : "normal"}.webp`);

window.__scDownload = async (cardId, kind = "normal") => {
  try {
    const base = getShinyCard(cardId);
    const label = `${base?.prefix || `卡面 #${cardId}`}${kind === "fes" ? " · 特训后" : ""}`;
    const r0 = await downloadOriginal(cardId, kind, "shinycolors");
    if (!r0.ok || !r0.jobId) throw new Error(r0.error || "任务创建失败");
    registerJob(r0.jobId, label, { card: cardId, kind, mod: "shinycolors" });
    toast("已加入下载队列 · 进度见左下角「下载管理」");
  } catch (e) {
    toast(`下载失败：${e.message}`, true);
  }
};

// ==================== Our Notes 模块（bdon.moe） ====================

/** Our Notes 首页：与 pjsk/邦多利首页同款布局（hero + 统计 + 最新卡面网格） */
export async function renderOnotesHome(app) {
  app.innerHTML = '<div class="loading-block">正在加载 Our Notes 卡面…</div>';
  try {
    const [, st] = await Promise.all([
      ensureOnotesIndex(),
      fetchOnotesStatus().catch(() => null),
    ]);
    const cards = getOnotesCards();
    if (!cards.length) {
      app.innerHTML = `
      <div class="placeholder-hero">
        <div class="big">📦</div>
        <h2>还没有 Our Notes 卡面数据</h2>
        <p>请先运行项目里的 <code>scripts\\run_onotes_scrape.cmd</code> 完成首次抓取，然后刷新本页面。</p>
      </div>`;
      return;
    }
    // 「最新」按发布时间排序（索引抓详情时已回填 releaseAt）
    const latest = [...cards]
      .sort((a, b) => (b.releaseAt || 0) - (a.releaseAt || 0))
      .slice(0, 12);
    const maxId = cards.length ? Math.max(...cards.map(c => c.id)) : 0;
    const updated = getOnotesUpdatedAt() ? fmtDate(getOnotesUpdatedAt()) : "—";
    const cnt = st?.lastCounts;
    const cntHint = cnt
      ? `（新下载 ${cnt.downloaded ?? 0} · 跳过 ${cnt.skipped ?? 0}${cnt.failed ? ` · 失败 ${cnt.failed}` : ""}）`
      : "增量模式 · 已有卡面自动跳过";
    const partial = st?.lastResult === "partial";
    const memberCount = cards.filter(c => c.cardKind !== "support").length;
    const supportCount = cards.length - memberCount;

    app.innerHTML = `
  <div class="hero">
    <h1>卡牌雷达 · <span class="hl">Our Notes 卡面图鉴</span></h1>
    <p>每两周自动同步 BanG Dream! Our Notes 的卡面数据库（周一 10:00）：角色卡与支援卡双图鉴，原图 1440×1920 高清 PNG，数据来源 bdon.moe～</p>
    <div class="actions">
      <button class="btn primary" onclick="location.hash='#/onotes/cards'">🗂️ 浏览全部卡面</button>
      <button class="btn" onclick="location.hash='#/about'">📅 更新与存储策略</button>
    </div>
  </div>
  <div class="stats">
    <div class="stat-tile"><div class="label">卡面总数</div><div class="value">${cards.length}</div><div class="hint">角色卡 ${memberCount} · 支援卡 ${supportCount}</div></div>
    <div class="stat-tile"><div class="label">最新卡面</div><div class="value">#${maxId}</div><div class="hint">${esc(cards[0]?.prefix || "")}</div></div>
    <div class="stat-tile"><div class="label">上次抓取</div><div class="value" style="font-size:16px;line-height:1.4">${st?.lastRun ? fmtDate(st.lastRun) : "—"}</div><div class="hint">${partial ? '<span style="color:#b45309">⚠ 部分图片失败，详见 data/logs/onotes_scrape.log</span>　' : ""}${cntHint}</div></div>
    <div class="stat-tile"><div class="label">下次自动抓取</div><div class="value" style="font-size:16px;line-height:1.4">每两周 · 周一 10:00</div><div class="hint">Windows 计划任务 · 失败会弹窗提醒</div></div>
  </div>
  <div class="home-sec-head">
    <h2>🆕 最新卡面</h2>
    <a href="#/onotes/cards">查看全部 →</a>
  </div>
  <div class="card-grid">${latest.map(c => cardCellHtml(c, "onotes")).join("")}</div>
  <div class="section-gap"></div>
  <div class="card-panel" style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
    <span style="font-size:22px">🎶</span>
    <div style="flex:1;min-width:240px">
      <div style="font-weight:700">镜像服务运行中</div>
      <div style="font-size:12.5px;color:var(--text-3)">数据目录 data/onotes · 缩略图 ${cards.length} 组 · 原图按需抓取（1440×1920 → PNG）</div>
    </div>
    <button class="btn small" onclick="location.hash='#/about'">了解更多</button>
  </div>`;
  } catch (e) {
    app.innerHTML = `
    <div class="placeholder-hero">
      <div class="big">🔌</div>
      <h2>数据服务未就绪</h2>
      <p>${esc(e.message)}。请运行 <code>scripts\\verify_setup.cmd</code> 自检修复。</p>
    </div>`;
  }
}

/** Our Notes 详情页单图盒（每卡单立绘：角色卡 member_full / 支援卡 snap_full） */
function onotesArtBox(card, cached) {
  const kind = card.cardKind === "support" ? "support" : "card";
  const label = kind === "support" ? "支援卡图" : "卡面图";
  const url = `/api/onotes/thumbs/${card.id}_${kind}.webp`;
  return `
  <div class="art-box">
    <div class="tag">${label}</div>
    <div class="img-wrap" onclick="window.__onZoomCard(${card.id},'${kind}',${!!cached})">
      <img src="${url}" loading="lazy" alt="${label}"
           onerror="this.parentElement.innerHTML='<div style=\'display:grid;place-items:center;aspect-ratio:1/1;color:var(--text-3);font-size:14px\'>暂无卡面图片</div>'">
    </div>
    <div class="actions" id="on-act-${kind}">
      <button class="btn primary" onclick="window.__onDownload(${card.id},'${kind}')">
        <span class="spinner" style="display:none"></span>⬇️ 下载原图</button>
      ${cached
        ? `<a class="btn small" href="/api/onotes/originals/${card.id}_${kind}.png" target="_blank" rel="noopener">👁 在线查看原图</a>`
        : '<span class="note">1440×1920 原档 · PNG 无损转出，超分见左下角「下载管理」</span>'}
    </div>
  </div>`;
}

/** Our Notes 卡面详情页：角色卡 / 支援卡同一渲染器，kind 区分文案。
 *  ⚠️ 两类 ID 序列重叠（1~81 双方都有）：路由与查找一律用 (kind, id) 复合键。
 *  两段渲染：先按 index 数据立即出完整框架，详情接口返回后原地补齐数值与技能。 */
export async function renderOnotesDetail(app, id, kindParam = null) {
  app.innerHTML = '<div class="loading-block">正在加载卡面详情…</div>';
  await ensureOnotesIndex();
  const kind = kindParam === "support" ? "support" : "card";
  const base = getOnotesCard(id, kind);
  if (!base) {
    app.innerHTML = `<div class="loading-block">找不到卡面 #${esc(id)}</div>`;
    return;
  }
  const attrName = ONOTES_ATTR_NAMES[base.attr] || base.attr || "";
  const attrColor = ONOTES_ATTR_COLORS[base.attr] || "";
  const draw = (d) => {
    // 用户已切走时不覆盖
    if (location.hash !== `#/onotes/card/${kind}/${id}`) return;
    const detail = d || {};
    const card = { ...base, ...(detail.card || {}), _hasOriginal: detail.hasOriginal };
    const skills = detail.skills || [];
    const chars = detail.characterLinks?.length
      ? detail.characterLinks.map(c => c.name).join("、")
      : card.characterName;
    // 稀有度显示名：特殊档统一显示 EX（与右上角图标一致）
    const rarityDisplay =
      (detail.rarity || card.rarity) === "特殊" ? "EX" : (detail.rarity || card.rarity);

    // 翻页在同一 kind 序列内进行（互不串台）
    const all = getOnotesCards().filter(c =>
      (c.cardKind === "support" ? "support" : "card") === kind);
    const pos = all.findIndex(c => c.id === Number(id));
    const newer = pos > 0 ? all[pos - 1] : null;
    const older = pos >= 0 && pos < all.length - 1 ? all[pos + 1] : null;

    app.innerHTML = `
  <div class="detail-head">
    <div>
      <a class="back" href="#/onotes/cards">← 返回图鉴</a>
      <div class="page-title" style="margin-top:8px">${esc(card.prefix || `卡面 #${card.id}`)}</div>
      <div class="page-desc">${esc(chars)} · ${esc(card.unitName)} · ${esc(rarityDisplay)} · #${card.id}</div>
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <span class="badge new">${kind === "support" ? "支援卡" : "角色卡"}</span>
    </div>
  </div>
  <div class="detail-pager">
    ${newer ? `<button class="btn small" onclick="location.hash='#/onotes/card/${kind}/${newer.id}'">← 较新 #${newer.id}</button>` : "<span></span>"}
    <span class="pager-pos">#${card.id} / ${all.length}</span>
    ${older ? `<button class="btn small" onclick="location.hash='#/onotes/card/${kind}/${older.id}'">较旧 #${older.id} →</button>` : "<span></span>"}
  </div>

  <div class="detail-top">
    <div class="art-row">
      ${onotesArtBox(card, card._hasOriginal)}
    </div>
    <div class="card-panel">
      <h3 style="margin-bottom:10px">📋 基本资料</h3>
      <table class="info-table">
        <tr><th>卡面编号</th><td>#${card.id} · ${kind === "support" ? "支援卡" : "角色卡"}</td></tr>
        <tr><th>卡面名称</th><td>${esc(card.prefix || "（未命名）")}</td></tr>
        <tr><th>${kind === "support" ? "关联角色" : "角色"}</th><td>${esc(chars)}</td></tr>
        <tr><th>乐队</th><td>${esc(detail.band || card.unitName)}</td></tr>
        <tr><th>稀有度</th><td><span class="rarity-text">${esc(rarityDisplay)}</span></td></tr>
        ${card.attr ? `<tr><th>属性</th><td><span style="display:inline-flex;align-items:center;gap:6px">
          <span class="attr-dot" style="background:${attrColor}"></span>${esc(attrName || card.attr)}</span></td></tr>` : ""}
        <tr><th>Total Power</th><td>${esc(detail.total ?? card.power ?? "—")}</td></tr>
        <tr><th>实装日期</th><td>${esc(detail.release || "—")}</td></tr>
        ${detail.servers ? `<tr><th>上线服务器</th><td>${esc(detail.servers)}</td></tr>` : ""}
      </table>
      ${detail.flavor ? `<div style="margin-top:14px;border-top:1px dashed var(--border);padding-top:12px">
        <div style="font-size:13px;color:var(--text-2);line-height:1.8">💬 ${esc(detail.flavor)}</div>
      </div>` : ""}
    </div>
  </div>
  <div class="section-gap"></div>
  ${(detail.pf || detail.tc || detail.vi) ? `
  <div class="card-panel">
    <h3 style="margin-bottom:10px">📊 数值</h3>
    <table class="info-table">
      <tr><th>Performance</th><td>${esc(detail.pf ?? "—")}</td></tr>
      <tr><th>Technic</th><td>${esc(detail.tc ?? "—")}</td></tr>
      <tr><th>Visual</th><td>${esc(detail.vi ?? "—")}</td></tr>
    </table>
  </div>
  <div class="section-gap"></div>` : ""}
  ${skills.length ? `
  <div class="card-panel">
    <h3 style="margin-bottom:10px">⚡ 技能</h3>
    ${skills.map(s => `
      <div style="margin-bottom:16px">
        <div style="font-weight:700;margin-bottom:6px">${esc(s.name)}${s.kind ? ` <span style="font-size:12px;color:var(--text-3)">（${esc(s.kind)}）</span>` : ""}</div>
        <table class="info-table">
          ${s.levels.map(([lv, desc]) => `<tr><th>${esc(lv)}</th><td>${esc(desc)}</td></tr>`).join("")}
        </table>
      </div>`).join("")}
  </div>` : `<div class="card-panel"><div class="loading-block">技能详情加载中…</div></div>`}`;
  };

  draw(null); // 立即渲染（index 数据）
  fetchOnotesCardDetail(id, kind)
    .then(d => draw(d))
    .catch(() => { /* 详情失败保持骨架 */ });
}

// Our Notes 详情页的全局动作（kind: card 角色卡 / support 支援卡）
window.__onZoomCard = (id, kind = "card", cached) =>
  openImageModal(cached
    ? `/api/onotes/originals/${id}_${kind}.png`
    : `/api/onotes/thumbs/${id}_${kind}.webp`);

window.__onDownload = async (cardId, kind = "card") => {
  try {
    const base = getOnotesCard(cardId);
    const label = `${base?.prefix || `卡面 #${cardId}`} · ${kind === "support" ? "支援卡" : "角色卡"}`;
    const r0 = await downloadOriginal(cardId, kind, "onotes");
    if (!r0.ok || !r0.jobId) throw new Error(r0.error || "任务创建失败");
    registerJob(r0.jobId, label, { card: cardId, kind, mod: "onotes" });
    toast("已加入下载队列 · 进度见左下角「下载管理」");
  } catch (e) {
    toast(`下载失败：${e.message}`, true);
  }
};
