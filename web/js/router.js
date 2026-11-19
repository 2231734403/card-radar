// 轻量 hash 路由：#/cards / #/card/:id / #/home ...
const routes = []; // {pattern, name, handler}

export function register(pattern, name, handler) {
  routes.push({ pattern, name, handler });
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
  const path = (location.hash.replace(/^#/, '') || '/home');
  const hit = match(path);
  // 导航高亮
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
    app.innerHTML = `<div class="loading-block">加载失败：${e.message}</div>`;
  }
}

export function start() {
  window.addEventListener('hashchange', render);
  render();
}
