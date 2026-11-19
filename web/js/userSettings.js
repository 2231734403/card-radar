// 用户设置：localStorage 持久化，跨页面可用。
// 新增设置项：在 DEFAULTS 里加默认值即可，各页面用 getSettings() 读取。
const KEY = "pjsk_settings";

const DEFAULTS = {
  gameModule: "pjsk", // 当前游戏模块：pjsk | bandori | sc（决定侧栏与全局主题色）
  srTarget: "4k",     // 超分档位：2k | 4k
  srEngine: "ai",     // 超分引擎：ai（默认 · 独立显卡 Vulkan）| pillow（经典备选）
};

export function getSettings() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || "{}") };
  } catch (e) {
    return { ...DEFAULTS };
  }
}

export function setSetting(key, value) {
  const s = getSettings();
  s[key] = value;
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch (e) { /* 隐私模式等写入失败：仅本次会话生效 */ }
  window.dispatchEvent(new CustomEvent("settings:changed", { detail: { key, value } }));
}
