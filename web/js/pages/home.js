// 四游戏统一首页渲染器（替代原版 4 份重复首页代码）
import { getModule, cardUniqueKey } from '../modules/registry.js?v=2.0.0';
import { fetchModuleStatus, probeSources } from '../api.js?v=2.0.0';
import { ensureModuleIndex, getModuleCards, getModuleUpdatedAt } from '../store.js?v=2.0.0';
import { esc, cardCellHtml, fmtDate, skeletonGridHtml } from '../ui.js?v=2.0.0';
import { getFavorites } from '../userSettings.js?v=2.0.0';

export async function renderHome(app, modId = 'pjsk') {
  const mod = getModule(modId);
  app.innerHTML = `
    <div class="hero skeleton-hero shimmer"></div>
    <div class="section-gap"></div>
    ${skeletonGridHtml(8)}`;

  try {
    const [, status] = await Promise.all([
      ensureModuleIndex(mod.apiMod),
      fetchModuleStatus(mod.apiMod).catch(() => null),
    ]);
    const cards = getModuleCards(mod.apiMod);
    if (!cards.length) {
      app.innerHTML = `
      <div class="placeholder-hero">
        <div class="big">${mod.icon}</div>
        <h2>还没有 ${esc(mod.name)} 数据</h2>
        <p>请先运行项目里的 <code>${esc(mod.emptyCmd)}</code> 完成首次抓取，<br>完成后刷新本页面即可浏览与下载。</p>
      </div>`;
      return;
    }

    const latest = [...cards].sort((a, b) => {
      if (mod.latestSort === 'release_desc') {
        return (b.releaseAt || 0) - (a.releaseAt || 0) || b.id - a.id;
      }
      return b.id - a.id;
    }).slice(0, 12);

    const maxId = Math.max(...cards.map(c => c.id));
    const updated = status?.lastRun ? fmtDate(status.lastRun) : (getModuleUpdatedAt() ? fmtDate(getModuleUpdatedAt(mod.apiMod)) : '—');
    const cnt = status?.lastCounts;
    const offline = Boolean(cnt?.offline);
    const partial = status?.lastResult === 'partial';
    const cntHint = offline
      ? '离线降级模式（已保留本地缓存索引）'
      : cnt
        ? `新下载 ${cnt.downloaded ?? 0} · 跳过 ${cnt.skipped ?? 0}${cnt.failed ? ` · 失败 ${cnt.failed}` : ''}`
        : '增量模式 · 已有卡面自动跳过';

    const favMap = getFavorites();
    const modFavCount = cards.filter(c => Boolean(favMap[cardUniqueKey(mod.apiMod, c)])).length;

    let extraCountHint = mod.sourceName;
    if (mod.apiMod === 'onotes') {
      const mCnt = cards.filter(c => c.cardKind !== 'support').length;
      extraCountHint = `角色卡 ${mCnt} · 支援卡 ${cards.length - mCnt}`;
    }

    app.innerHTML = `
  <div class="hero">
    <div class="hero-top-row">
      <h1>卡牌雷达 · <span class="hl">${esc(mod.name)}图鉴</span></h1>
      <span class="source-pill" id="home-source-pill">探测源站状态…</span>
    </div>
    <p>${esc(mod.heroDesc)}</p>
    <div class="actions">
      <button class="btn primary" onclick="location.hash='#/${mod.routeId}/cards'">🗂️ 浏览全部卡面</button>
      <button class="btn" id="home-go-recent">🆕 近期新卡</button>
      <button class="btn" onclick="location.hash='#/favorites'">⭐ 我的收藏（${modFavCount}）</button>
      <button class="btn" onclick="location.hash='#/about'">📅 架构与策略</button>
    </div>
  </div>
  <div class="stats">
    <div class="stat-tile">
      <div class="label">卡面总数</div>
      <div class="value">${cards.length}</div>
      <div class="hint">${esc(extraCountHint)}</div>
    </div>
    <div class="stat-tile">
      <div class="label">最新编号</div>
      <div class="value">#${maxId}</div>
      <div class="hint">${esc(latest[0]?.prefix || '')}</div>
    </div>
    <div class="stat-tile">
      <div class="label">上次同步</div>
      <div class="value" style="font-size:17px;line-height:1.4">${esc(updated)}</div>
      <div class="hint">${partial ? '<span class="warn-txt">⚠ 部分资源失败，重试队列自愈中</span> · ' : ''}${esc(cntHint)}</div>
    </div>
    <div class="stat-tile">
      <div class="label">自动同步计划</div>
      <div class="value" style="font-size:17px;line-height:1.4">${esc(mod.schedule)}</div>
      <div class="hint">已缓存高清图 ${status?.originalsCount ?? 0} 张（${status?.cacheMB ?? 0} MB）${status?.retryPending ? ` · 待重试 ${status.retryPending}` : ''}</div>
    </div>
  </div>
  <div class="home-sec-head">
    <h2>🆕 最新卡面</h2>
    <a href="#/${mod.routeId}/cards">查看全部 ${cards.length} 张 →</a>
  </div>
  <div class="card-grid">${latest.map(c => cardCellHtml(c, mod.apiMod)).join('')}</div>
  <div class="section-gap"></div>
  <div class="card-panel status-banner">
    <span style="font-size:24px">${mod.icon}</span>
    <div style="flex:1;min-width:240px">
      <div style="font-weight:700">本地镜像微内核运行中${status?.version ? ` · v${esc(status.version)}` : ''}</div>
      <div style="font-size:12.5px;color:var(--text-3)">
        ${status?.aiEngine ? '🚀 Real-ESRGAN AI 引擎就绪（GPU 串行保护）' : '🎨 Pillow 渐进抗锯齿超分就绪（AI 引擎未安装时自动回退）'} · 按需抓图省空间
      </div>
    </div>
    <button class="btn small" onclick="location.hash='#/settings'">⚙️ 设置与缓存</button>
  </div>`;

    app.querySelector('#home-go-recent').onclick = () => {
      sessionStorage.setItem('cardRadar.openRecent', mod.routeId);
      location.hash = `#/${mod.routeId}/cards`;
    };

    // 异步探测数据源连通性（不阻塞首屏渲染）
    probeSources(false).then(res => {
      const pill = app.querySelector('#home-source-pill');
      if (!pill) return;
      const src = res?.sources?.[mod.apiMod];
      if (src?.ok) {
        pill.className = 'source-pill ok';
        pill.textContent = `● 数据源在线 · ${src.channel} ${src.latencyMs}ms`;
      } else {
        pill.className = 'source-pill offline';
        pill.textContent = '● 数据源不可达 · 展示本地缓存';
      }
    }).catch(() => {
      const pill = app.querySelector('#home-source-pill');
      if (pill) {
        pill.className = 'source-pill offline';
        pill.textContent = '● 离线缓存模式';
      }
    });
  } catch (e) {
    app.innerHTML = `
    <div class="placeholder-hero">
      <div class="big">🔌</div>
      <h2>数据服务未就绪</h2>
      <p>${esc(e.message)}。请运行 <code>scripts\\verify_setup.cmd</code> 自检修复。</p>
    </div>`;
  }
}
