// 轻量 hash 路由：支持正则参数捕获与页面离开清理钩子（onLeave），防止监听器泄漏
const routes = [];
let currentCleanup = null;

export function register(pattern, name, handler) {
  routes.push({ pattern, name, handler });
}

export function setPageCleanup(fn) {
  currentCleanup = typeof fn === 'function' ? fn : null;
}

function runCleanup() {
  if (currentCleanup) {
    try { currentCleanup(); } catch { /* 忽略清理异常 */ }
    currentCleanup = null;
  }
}

function match(path) {
  for (const r of routes) {
    const m = path.match(r.pattern);
    if (m) return { r, m };
  }
  return null;
}

export function navigate(hash) {
  if (location.hash === hash) render();
  else location.hash = hash;
}

export async function render() {
  const app = document.getElementById('app');
  if (!app) return;
  runCleanup();
  const path = location.hash.replace(/^#/, '').split('?')[0] || '/pjsk/home';
  const hit = match(path);
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.route === (hit?.r.name ?? ''));
  });
  if (!hit) {
    app.innerHTML = '<div class="loading-block">页面不存在，<a href="#/pjsk/home">返回首页</a></div>';
    return;
  }
  try {
    await hit.r.handler(app, ...hit.m.slice(1));
  } catch (e) {
    app.innerHTML = `<div class="loading-block">加载失败：${String(e?.message || e)}</div>`;
  }
}

export function start() {
  window.addEventListener('hashchange', render);
  render();
}
