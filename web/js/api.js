// API 层：统一对接 Card Radar v2 REST API（清晰解耦，零硬编码路径拼接）
import { getModule } from './modules/registry.js?v=2.0.0';

async function jsonReq(url, opts = {}) {
  const r = await fetch(url, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `请求失败（HTTP ${r.status}）`);
  return data;
}

export function fetchHealth() {
  return jsonReq('/api/v2/health');
}

export function fetchModules() {
  return jsonReq('/api/v2/modules');
}

export function fetchModuleIndex(modKey) {
  const mod = getModule(modKey);
  return jsonReq(`/api/v2/modules/${mod.apiMod}/index`);
}

export function fetchModuleStatus(modKey) {
  const mod = getModule(modKey);
  return jsonReq(`/api/v2/modules/${mod.apiMod}/status`);
}

export function fetchCardDetail(modKey, id, kind = null) {
  const mod = getModule(modKey);
  const url = mod.compositeKey && kind
    ? `/api/v2/modules/${mod.apiMod}/cards/${encodeURIComponent(kind)}/${id}`
    : `/api/v2/modules/${mod.apiMod}/cards/${id}`;
  return jsonReq(url);
}

// ---- 下载 / 超分 / 批量 / 重试 ----
export function downloadOriginal(cardId, kind, modKey = 'pjsk') {
  const mod = getModule(modKey);
  return fetch('/api/v2/jobs/download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mod: mod.apiMod, cardId: Number(cardId), kind }),
  }).then(r => r.json());
}

export function superresImage(cardId, kind, tier = '4k', engine = 'ai', modKey = 'pjsk') {
  const mod = getModule(modKey);
  return fetch('/api/v2/jobs/superres', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mod: mod.apiMod, cardId: Number(cardId), kind, tier, engine }),
  }).then(r => r.json());
}

export function enqueueBatchJobs(action, items, tier = '4k', engine = 'ai') {
  return jsonReq('/api/v2/jobs/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, items, tier, engine }),
  });
}

export function downloadJobs(mod = '', state = '') {
  const params = new URLSearchParams();
  if (mod) params.set('mod', mod);
  if (state) params.set('state', state);
  const qs = params.toString();
  return jsonReq(`/api/v2/jobs${qs ? '?' + qs : ''}`);
}

export function downloadProgress(jobId) {
  return jsonReq(`/api/v2/jobs/${encodeURIComponent(jobId)}`);
}

export function retryJob(jobId) {
  return jsonReq(`/api/v2/jobs/${encodeURIComponent(jobId)}/retry`, { method: 'POST' });
}

export function removeJob(jobId) {
  return fetch(`/api/v2/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' }).then(r => r.json());
}

export function clearFinishedJobs() {
  return jsonReq('/api/v2/jobs/clear', { method: 'POST' });
}

// ---- ZIP 收藏包导出 ----
export async function exportZipPack(items, groupBy = 'unit', fetchMissing = true) {
  const r = await fetch('/api/v2/export/zip', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items, groupBy, fetchMissing }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.error || `打包导出失败（HTTP ${r.status}）`);
  }
  const cd = r.headers.get('Content-Disposition') || '';
  const mUtf = cd.match(/filename\*=UTF-8''([^;]+)/i);
  const filename = mUtf ? decodeURIComponent(mUtf[1]) : 'card_radar_pack.zip';
  const blob = await r.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    URL.revokeObjectURL(a.href);
    a.remove();
  }, 1000);
  return filename;
}

// ---- 全模块缓存管理 ----
export function cacheStats() {
  return jsonReq('/api/v2/cache');
}

export function cacheClear(mod = 'all') {
  return jsonReq(`/api/v2/cache?mod=${encodeURIComponent(mod)}`, { method: 'DELETE' });
}

// ---- 用户档案（收藏/分组/设置） ----
export function fetchUserProfile() {
  return jsonReq('/api/v2/user-data');
}

export function saveUserProfile(payload) {
  return jsonReq('/api/v2/user-data', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// ---- 数据源可达性探活 ----
export function probeSources(force = false) {
  return jsonReq(`/api/v2/sources/probe${force ? '?force=1' : ''}`);
}

// 兼容别名
export const fetchStatus = () => fetchModuleStatus('pjsk');
export const fetchIndex = () => fetchModuleIndex('pjsk');
