// 首页：概览 + 统计 + 最新卡牌
import { fetchStatus } from '../api.js?v=1.16.0';
import { ensureIndex, getCards, getUpdatedAt } from '../store.js?v=1.16.0';
import { esc, cardCellHtml, fmtDate } from '../ui.js?v=1.16.0';

export async function renderHome(app) {
  app.innerHTML = '<div class="loading-block">正在加载卡牌雷达…</div>';
  try {
    const [, status] = await Promise.all([ensureIndex(), fetchStatus().catch(() => null)]);
    const cards = getCards();
    if (!cards.length) {
      app.innerHTML = `
      <div class="placeholder-hero">
        <div class="big">📦</div>
        <h2>还没有卡牌数据</h2>
        <p>请先运行项目里的 <code>scripts\\run_scrape.cmd</code> 完成首次抓取，<br>然后刷新本页面。之后每两周的周一 09:00 会自动更新。</p>
      </div>`;
      return;
    }
    const latest = cards.slice(0, 12);
    const maxId = cards.length ? Math.max(...cards.map(c => c.id)) : 0;
    const updated = getUpdatedAt() ? fmtDate(getUpdatedAt()) : '—';
    const cnt = status?.lastCounts;
    const cntHint = cnt
      ? `（新下载 ${cnt.downloaded ?? 0} · 跳过 ${cnt.skipped ?? 0}${cnt.failed ? ` · 失败 ${cnt.failed}` : ''}）`
      : '增量模式 · 已有卡面自动跳过';
    const partial = status?.lastResult === 'partial';

    app.innerHTML = `
  <div class="hero">
    <h1>卡牌雷达 · <span class="hl">PJSK 卡面图鉴</span></h1>
    <p>每两周自动同步 pjsk.moe 的卡牌数据库（周一 09:00）：低清预览常驻本地，PNG 原图点击下载时才抓取，绝不浪费一寸存储空间～</p>
    <div class="actions">
      <button class="btn primary" onclick="location.hash='#/pjsk/cards'">🗂️ 浏览全部卡牌</button>
      <button class="btn" onclick="location.hash='#/about'">📅 更新与存储策略</button>
    </div>
  </div>
  <div class="stats">
    <div class="stat-tile"><div class="label">卡牌总数</div><div class="value">${cards.length}</div><div class="hint">JP 服务器 · 最新资源 · 中文显示</div></div>
    <div class="stat-tile"><div class="label">最新卡牌</div><div class="value">#${maxId}</div><div class="hint">${esc(cards[0]?.prefix || '')}</div></div>
    <div class="stat-tile"><div class="label">上次抓取</div><div class="value" style="font-size:16px;line-height:1.4">${updated}</div><div class="hint">${partial ? '<span style="color:#b45309">⚠ 部分图片失败，详见 data/logs/scrape.log</span>　' : ''}${cntHint}</div></div>
    <div class="stat-tile"><div class="label">下次自动抓取</div><div class="value" style="font-size:16px;line-height:1.4">每两周 · 周一 09:00</div><div class="hint">Windows 计划任务 · 失败会弹窗提醒</div></div>
  </div>
  <div class="home-sec-head">
    <h2>🆕 最新卡牌</h2>
    <a href="#/pjsk/cards">查看全部 →</a>
  </div>
  <div class="card-grid">${latest.map(cardCellHtml).join('')}</div>
  <div class="section-gap"></div>
  <div class="card-panel" style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
    <span style="font-size:22px">🐳</span>
    <div style="flex:1;min-width:240px">
      <div style="font-weight:700">镜像服务运行中${status?.version ? ` · v${status.version}` : ''}</div>
      <div style="font-size:12.5px;color:var(--text-3)">数据目录 data/ · 缩略图 ${cards.length} 组 · 已缓存 PNG 原图 ${status?.originalsCount ?? 0} 张</div>
    </div>
    <button class="btn small" onclick="location.hash='#/about'">了解更多</button>
  </div>`;
  } catch (e) {
    app.innerHTML = `
    <div class="placeholder-hero">
      <div class="big">🔌</div>
      <h2>数据服务未就绪</h2>
      <p>${esc(e.message)}。请运行 <code>scripts\\verify_setup.cmd</code> 自检修复，<br>它会自动重启隐藏窗口的镜像服务并补齐计划任务。</p>
    </div>`;
  }
}
