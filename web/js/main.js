// 入口：游戏模块化导航 —— 每个模块有自己的首页/子页面，全局保留「设置」「关于与策略」；
// 切换模块时全站主题色顺滑过渡（theme.js + CSS @property）。
// 扩充新游戏模块：在 MODULES 里追加一项（pages[0] 即该模块的首页）即可，无需改其他代码。
import { register, start } from './router.js?v=1.16.2';
import { renderHome } from './pages/home.js?v=1.16.2';
import { renderCards } from './pages/cards.js?v=1.16.2';
import { renderDetail } from './pages/detail.js?v=1.16.2';
import { renderBandoriHome, renderBandoriDetail, renderShinyHome, renderShinyDetail,
         renderOnotesHome, renderOnotesDetail } from './pages/module.js?v=1.16.2';
import { renderAbout } from './pages/placeholder.js?v=1.16.2';
import { renderSettings } from './pages/settings.js?v=1.16.2';
import { fetchStatus } from './api.js?v=1.16.2';
import { initDlPanel } from './dlpanel.js?v=1.16.2';
import { applyTheme } from './theme.js?v=1.16.2';
import { getSettings, setSetting } from './userSettings.js?v=1.16.2';

// 游戏模块定义：theme 与 CSS 的 html[data-theme] 对应（pjsk=默认青蓝、bandori=#FF3377 红、
// onotes=星空紫、sc=#8adfff 蓝系）。
const MODULES = [
  { id: 'pjsk', name: 'PJSK 卡面', icon: '🐳', pages: [
    { route: 'home', icon: '🏠', label: '首页', handler: renderHome },
    { route: 'cards', icon: '🃏', label: '卡牌图鉴', handler: renderCards },
  ] },
  { id: 'bandori', name: '邦多利卡面', icon: '🎸', pages: [
    { route: 'home', icon: '🏠', label: '首页', handler: renderBandoriHome },
    { route: 'cards', icon: '🃏', label: '卡面图鉴', handler: a => renderCards(a, 'bandori') },
  ] },
  { id: 'onotes', name: 'Our Notes 卡面', icon: '🎶', pages: [
    { route: 'home', icon: '🏠', label: '首页', handler: renderOnotesHome },
    { route: 'cards', icon: '🃏', label: '卡面图鉴', handler: a => renderCards(a, 'onotes') },
  ] },
  { id: 'sc', name: '闪彩卡面', icon: '✨', pages: [
    { route: 'home', icon: '🏠', label: '首页', handler: renderShinyHome },
    { route: 'cards', icon: '🃏', label: '卡面图鉴', handler: a => renderCards(a, 'shinycolors') },
  ] },
];

// 卡面详情路由：pjsk 用 #/card/:id（旧链接兼容），邦多利用 #/bandori/card/:id；
// 路由名指向各自模块的 cards 页，侧栏「图鉴」保持高亮
register(/^\/card\/(\d+)$/, 'pjsk/cards', renderDetail);
register(/^\/bandori\/card\/(\d+)$/, 'bandori/cards', renderBandoriDetail);
// Our Notes：角色卡/支援卡 ID 序列重叠，详情路由带 kind
register(/^\/onotes\/card\/(card|support)\/(\d+)$/, 'onotes/cards',
  (app, kind, id) => renderOnotesDetail(app, id, kind));
register(/^\/sc\/card\/(\d+)$/, 'sc/cards', renderShinyDetail);
for (const mod of MODULES) {
  for (const p of mod.pages) {
    register(new RegExp('^\\/' + mod.id + '\\/' + p.route + '$'),
             mod.id + '/' + p.route, p.handler);
  }
}

// 全局页面（不属于任何游戏模块，侧栏「通用」组）：路由保持扁平 #/settings、#/about
register(/^\/settings$/, 'settings', renderSettings);
register(/^\/about$/, 'about', renderAbout);

const sidebarNav = document.getElementById('sidebar-nav');
let currentModule = null;

/** 侧栏：顶部模块切换器 + 当前模块子导航 + 全局（设置/关于） */
function renderSidebar(modId) {
  const mod = MODULES.find(m => m.id === modId) || MODULES[0];
  sidebarNav.innerHTML = `
    <div class="module-switch">
      ${MODULES.map(m => `
        <button class="module-btn ${m.id === mod.id ? 'active' : ''}" data-mod="${m.id}" title="切换到 ${m.name}">
          <span class="ico">${m.icon}</span><span>${m.name}</span>
        </button>`).join('')}
    </div>
    <div class="nav-group-label">${mod.name} · 数据库</div>
    ${mod.pages.filter(p => !p.hidden).map(p => `
      <button class="nav-item" data-route="${mod.id}/${p.route}" onclick="location.hash='#/${mod.id}/${p.route}'">
        <span class="ico">${p.icon}</span>${p.label}
        ${p.chip ? `<span class="chip">${p.chip}</span>` : ''}
      </button>`).join('')}
    <div class="nav-group-label">通用</div>
    <button class="nav-item" data-route="settings" onclick="location.hash='#/settings'">
      <span class="ico">⚙️</span>设置
    </button>
    <button class="nav-item" data-route="about" onclick="location.hash='#/about'">
      <span class="ico">📖</span>关于与策略
    </button>
  `;
  sidebarNav.querySelectorAll('.module-btn').forEach(el => {
    el.onclick = () => {
      const id = el.dataset.mod;
      if (id === currentModule) return;
      setSetting('gameModule', id);
      // 先切换游戏：侧栏与内容立即重建（以当前主题色渲染，内容随 pageIn 淡入），
      // 再变换颜色：下一帧挂 theme-anim 并切 data-theme → 全站从旧色渐变到新主题色。
      syncModule(id);
      location.hash = `#/${id}/home`;
      setTimeout(() => applyTheme(id), 60);
    };
  });
}

/** 应用模块：侧栏重建（幂等）。主题色由 applyTheme 独立控制——
 *  模块切换时「先切内容、后渐变换色」，两者解耦以控制时序。 */
function syncModule(modId) {
  const id = MODULES.some(m => m.id === modId) ? modId : 'pjsk';
  if (id === currentModule) return;
  currentModule = id;
  renderSidebar(id);
}

function moduleOfHash() {
  const m = location.hash.match(/^#\/(pjsk|bandori|onotes|sc)(\/|$)/);
  return m ? m[1] : null;
}

// 旧链接兼容：#/home → #/pjsk/home 等（#/card/:id 详情保持不变）。
// 初始加载与 hashchange 都检查，覆盖旧书签/手输地址两种场景。
// ⚠️ 空 hash（裸域名 127.0.0.1:8819）按 '/home' 处理——router 对空 hash 也是兜底 '/home'，
//    迁移表必须含这一键，否则刚进入网页会显示「页面不存在」。
const LEGACY_HASH = { '': '/pjsk/home', '/home': '/pjsk/home', '/cards': '/pjsk/cards' };

function migrateHashNow() {
  const path = location.hash.replace(/^#/, '') || '/home';
  if (LEGACY_HASH[path]) location.replace('#' + LEGACY_HASH[path]);
}

migrateHashNow();

// 初始化：渲染前先把主题色对齐（无动画，避免首帧闪烁），再重建侧栏
const __initialModule = moduleOfHash() || getSettings().gameModule || 'pjsk';
applyTheme(__initialModule, false);
syncModule(__initialModule);

// hashchange：先同步模块/主题（此监听先于 router.start 注册，先执行重建侧栏，
// 之后 router.render 才在新建的侧栏 DOM 上设置高亮）
window.addEventListener('hashchange', () => {
  migrateHashNow();
  const mod = moduleOfHash();
  if (mod && mod !== currentModule) {
    // 经由 hash 直接跨模块跳转（手输/旧链接）：先切内容，再无动画对齐主题
    syncModule(mod);
    applyTheme(mod, false);
  } else {
    syncModule(mod || currentModule);
  }
});

// 侧边栏底部状态灯
fetchStatus().then(s => {
  const foot = document.getElementById('sidebar-foot');
  if (!foot) return;
  const t = s.lastRun ? new Date(s.lastRun).toLocaleString('zh-CN', { hour12: false }) : '尚未运行';
  const ok = s.lastResult !== 'partial';
  foot.innerHTML = `<span class="dot" style="background:${ok ? '#22c55e' : '#f59e0b'};box-shadow:0 0 0 3px ${ok ? 'rgba(34,197,94,.15)' : 'rgba(245,158,11,.2)'}"></span>上次抓取：${t}`;
}).catch(() => {});

// 统一下载面板（左下角，跨页面常驻）
initDlPanel();

start();
