// Card Radar Service Worker：缓存已访问缩略图、角标图标与最近一次索引，断网照常浏览图鉴
const CACHE_NAME = 'card-radar-v2.0.0';

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  const p = url.pathname;
  // 缩略图与静态角标：Cache-First（已看过一次即离线可用）
  if (p.includes('/thumbs/') || p.startsWith('/img/')) {
    event.respondWith(
      caches.open(CACHE_NAME).then(cache =>
        cache.match(req).then(hit => {
          if (hit) return hit;
          return fetch(req).then(resp => {
            if (resp && resp.ok) cache.put(req, resp.clone());
            return resp;
          });
        })
      )
    );
    return;
  }

  // 模块索引 JSON：Network-First，断网回退缓存
  if (p.endsWith('/index') && p.startsWith('/api/')) {
    event.respondWith(
      caches.open(CACHE_NAME).then(cache =>
        fetch(req).then(resp => {
          if (resp && resp.ok) cache.put(req, resp.clone());
          return resp;
        }).catch(() => cache.match(req))
      )
    );
  }
});
