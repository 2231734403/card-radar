// API 层：与本地服务器交互的唯一入口
export async function fetchIndex() {
  const r = await fetch('/api/index');
  if (!r.ok) throw new Error('索引加载失败');
  return r.json();
}

export async function fetchStatus() {
  const r = await fetch('/api/status');
  if (!r.ok) throw new Error('状态接口失败');
  return r.json();
}

export async function fetchCardDetail(id) {
  const r = await fetch(`/api/cards/${id}`);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || '详情加载失败');
  return r.json();
}

/** 创建原图下载任务（服务端抓取 PNG 并写入系统「下载」文件夹），返回 jobId。
 *  mod: pjsk（主备源竞速）| bandori（bestdori）| onotes（bdon.moe，card/support 双类）| shinycolors */
export async function downloadOriginal(cardId, kind, mod = 'pjsk') {
  const base = mod === 'bandori' ? '/api/bandori/download'
    : mod === 'onotes' ? '/api/onotes/download'
    : mod === 'shinycolors' ? '/api/shinycolors/download' : '/api/download';
  const r = await fetch(`${base}/${cardId}/${kind}`, { method: 'POST' });
  return r.json();
}

/** 轮询单个下载任务进度 */
export async function downloadProgress(jobId) {
  const r = await fetch(`/api/download-progress/${jobId}`);
  if (!r.ok) throw new Error('进度查询失败');
  return r.json();
}

/** 全部下载任务列表（统一下载面板用） */
export async function downloadJobs() {
  const r = await fetch('/api/download-jobs');
  if (!r.ok) throw new Error('下载列表获取失败');
  return r.json();
}

/** 超分（tier: 2k | 4k；engine: ai | pillow；mod: pjsk | bandori | onotes，档位与引擎由设置页决定） */
export async function superresImage(cardId, kind, tier = "4k", engine = "ai", mod = 'pjsk') {
  const base = mod === 'bandori' ? '/api/bandori/superres'
    : mod === 'onotes' ? '/api/onotes/superres'
    : mod === 'shinycolors' ? '/api/shinycolors/superres' : '/api/superres';
  const r = await fetch(`${base}/${cardId}/${kind}?target=${encodeURIComponent(tier)}&engine=${encodeURIComponent(engine)}`,
    { method: 'POST' });
  return r.json();
}

/** 图片缓存统计 */
export async function cacheStats() {
  const r = await fetch('/api/cache-stats');
  if (!r.ok) throw new Error('缓存统计失败');
  return r.json();
}

/** 清除图片缓存（data/originals） */
export async function cacheClear() {
  const r = await fetch('/api/cache-clear', { method: 'POST' });
  if (!r.ok) throw new Error('缓存清除失败');
  return r.json();
}

/** 删除指定下载任务记录（下载面板条目「单独删除」用） */
export async function removeJob(jobId) {
  const r = await fetch(`/api/job-remove/${encodeURIComponent(jobId)}`, { method: 'POST' });
  return r.json();
}

/** 邦多利模块：索引 / 状态 / 单卡详情（bestdori 数据） */
export async function fetchBandoriIndex() {
  const r = await fetch('/api/bandori/index');
  if (!r.ok) throw new Error('邦多利索引加载失败');
  return r.json();
}

export async function fetchBandoriStatus() {
  const r = await fetch('/api/bandori/status');
  if (!r.ok) throw new Error('邦多利状态接口失败');
  return r.json();
}

export async function fetchBandoriCardDetail(id) {
  const r = await fetch(`/api/bandori/cards/${id}`);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || '详情加载失败');
  return r.json();
}

// 闪耀色彩模块
export async function fetchShinyIndex() {
  const r = await fetch('/api/shinycolors/index');
  if (!r.ok) throw new Error('闪耀色彩索引加载失败');
  return r.json();
}

export async function fetchShinyStatus() {
  const r = await fetch('/api/shinycolors/status');
  if (!r.ok) throw new Error('闪耀色彩状态接口失败');
  return r.json();
}

export async function fetchShinyCardDetail(id) {
  const r = await fetch(`/api/shinycolors/cards/${id}`);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || '详情加载失败');
  return r.json();
}

// Our Notes 模块（bdon.moe：角色卡 + 支援卡）
export async function fetchOnotesIndex() {
  const r = await fetch('/api/onotes/index');
  if (!r.ok) throw new Error('Our Notes 索引加载失败');
  return r.json();
}

export async function fetchOnotesStatus() {
  const r = await fetch('/api/onotes/status');
  if (!r.ok) throw new Error('Our Notes 状态接口失败');
  return r.json();
}

export async function fetchOnotesCardDetail(id, kind = 'card') {
  const r = await fetch(`/api/onotes/cards/${id}/${kind}`);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || '详情加载失败');
  return r.json();
}
