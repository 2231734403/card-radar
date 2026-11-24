// Card Radar v2.0.0 前端主入口
// 职责：模块注册表驱动侧栏与路由 + 主题/深色模式切换 + 响应式抽屉 + 全局快捷键 + PWA SW 注册
import { MODULES, getModule } from './modules/registry.js?v=2.0.0';
import { register, start } from './router.js?v=2.0.0';
import { renderHome } from './pages/home.js?v=2.0.0';
import { renderCards } from './pages/cards.js?v=2.0.0';
import { renderDetail } from './pages/detail.js?v=2.0.0';
import { renderFavorites } from './pages/favorites.js?v=2.0.0';
import { renderSettings } from './pages/settings.js?v=2.0.0';
import { renderAbout } from './pages/about.js?v=2.0.0';
import { fetchHealth } from './api.js?v=2.0.0';
import { initDlPanel } from './dlpanel.js?v=2.0.0';
import { applyTheme, applyColorMode, currentEffectiveMode } from './theme.js?v=2.0.0';
import { getSettings, setSetting, getFavorites, hydrateUserData } from './userSettings.js?v=2.0.0';
import { closeTopModal, openShortcutsModal, toast } from './ui.js?v=2.0.0';

// 1. 注册全部模块路由（首页 / 图鉴 / 详情）
register(/^\/card\/(\d+)$/, 'pjsk/cards', (app, id) => renderDetail(app, 'pjsk', id));
register(/^\/pjsk\/card\/(\d+)$/, 'pjsk/cards', (app, id) => renderDetail(app, 'pjsk', id));
register(/^\/bandori\/card\/(\d+)$/, 'bandori/cards', (app, id) => renderDetail(app, 'bandori', id));
register(/^\/onotes\/card\/(card|support)\/(\d+)$/, 'onotes/cards', (app, kind, id) => renderDetail(app, 'onotes', id, kind));
register(/^\/sc\/card\/(\d+)$/, 'sc/cards', (app, id) => renderDetail(app, 'sc', id));

for (const mod of MODULES) {
  register(new RegExp(`^\\/${mod.routeId}\\/home$`), `${mod.routeId}/home`, app => renderHome(app, mod.routeId));
  register(new RegExp(`^\\/${mod.routeId}\\/cards$`), `${mod.routeId}/cards`, app => renderCards(app, mod.routeId));
}

// 2. 全局页面路由
register(/^\/favorites$/, 'favorites', renderFavorites);
register(/^\/settings$/, 'settings', renderSettings);
register(/^\/about$/, 'about', renderAbout);

const sidebarNav = document.getElementById('sidebar-nav');
const sidebarEl = document.getElementById('sidebar');
const maskEl = document.getElementById('sidebar-mask');
let currentModule = null;

function closeDrawer() {
  sidebarEl?.classList.remove('open');
  maskEl?.classList.remove('open');
}

function toggleDrawer() {
  sidebarEl?.classList.toggle('open');
  maskEl?.classList.toggle('open');
}

function renderSidebar(modId) {
  const mod = getModule(modId);
  const favCount = Object.keys(getFavorites()).length;
  sidebarNav.innerHTML = `
    <div class="module-switch">
      ${MODULES.map(m => `
        <button class="module-btn ${m.routeId === mod.routeId ? 'active' : ''}" data-mod="${m.routeId}" title="切换到 ${m.name}">
          <span class="ico">${m.icon}</span><span>${m.name}</span>
        </button>`).join('')}
    </div>
    <div class="nav-group-label">${mod.name} · 数据库</div>
    <button class="nav-item" data-route="${mod.routeId}/home" data-go="#/${mod.routeId}/home">
      <span class="ico">🏠</span>首页
    </button>
    <button class="nav-item" data-route="${mod.routeId}/cards" data-go="#/${mod.routeId}/cards">
      <span class="ico">🃏</span>卡面图鉴
    </button>
    <div class="nav-group-label">通用</div>
    <button class="nav-item" data-route="favorites" data-go="#/favorites">
      <span class="ico">⭐</span>我的收藏
      ${favCount ? `<span class="chip" id="nav-fav-count">${favCount}</span>` : '<span class="chip" id="nav-fav-count" style="display:none">0</span>'}
    </button>
    <button class="nav-item" data-route="settings" data-go="#/settings">
      <span class="ico">⚙️</span>设置
    </button>
    <button class="nav-item" data-route="about" data-go="#/about">
      <span class="ico">📖</span>关于与策略
    </button>
  `;

  sidebarNav.querySelectorAll('.nav-item[data-go]').forEach(btn => {
    btn.onclick = () => {
      closeDrawer();
      location.hash = btn.dataset.go;
    };
  });

  sidebarNav.querySelectorAll('.module-btn').forEach(el => {
    el.onclick = () => {
      const id = el.dataset.mod;
      closeDrawer();
      if (id === currentModule) return;
      setSetting('gameModule', id);
      syncModule(id);
      location.hash = `#/${id}/home`;
      // 先切内容，60ms 后平滑过渡主题色
      setTimeout(() => applyTheme(id, true), 60);
    };
  });
}

function updateFavBadge() {
  const el = document.getElementById('nav-fav-count');
  if (!el) return;
  const n = Object.keys(getFavorites()).length;
  el.textContent = n;
  el.style.display = n ? '' : 'none';
}

function syncModule(modId) {
  const mod = getModule(modId);
  if (mod.routeId === currentModule) return;
  currentModule = mod.routeId;
  renderSidebar(mod.routeId);
}

function moduleOfHash() {
  const m = location.hash.match(/^#\/(pjsk|bandori|onotes|sc)(\/|$)/);
  if (m) return m[1];
  if (/^#\/card\/\d+/.test(location.hash)) return 'pjsk';
  return null;
}

// 严守 T11：空 hash 与旧链接兼容迁移
const LEGACY_HASH = { '': '/pjsk/home', '/home': '/pjsk/home', '/cards': '/pjsk/cards' };
function migrateHashNow() {
  const raw = location.hash.replace(/^#/, '').split('?')[0];
  if (Object.prototype.hasOwnProperty.call(LEGACY_HASH, raw)) {
    location.replace('#' + LEGACY_HASH[raw]);
  }
}

function toggleColorModeQuick() {
  const next = currentEffectiveMode() === 'dark' ? 'light' : 'dark';
  setSetting('colorMode', next);
  applyColorMode(next, true);
  toast(next === 'dark' ? '已切换至深色模式 🌙' : '已切换至浅色模式 ☀️');
}

// 初始化主题与模式（首帧无动画防闪烁）
migrateHashNow();
const initialSettings = getSettings();
const initialMod = moduleOfHash() || initialSettings.gameModule || 'pjsk';
applyColorMode(initialSettings.colorMode || 'light', false);
applyTheme(initialMod, false);
syncModule(initialMod);

// 移动端抽屉与深色模式按钮
document.getElementById('mobile-menu-btn')?.addEventListener('click', toggleDrawer);
maskEl?.addEventListener('click', closeDrawer);
document.getElementById('mode-toggle-btn')?.addEventListener('click', toggleColorModeQuick);
document.getElementById('mobile-mode-btn')?.addEventListener('click', toggleColorModeQuick);
document.getElementById('btn-shortcuts')?.addEventListener('click', openShortcutsModal);

// 监听收藏数与设置变更
window.addEventListener('favorites:changed', updateFavBadge);
window.addEventListener('settings:changed', e => {
  if (e.detail?.key === 'colorMode') {
    applyColorMode(e.detail.value, true);
  }
});

// hashchange 先同步模块，再由 router.start 渲染页面
window.addEventListener('hashchange', () => {
  migrateHashNow();
  closeDrawer();
  const mod = moduleOfHash();
  if (mod && mod !== currentModule) {
    syncModule(mod);
    applyTheme(mod, false);
  }
});

// 全局快捷键：/ 聚焦搜索、Esc 关弹窗、D 切深浅模式、? 快捷键帮助
window.addEventListener('keydown', e => {
  const tag = (e.target?.tagName || '').toLowerCase();
  const inInput = tag === 'input' || tag === 'textarea' || tag === 'select' || e.target?.isContentEditable;

  if (e.key === 'Escape') {
    if (closeTopModal()) return;
    if (inInput) e.target.blur();
    return;
  }
  if (inInput || e.ctrlKey || e.metaKey || e.altKey) return;

  if (e.key === '/') {
    const search = document.getElementById('f-q');
    if (search) {
      e.preventDefault();
      search.focus();
      search.select();
    }
  } else if (e.key === 'd' || e.key === 'D') {
    e.preventDefault();
    toggleColorModeQuick();
  } else if (e.key === '?') {
    e.preventDefault();
    openShortcutsModal();
  }
});

// 侧栏底部健康状态 + 版本显示
fetchHealth().then(h => {
  const foot = document.getElementById('sidebar-foot-status');
  const ver = document.getElementById('sidebar-ver');
  if (ver && h.version) ver.textContent = `v${h.version}`;
  if (!foot) return;
  const anyPartial = (h.modules || []).some(m => m.lastResult === 'partial');
  foot.innerHTML = `<span class="dot" style="background:${anyPartial ? '#f59e0b' : '#22c55e'};box-shadow:0 0 0 3px ${anyPartial ? 'rgba(245,158,11,.2)' : 'rgba(34,197,94,.15)'}"></span>已收录 ${h.totalCards || 0} 张卡面`;
}).catch(() => {
  const foot = document.getElementById('sidebar-foot-status');
  if (foot) foot.innerHTML = '<span class="dot" style="background:#ef4444"></span>本地服务未连接';
});

// 注册 PWA Service Worker（离线缩略图与索引缓存）
if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

// 同步后端用户档案（收藏/分组）、初始化下载面板、启动路由
hydrateUserData();
initDlPanel();
start();
