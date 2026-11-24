// 泛型化多模块数据仓库 + 统一高性能筛选引擎
// 消除四份重复缓存代码；支持收藏筛选、近 N 天新卡筛选与严格 String() 稀有度比较（严防 T13）。
import { fetchModuleIndex } from './api.js?v=2.0.0';
import { getModule } from './modules/registry.js?v=2.0.0';

const _cache = new Map();    // apiMod -> {updatedAt, cards, characters?, ...}
const _inflight = new Map(); // apiMod -> Promise

export async function ensureModuleIndex(modKey, force = false) {
  const mod = getModule(modKey);
  if (!force && _cache.has(mod.apiMod)) return _cache.get(mod.apiMod);
  if (!force && _inflight.has(mod.apiMod)) return _inflight.get(mod.apiMod);
  const p = fetchModuleIndex(mod.apiMod)
    .then(data => {
      _cache.set(mod.apiMod, data);
      _inflight.delete(mod.apiMod);
      return data;
    })
    .catch(err => {
      _inflight.delete(mod.apiMod);
      throw err;
    });
  _inflight.set(mod.apiMod, p);
  return p;
}

export function getModuleIndex(modKey) {
  return _cache.get(getModule(modKey).apiMod) || null;
}

export function getModuleCards(modKey) {
  return getModuleIndex(modKey)?.cards || [];
}

export function getModuleUpdatedAt(modKey) {
  return getModuleIndex(modKey)?.updatedAt || 0;
}

export function getModuleCard(modKey, id, kind = null) {
  const mod = getModule(modKey);
  const cards = getModuleCards(mod.apiMod);
  const numId = Number(id);
  if (mod.compositeKey && kind) {
    const want = kind === 'support' ? 'support' : 'card';
    return cards.find(c => c.id === numId && (c.cardKind === 'support' ? 'support' : 'card') === want);
  }
  return cards.find(c => c.id === numId);
}

export function getModuleCharacters(modKey) {
  const idx = getModuleIndex(modKey);
  if (idx?.characters?.length) {
    return idx.characters.map(c => [c.id, c.name]).sort((a, b) => a[0] - b[0]);
  }
  const seen = new Map();
  for (const c of getModuleCards(modKey)) {
    if (c.characterId != null && !seen.has(c.characterId)) {
      seen.set(c.characterId, c.characterName || `角色${c.characterId}`);
    }
  }
  return [...seen.entries()].sort((a, b) => a[0] - b[0]);
}

/**
 * 通用筛选 + 排序（纯函数，易于自动化单测）
 * @param {object} f - { q, unit, characterId, attr, rarity, kind, sort, favOnly, recentDays }
 * @param {Array} cards - 卡面数组
 * @param {object} [opts] - { favSet?: Set<string>, keyFn?: (card)=>string, nowMs?: number }
 */
export function filterCards(f, cards = [], opts = {}) {
  let list = cards.slice();
  const q = (f.q || '').trim().toLowerCase();
  if (q) {
    list = list.filter(c =>
      (c.prefix || '').toLowerCase().includes(q)
      || (c.characterName || '').toLowerCase().includes(q)
      || (c.characterFullName || '').toLowerCase().includes(q)
      || (c.unitName || '').toLowerCase().includes(q)
      || String(c.id).includes(q)
      || (c.skillName || '').toLowerCase().includes(q));
  }
  if (f.unit) list = list.filter(c => c.unitName === f.unit);
  if (f.characterId) list = list.filter(c => String(c.characterId) === String(f.characterId));
  if (f.attr) list = list.filter(c => c.attr === f.attr);
  if (f.rarity === 'birthday') {
    list = list.filter(c => c.rarityType === 'rarity_birthday');
  } else if (f.rarity) {
    // 严格按 String 比较，杜绝 Number('SSR')=NaN 导致闪彩/Our Notes 筛空（T13）
    list = list.filter(c => String(c.rarity) === String(f.rarity));
  }
  if (f.kind) list = list.filter(c => String(c.cardKind || '') === String(f.kind));
  if (f.favOnly && opts.favSet && opts.keyFn) {
    list = list.filter(c => opts.favSet.has(opts.keyFn(c)));
  }
  if (f.recentDays && Number(f.recentDays) > 0) {
    const now = opts.nowMs || Date.now();
    const cutoff = now - Number(f.recentDays) * 86400 * 1000;
    const maxFuture = now + 90 * 86400 * 1000; // 排除 2100 年占位时间戳
    list = list.filter(c => {
      const ts = Number(c.releaseAt || c.releaseJp || 0);
      return ts >= cutoff && ts <= maxFuture;
    });
  }
  if (f.sort === 'id_asc') {
    list.sort((a, b) => a.id - b.id);
  } else if (f.sort === 'release_desc') {
    list.sort((a, b) => (b.releaseAt || 0) - (a.releaseAt || 0) || b.id - a.id);
  } else if (f.sort === 'release_asc') {
    list.sort((a, b) => (a.releaseAt || 0) - (b.releaseAt || 0) || a.id - b.id);
  } else {
    list.sort((a, b) => b.id - a.id);
  }
  return list;
}
