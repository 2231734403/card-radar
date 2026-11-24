// 四游戏模块统一注册表（单一前端配置真源）
// 扩充新游戏只需在此追加一项，首页/图鉴/详情/侧栏/收藏/主题自动接管。

export const ATTR_COLORS = {
  cool: '#4f8ef7',
  cute: '#f76fa4',
  happy: '#f7a94f',
  pure: '#55c96e',
  mysterious: '#9b6ef7',
};
export const ATTR_NAMES = {
  cool: 'Cool', cute: 'Cute', happy: 'Happy', pure: 'Pure', mysterious: 'Mysterious',
};

export const BANDORI_ATTR_COLORS = {
  powerful: '#ff396a',
  cool: '#49c1e8',
  pure: '#5ee282',
  happy: '#f6a231',
};
export const BANDORI_ATTR_NAMES = {
  powerful: 'Powerful', cool: 'Cool', pure: 'Pure', happy: 'Happy',
};

export const ONOTES_ATTR_COLORS = {
  Red: '#ff396a',
  Blue: '#49c1e8',
  Green: '#5ee282',
  Yellow: '#f6c231',
  Purple: '#9b6ef7',
};
export const ONOTES_ATTR_NAMES = {
  Red: '紅赤', Blue: '紺碧', Green: '翡翠', Yellow: '山吹', Purple: '紫苑',
};
export const ONOTES_RARITY_ICON = {
  R: 'R', SR: 'SR', SSR: 'SSR', BD: 'BD', 特殊: 'EX',
};

export const MODULES = [
  {
    id: 'pjsk',
    apiMod: 'pjsk',
    routeId: 'pjsk',
    name: 'PJSK 卡面',
    shortName: 'PJSK',
    icon: '🐳',
    theme: 'pjsk',
    schedule: '每两周 · 周一 09:00',
    sourceName: 'pjsk.moe（JP 服务器 · 中文显示）',
    heroDesc: '每两周自动同步 pjsk.moe 卡牌数据库（周一 09:00）：低清预览常驻本地，PNG 无损原图按需抓取、绝不冗余占用空间。',
    cardsDesc: '浏览本地镜像的全部 PJSK 卡牌 · 支持两级筛选、批量下载/超分与收藏管理',
    unitLabel: '组合',
    unitOrder: [
      'Leo/need', 'MORE MORE JUMP!', 'Vivid BAD SQUAD',
      'Wonderlands×Showtime', '25时，Nightcord见。', '虚拟歌手',
    ],
    specialUnits: [],
    attrColors: ATTR_COLORS,
    attrNames: ATTR_NAMES,
    rarityChips: [
      { v: '4', label: '4★' }, { v: '3', label: '3★' }, { v: '2', label: '2★' },
      { v: '1', label: '1★' }, { v: 'birthday', label: '生日' },
    ],
    kindLabel: '',
    kindChips: [],
    compositeKey: false,
    emptyCmd: 'scripts\\run_scrape.cmd',
    latestSort: 'id_desc',
    defaultArtKind: c => (c.trainable ? 'after_training' : 'normal'),
    detailHash: c => `#/card/${c.id}`,
    thumbUrl: (c, kind = null) => {
      const k = kind || (c.trainable ? 'after_training' : 'normal');
      return `/api/v2/modules/pjsk/thumbs/${c.id}/${k}`;
    },
    fallbackThumbUrl: c => `/api/v2/modules/pjsk/thumbs/${c.id}/normal`,
  },
  {
    id: 'bandori',
    apiMod: 'bandori',
    routeId: 'bandori',
    name: '邦多利卡面',
    shortName: '邦多利',
    icon: '🎸',
    theme: 'bandori',
    schedule: '每两周 · 周一 09:20',
    sourceName: 'bestdori.com（双服时间 · 简体）',
    heroDesc: '每两周自动同步 BanG Dream!（邦多利）卡面数据库（周一 09:20）：完整记录日服与国服上线时间，PNG 原图按需抓取。',
    cardsDesc: '浏览本地镜像的全部邦多利卡面 · 支持乐团两级筛选、属性筛选与批量处理',
    unitLabel: '乐团',
    unitOrder: [
      "Poppin'Party", 'Afterglow', 'Hello, Happy World!', 'Pastel*Palettes',
      'Roselia', 'Morfonica', 'RAISE A SUILEN', 'MyGO!!!!!',
    ],
    specialUnits: [],
    attrColors: BANDORI_ATTR_COLORS,
    attrNames: BANDORI_ATTR_NAMES,
    rarityChips: [
      { v: '5', label: '5★' }, { v: '4', label: '4★' }, { v: '3', label: '3★' },
      { v: '2', label: '2★' }, { v: '1', label: '1★' },
    ],
    kindLabel: '',
    kindChips: [],
    compositeKey: false,
    emptyCmd: 'scripts\\run_bandori_scrape.cmd',
    latestSort: 'release_desc',
    defaultArtKind: c => (c.trainable ? 'after_training' : 'normal'),
    detailHash: c => `#/bandori/card/${c.id}`,
    thumbUrl: (c, kind = null) => {
      const k = kind || (c.trainable ? 'after_training' : 'normal');
      return `/api/v2/modules/bandori/thumbs/${c.id}/${k}`;
    },
    fallbackThumbUrl: c => `/api/v2/modules/bandori/thumbs/${c.id}/normal`,
  },
  {
    id: 'onotes',
    apiMod: 'onotes',
    routeId: 'onotes',
    name: 'Our Notes 卡面',
    shortName: 'Our Notes',
    icon: '🎶',
    theme: 'onotes',
    schedule: '每两周 · 周一 10:00',
    sourceName: 'bdon.moe（Moenotes · 简体）',
    heroDesc: '每两周自动同步 BanG Dream! Our Notes 数据库（周一 10:00）：角色卡与支援卡双图鉴复合索引，1440×1920 高清无损转出。',
    cardsDesc: '浏览本地镜像的全部 Our Notes 角色卡与支援卡 · 支持五属性与稀有度筛选',
    unitLabel: '乐队',
    unitOrder: ['MyGO!!!!!', 'Ave Mujica', '梦限大MewType', 'millsage', '一家Dumb Rock!'],
    specialUnits: [],
    attrColors: ONOTES_ATTR_COLORS,
    attrNames: ONOTES_ATTR_NAMES,
    rarityChips: [
      { v: 'SSR', label: 'SSR' }, { v: 'SR', label: 'SR' }, { v: 'R', label: 'R' },
      { v: 'BD', label: 'BD' }, { v: '特殊', label: 'EX' },
    ],
    kindLabel: '卡面种类',
    kindChips: [
      { v: 'card', label: '角色卡' }, { v: 'support', label: '支援卡' },
    ],
    compositeKey: true,
    emptyCmd: 'scripts\\run_onotes_scrape.cmd',
    latestSort: 'release_desc',
    defaultArtKind: c => (c.cardKind === 'support' ? 'support' : 'card'),
    detailHash: c => `#/onotes/card/${c.cardKind === 'support' ? 'support' : 'card'}/${c.id}`,
    thumbUrl: (c, kind = null) => {
      const k = kind || (c.cardKind === 'support' ? 'support' : 'card');
      return `/api/v2/modules/onotes/thumbs/${c.id}/${k}`;
    },
    fallbackThumbUrl: c => `/api/v2/modules/onotes/thumbs/${c.id}/${c.cardKind === 'support' ? 'support' : 'card'}`,
  },
  {
    id: 'sc',
    apiMod: 'shinycolors',
    routeId: 'sc',
    name: '闪彩卡面',
    shortName: '闪彩',
    icon: '✨',
    theme: 'sc',
    schedule: '每两周 · 周一 09:40',
    sourceName: 'shinycolors.moe + gameo 2×',
    heroDesc: '每两周自动同步 SHINY COLORS（闪耀色彩）数据库（周一 09:40）：优先抓取 2272×1280 高清档并无损转存 PNG，支持 Fes 特训立绘。',
    cardsDesc: '浏览本地镜像的全部闪耀色彩卡面 · 支持主组合/特殊组合、P/S 卡种与稀有度筛选',
    unitLabel: '组合',
    unitOrder: [
      'illumination STARS', "L'Antica", '放課後クライマックスガールズ',
      'ALSTROEMERIA', 'Straylight', 'noctchill', 'SHHis', 'CoMETIK',
    ],
    specialUnits: ['２８３プロ', 'B小町', '劇団ララライ'],
    attrColors: {},
    attrNames: {},
    rarityChips: [
      { v: 'UR', label: 'UR' }, { v: 'SSR', label: 'SSR' }, { v: 'SR', label: 'SR' },
      { v: 'R', label: 'R' }, { v: 'N', label: 'N' },
    ],
    kindLabel: '卡面种类',
    kindChips: [
      { v: 'P', label: 'Produce' }, { v: 'S', label: 'Support' },
    ],
    compositeKey: false,
    emptyCmd: 'scripts\\run_shinycolors_scrape.cmd',
    latestSort: 'release_desc',
    defaultArtKind: c => (c.trainable ? 'fes' : 'normal'),
    detailHash: c => `#/sc/card/${c.id}`,
    thumbUrl: (c, kind = null) => {
      const k = kind || (c.trainable ? 'fes' : 'normal');
      return `/api/v2/modules/shinycolors/thumbs/${c.id}/${k}`;
    },
    fallbackThumbUrl: c => `/api/v2/modules/shinycolors/thumbs/${c.id}/normal`,
  },
];

export function getModule(key) {
  const k = String(key || 'pjsk').toLowerCase();
  return MODULES.find(m => m.id === k || m.apiMod === k || m.routeId === k) || MODULES[0];
}

export function cardUniqueKey(modKey, card) {
  const mod = getModule(modKey);
  const kind = mod.compositeKey ? (card.cardKind === 'support' ? 'support' : 'card') : 'card';
  return `${mod.apiMod}:${kind}:${card.id}`;
}
