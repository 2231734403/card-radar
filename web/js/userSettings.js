// 用户偏好设置 + 收藏夹与分组状态管理
// 本地 localStorage 即时生效，同时静默双向同步到服务端 data/user_profile.json（换浏览器/清缓存不丢数据）。
import { fetchUserProfile, saveUserProfile } from './api.js?v=2.0.0';
import { getModule } from './modules/registry.js?v=2.0.0';

const SETTINGS_KEY = 'cardRadar.settings';
const LEGACY_SETTINGS_KEY = 'pjsk_settings';
const FAV_KEY = 'cardRadar.favorites';
const GROUPS_KEY = 'cardRadar.groups';

const DEFAULTS = {
  gameModule: 'pjsk',
  srTarget: '4k',
  srEngine: 'ai',
  colorMode: 'light', // light | dark | auto
  copyrightAck: false,
};

let _syncTimer = null;
let _favorites = loadLocalJson(FAV_KEY, {});
let _groups = loadLocalJson(GROUPS_KEY, ['精选', '待超分', '壁纸']);

function loadLocalJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    return parsed ?? fallback;
  } catch {
    return fallback;
  }
}

function saveLocalJson(key, val) {
  try {
    localStorage.setItem(key, JSON.stringify(val));
  } catch {
    // 隐私模式下忽略存储异常
  }
}

export function getSettings() {
  const legacy = loadLocalJson(LEGACY_SETTINGS_KEY, {});
  const cur = loadLocalJson(SETTINGS_KEY, {});
  return { ...DEFAULTS, ...legacy, ...cur };
}

export function setSetting(key, value) {
  const s = getSettings();
  s[key] = value;
  saveLocalJson(SETTINGS_KEY, s);
  saveLocalJson(LEGACY_SETTINGS_KEY, s);
  window.dispatchEvent(new CustomEvent('settings:changed', { detail: { key, value } }));
  scheduleSync();
}

export function favKey(modKey, cardId, kind = null) {
  const mod = getModule(modKey);
  const k = mod.compositeKey ? (kind === 'support' ? 'support' : 'card') : 'card';
  return `${mod.apiMod}:${k}:${Number(cardId)}`;
}

export function getFavorites() {
  return { ..._favorites };
}

export function getGroups() {
  return [..._groups];
}

export function isFavorite(modKey, cardId, kind = null) {
  return Boolean(_favorites[favKey(modKey, cardId, kind)]);
}

export function getFavoriteEntry(modKey, cardId, kind = null) {
  return _favorites[favKey(modKey, cardId, kind)] || null;
}

export function toggleFavorite(modKey, cardId, kind = null, group = '') {
  const mod = getModule(modKey);
  const k = mod.compositeKey ? (kind === 'support' ? 'support' : 'card') : 'card';
  const key = `${mod.apiMod}:${k}:${Number(cardId)}`;
  let added = false;
  if (_favorites[key]) {
    delete _favorites[key];
  } else {
    _favorites[key] = {
      mod: mod.apiMod,
      id: Number(cardId),
      kind: k,
      group: group || _groups[0] || '精选',
      addedAt: Date.now(),
    };
    added = true;
  }
  saveLocalJson(FAV_KEY, _favorites);
  window.dispatchEvent(new CustomEvent('favorites:changed', { detail: { key, added } }));
  scheduleSync();
  return added;
}

export function setFavoriteGroup(modKey, cardId, kind, group) {
  const key = favKey(modKey, cardId, kind);
  if (!_favorites[key]) return;
  _favorites[key].group = group;
  saveLocalJson(FAV_KEY, _favorites);
  window.dispatchEvent(new CustomEvent('favorites:changed', { detail: { key, group } }));
  scheduleSync();
}

export function addGroup(name) {
  const clean = String(name || '').trim().slice(0, 24);
  if (!clean || _groups.includes(clean)) return false;
  _groups.push(clean);
  saveLocalJson(GROUPS_KEY, _groups);
  window.dispatchEvent(new CustomEvent('favorites:changed', { detail: { groups: _groups } }));
  scheduleSync();
  return true;
}

export function removeGroup(name) {
  if (_groups.length <= 1) return false;
  _groups = _groups.filter(g => g !== name);
  const fallback = _groups[0];
  for (const entry of Object.values(_favorites)) {
    if (entry.group === name) entry.group = fallback;
  }
  saveLocalJson(GROUPS_KEY, _groups);
  saveLocalJson(FAV_KEY, _favorites);
  window.dispatchEvent(new CustomEvent('favorites:changed', { detail: { groups: _groups } }));
  scheduleSync();
  return true;
}

export function replaceUserData(profile) {
  if (profile.favorites && typeof profile.favorites === 'object') {
    _favorites = { ...profile.favorites };
    saveLocalJson(FAV_KEY, _favorites);
  }
  if (Array.isArray(profile.groups) && profile.groups.length) {
    _groups = [...new Set(profile.groups.map(x => String(x).trim()).filter(Boolean))];
    saveLocalJson(GROUPS_KEY, _groups);
  }
  if (profile.settings && typeof profile.settings === 'object') {
    const merged = { ...getSettings(), ...profile.settings };
    saveLocalJson(SETTINGS_KEY, merged);
  }
  window.dispatchEvent(new CustomEvent('favorites:changed', { detail: { synced: true } }));
  scheduleSync();
}

function scheduleSync() {
  clearTimeout(_syncTimer);
  _syncTimer = setTimeout(() => {
    saveUserProfile({
      favorites: _favorites,
      groups: _groups,
      settings: getSettings(),
    }).catch(() => { /* 离线时保持本地存储，联网后再同步 */ });
  }, 450);
}

/** 启动时与服务端 data/user_profile.json 合并，防清缓存丢收藏 */
export async function hydrateUserData() {
  try {
    const remote = await fetchUserProfile();
    if (!remote) return;
    let changed = false;
    if (remote.favorites && typeof remote.favorites === 'object') {
      const merged = { ...remote.favorites, ..._favorites };
      if (Object.keys(merged).length !== Object.keys(_favorites).length) {
        _favorites = merged;
        saveLocalJson(FAV_KEY, _favorites);
        changed = true;
      }
    }
    if (Array.isArray(remote.groups) && remote.groups.length) {
      const mergedGroups = [...new Set([..._groups, ...remote.groups])];
      if (mergedGroups.length !== _groups.length) {
        _groups = mergedGroups;
        saveLocalJson(GROUPS_KEY, _groups);
        changed = true;
      }
    }
    if (changed) {
      window.dispatchEvent(new CustomEvent('favorites:changed', { detail: { synced: true } }));
    }
    // 若本地有新收藏而服务端为空，顺手回写备份
    if (Object.keys(_favorites).length > Object.keys(remote.favorites || {}).length) {
      scheduleSync();
    }
  } catch {
    // 服务暂不可用时静默回退本地
  }
}
