// 数据仓库：缓存卡牌索引（pjsk + bandori + onotes + shinycolors 多模块），提供筛选与查找
import { fetchIndex, fetchBandoriIndex, fetchShinyIndex, fetchOnotesIndex } from './api.js?v=1.16.1';

let _index = null; // {updatedAt, cards:[...]}
let _loading = null;
let _bIndex = null;
let _bLoading = null;

export async function ensureIndex() {
  if (_index) return _index;
  if (!_loading) {
    _loading = fetchIndex().then(d => { _index = d; return d; });
  }
  _index = await _loading;
  return _index;
}

export function getCards() {
  return _index?.cards || [];
}

export function getCard(id) {
  return getCards().find(c => c.id === Number(id));
}

export function getUpdatedAt() {
  return _index?.updatedAt || 0;
}

export function characters() {
  const seen = new Map();
  for (const c of getCards()) {
    if (!seen.has(c.characterId)) seen.set(c.characterId, c.characterName || `角色${c.characterId}`);
  }
  return [...seen.entries()].sort((a, b) => a[0] - b[0]);
}

// ---------------- 邦多利模块 ----------------
export async function ensureBandoriIndex() {
  if (_bIndex) return _bIndex;
  if (!_bLoading) {
    _bLoading = fetchBandoriIndex().then(d => { _bIndex = d; return d; });
  }
  _bIndex = await _bLoading;
  return _bIndex;
}

export function getBandoriCards() {
  return _bIndex?.cards || [];
}

export function getBandoriCard(id) {
  return getBandoriCards().find(c => c.id === Number(id));
}

export function getBandoriUpdatedAt() {
  return _bIndex?.updatedAt || 0;
}

export function bandoriCharacters() {
  const seen = new Map();
  for (const c of getBandoriCards()) {
    if (!seen.has(c.characterId)) seen.set(c.characterId, c.characterName || `角色${c.characterId}`);
  }
  return [...seen.entries()].sort((a, b) => a[0] - b[0]);
}

// ---------------- 闪耀色彩模块 ----------------
let _sIndex = null;
let _sLoading = null;

export async function ensureShinyIndex() {
  if (_sIndex) return _sIndex;
  if (!_sLoading) {
    _sLoading = fetchShinyIndex().then(d => { _sIndex = d; return d; });
  }
  _sIndex = await _sLoading;
  return _sIndex;
}

export function getShinyCards() {
  return _sIndex?.cards || [];
}

export function getShinyCard(id) {
  return getShinyCards().find(c => c.id === Number(id));
}

export function getShinyUpdatedAt() {
  return _sIndex?.updatedAt || 0;
}

// ---------------- Our Notes 模块（bdon.moe）----------------
// cards 数组含角色卡（cardKind='card'）与支援卡（cardKind='support'）两套序列；
// 角色筛选直接用索引自带 characters（26 人，含乐队/分工/CV/生日）
let _oIndex = null;
let _oLoading = null;

export async function ensureOnotesIndex() {
  if (_oIndex) return _oIndex;
  if (!_oLoading) {
    _oLoading = fetchOnotesIndex().then(d => { _oIndex = d; return d; });
  }
  _oIndex = await _oLoading;
  return _oIndex;
}

export function getOnotesCards() {
  return _oIndex?.cards || [];
}

export function getOnotesCard(id, kind = null) {
  // 角色卡/支援卡 ID 序列重叠：指定 kind 时按复合键查找
  const want = kind === 'support' ? 'support' : kind === 'card' ? 'card' : null;
  return getOnotesCards().find(c => c.id === Number(id)
    && (!want || (c.cardKind === 'support' ? 'support' : 'card') === want));
}

export function getOnotesUpdatedAt() {
  return _oIndex?.updatedAt || 0;
}

export function onotesCharacters() {
  const chars = _oIndex?.characters || [];
  return chars.map(c => [c.id, c.name]).sort((a, b) => a[0] - b[0]);
}

export function shinyCharacters() {
  const seen = new Map();
  for (const c of getShinyCards()) {
    if (!seen.has(c.characterId)) seen.set(c.characterId, c.characterName || `角色${c.characterId}`);
  }
  return [...seen.entries()].sort((a, b) => a[0] - b[0]);
}

/**
 * 筛选 + 排序（pjsk/bandori/shinycolors 通用；cards 参数指定数据集）
 * f: { q, unit, characterId, attr, rarity, kind, sort }
 * rarity 统一按字符串比较（pjsk 是数字星数，shinycolors 是 'SSR' 等字符串——
 * 曾因 Number('SSR')=NaN 导致闪彩一点稀有度就筛空）
 */
export function filterCards(f, cards = getCards()) {
  let list = cards.slice();
  const q = (f.q || '').trim().toLowerCase();
  if (q) {
    list = list.filter(c =>
      (c.prefix || '').toLowerCase().includes(q)
      || (c.characterName || '').toLowerCase().includes(q)
      || (c.characterFullName || '').toLowerCase().includes(q)
      || String(c.id).includes(q)
      || (c.skillName || '').toLowerCase().includes(q));
  }
  if (f.unit) list = list.filter(c => c.unitName === f.unit);
  if (f.characterId) list = list.filter(c => c.characterId === Number(f.characterId));
  if (f.attr) list = list.filter(c => c.attr === f.attr);
  if (f.rarity === 'birthday') list = list.filter(c => c.rarityType === 'rarity_birthday');
  else if (f.rarity) list = list.filter(c => String(c.rarity) === String(f.rarity));
  if (f.kind) list = list.filter(c => (c.cardKind || '') === f.kind);
  if (f.sort === 'id_asc') list.sort((a, b) => a.id - b.id);
  else if (f.sort === 'release_desc') list.sort((a, b) => (b.releaseAt || 0) - (a.releaseAt || 0) || b.id - a.id);
  else list.sort((a, b) => b.id - a.id);
  return list;
}
