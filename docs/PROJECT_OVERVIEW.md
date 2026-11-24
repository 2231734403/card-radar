# 卡牌雷达（Card Radar）· 完整技术档案

> 用途：本文件是项目的**自包含技术说明书**，供外部 AI / 新维护者在不读源码的情况下理解全貌并提出强化方案。
> 版本：**v1.16.2** ｜ 平台：Windows 10/11 ｜ 语言：Python 3.10+ / 原生 JavaScript（无框架）
> 仓库：`card-radar`（MIT License，公开）

---

## 1. 一句话定位

把四个二次元音乐游戏的**公开卡面数据库**同步到本地，提供一个纯本地的图鉴站：浏览 / 两级筛选 / 原图下载 / AI 超分，全部素材按需抓取、绝不冗余存储。

四个游戏模块（侧栏顺序）：

| id | 名称 | 数据源站点 | 卡量（当前） |
|---|---|---|---|
| `pjsk` | PJSK 卡面（Project Sekai） | pjsk.moe（Moesekai） | 1478 |
| `bandori` | 邦多利卡面（BanG Dream! GBP） | bestdori.com | 2512 |
| `onotes` | Our Notes 卡面（BanG Dream! Our Notes，2026 新作） | bdon.moe（Moenotes） | 167 |
| `sc` | 闪彩卡面（ShinyColors） | shinycolors.moe | 1519 |

---

## 2. 硬约束（强化时必须遵守）

1. **零第三方 Python 依赖**：仅标准库 + Pillow（`pip install --user pillow`）。不得引入 requests / aiohttp / Flask / FastAPI / npm 依赖。
2. **纯本地**：只监听 `127.0.0.1:8819`，无外网服务端、无数据库、无构建步骤。前端是"原生 ES Module + hash 路由"，不许上框架/打包器。
3. **Windows 优先**：使用 `py` 启动器、计划任务、VBS 隐藏窗口、注册表读「下载」目录。跨平台不是目标。
4. **中文界面**：全部 UI 文案简体中文；游戏内文本按数据源语言（pjsk 有中文化映射，bandori 简体自带，onotes 简体，闪彩日文原文）。
5. **素材按需**：缩略图常驻本地；高清原图**只在用户点「下载原图」/「超分」时抓取**并缓存，绝不全量预拉。
6. **改前端必须 bump 版本**：所有 `?v=` 资源版本号由 `tools/bump_version.ps1` 统一替换（详见第 11 节）。
7. **.cmd/.vbs 必须纯 ASCII**（cmd 的 GBK 解析会把 UTF-8 中文注释搞乱）；`.ps1` 含中文必须 UTF-8 with BOM。

---

## 3. 仓库结构与规模

```
scraper/           4 个爬虫（各模块独立，互不 import）
  scrape.py            538 行  PJSK
  bandori_scrape.py    422 行  邦多利
  shinycolors_scrape.py 421 行 闪彩
  onotes_scrape.py     522 行  Our Notes
server/server.py    2415 行  本地站（HTTP + 路由 + job 队列 + 超分管线）
web/
  index.html           单页入口（?v= 版本号在此）
  css/style.css        848 行  设计令牌 + 四主题 + 全部组件样式
  js/main.js           156 行  模块系统 + 侧栏 + 路由注册 + 启动
  js/router.js          43 行  hash 路由（正则 → 页面 handler）
  js/store.js          163 行  四模块索引缓存 + 统一筛选 filterCards
  js/api.js            129 行  全部 fetch 封装
  js/ui.js             153 行  公共渲染（网格卡片 cell / 属性角标 / toast / 图片弹窗）
  js/theme.js           21 行  主题切换（theme-anim 类方案）
  js/dlpanel.js        336 行  左下角下载球 + 任务面板（轮询 / 删除 / 再超分）
  js/userSettings.js    26 行  localStorage 设置（模块 / 超分档位 / 引擎）
  js/pages/home.js      66 行  PJSK 首页
  js/pages/cards.js    409 行  四模块共用图鉴页（CFG 表驱动）
  js/pages/detail.js   174 行  PJSK 详情
  js/pages/module.js   750 行  邦多利 / Our Notes / 闪彩 的首页与详情
  js/pages/placeholder.js 89 行 关于页
  js/pages/settings.js 143 行  设置页
  img/attr/           属性/稀有度角标 PNG（pjsk 星花心月蝶、邦多利四色、Our Notes 官方图标）
scripts/            启动与抓取入口（.cmd → wscript → .vbs 隐藏窗口）
docs/               README 截图 + 本文件
data/               抓取产物（.gitignore，运行时生成）
ai_engine/          Real-ESRGAN 二进制（.gitignore，需自行下载）
tools/              一次性脚本与维护工具（.gitignore，不入库）
```

代码总量约 **7.8k 行**（server 2.4k + scrapers 1.9k + web 3.5k）。

---

## 4. 架构总览

```
[公网数据源] --爬虫(每两周)--> data/<模块>/index.json + data/thumbs_*/
                                    |
                              server.py (127.0.0.1:8819)
                                    |
              +---------------------+---------------------+
              |                     |                     |
        静态文件(web/)        GET API(索引/详情/图)    POST API(下载/超分 job)
              |                     |                     |
        SPA(hash 路由)  <-----  前端 fetch           job 线程池(daemon)
                                                          |
                                            原图缓存 data/originals_*/ 
                                                          |
                                       系统「下载」文件夹(注册表解析)
```

- **索引驱动**：前端只读 `/api/<mod>/index`（一次性全量 JSON），筛选/排序/搜索**全部在前端内存完成**，零后端查询。
- **详情懒加载**：详情页先按 index 数据渲染完整骨架，再请求 `/api/<mod>/cards/:id` 补齐技能/数值（服务器端有 `data/<mod>/card_*.json` 缓存，未命中则现场抓取并落盘）。
- **重任务后台化**：下载原图与超分都是 POST 创建 job → 后台线程执行 → 前端轮询 `/api/download-progress/:jobId`（1s 间隔），面板常驻左下角。

---

## 5. 四模块数据源规格（核心资产，精确到 URL）

### 5.1 PJSK

| 类型 | URL |
|---|---|
| 主数据（JP，主/备竞速） | `https://metadata.pjsk.moe/jp/master/{cards,skills,gameCharacters,gameCharacterUnits,moe_costume,cardEpisodes}.json` ↔ `metadata.exmeaning.com`（同路径） |
| 中文翻译层 | `https://translation.exmeaning.com/files/translation/{cards,skills,costumes}.json` —— **日文原文→中文映射字典**（不是按 id），未翻译则回退日文 |
| 图片主源 | `https://storage.pjsk.moe/sekai-jp-assets/` |
| 图片备源 | `https://storage.exmeaning.com/sekai-jp-assets/` |
| 缩略图 | `{storage}/thumbnail/chara/{assetbundleName}_normal|after_training.webp`（trained 仅 3★/4★） |
| 原图（PNG 无损） | `{storage}/character/member/{assetbundleName}/card_{normal|after_training}.png`（同目录 png/webp 并存，PNG 即无损原档，4★ 约 4–5MB） |

要点：
- `race_fetch` 主备竞速（先返回者胜，流式落盘），自动适应 VPN 开关。
- 中文名表 `CHAR_ZH` 硬编码（虚拟歌手 21–26 必须映射，片假名不能直接当中文）。
- 非突破卡请求 `after_training` 会 404，属**预期**，不算失败。

### 5.2 邦多利（bestdori）

| 类型 | URL |
|---|---|
| 卡列表 | `https://bestdori.com/api/cards/all.5.json`（2500+ 卡 dict） |
| 角色 | `https://bestdori.com/api/characters/main.2.json`（40 角色，含 bandId） |
| 乐队 | `https://bestdori.com/api/bands/main.1.json`（bandId → 乐队名） |
| 技能 | `https://bestdori.com/api/skills/all.10.json`（86 技能，`{0}` 占位符按 duration 最高等级插值） |
| 详情 | `https://bestdori.com/api/cards/{id}.json`（skillName/episodes/gachaText 多语言） |
| 图片 | `https://bestdori.com/assets/{region}/characters/resourceset/{resourceSetName}_rip/card_{normal|after_training}.png` |

关键字段映射：
- 多语言数组序：`[日, 英, 繁, 简, 韩]` → 简体取 **下标 3**（自带简体，无需翻译层）。
- `releasedAt` 数组序：`[日服, 英服, 台服, 国服, 韩服]` → 索引落盘 `releaseJp`(0) / `releaseCn`(3)，`releaseAt = releaseCn || releaseJp`。**详情页展示「日服上线 / 国服上线」双行**，国服未上线显示「未上线」，2100 年占位时间戳显示「未公布」。
- `spoiler` 字段已废弃（v1.16.0 删除），未实装卡由双服时间承接。
- 区域回退链：`jp → cn → en`（**bilibili 服特有卡 `bili_res*` 只在 cn 区域有图**）。
- ⚠️ 资源不存在时 bestdori 回 SPA 壳（**HEAD 也 200**）——判定资源真伪必须 GET + Content-Type/magic bytes。

### 5.3 闪彩（shinycolors.moe）

| 类型 | URL |
|---|---|
| 偶像列表 | `https://api.shinycolors.moe/info/idolList`（33 位含联动） |
| 偶像详情 | `https://api.shinycolors.moe/info/idolInfo?idolId={n}`（内含 `cardLists[]` 全量卡） |
| 卡详情 | `https://api.shinycolors.moe/info/{p,s}CardInfo?cardId={uuid}` |
| 缩略图（官方） | `https://cf-static.shinycolors.moe/images/content/{idols|support_idols}/card/{enzaId}.jpg` |
| 特训后缩略 | `.../{dir}/fes_card/{enzaId}.jpg`（`fes_card` 就是特训后，仅 P 卡 trainable） |
| **高清原图（2×，优先）** | `https://gameo.jp/img/imassc/card/【卡名】角色[2].{jpg|webp}` —— **2272×1280**，`2`=特训后；2024-10-08 后实装的卡用 webp；卡名需去 `/ : #`、` ’→' `、`…→...` |
| 官方兜底 | cf-static 的 1136×640 jpg |

要点：
- 官方 cf-static 与 shinycolors.moe 全站**只有 1136×640 JPEG**（游戏原生分辨率，无更高官方档）；高清靠 gameo.jp 社区档（抽样 20 命中 19）。
- 缓存/下载一律输出 **PNG 无损容器**（2272 档 2–3MB）；旧 1136 缓存按宽度 <2000 自动升级，升级失败写 `.low` 标记 7 天内不重试。
- 无属性体系（本篇卡无属性色），前端不渲染属性角标。
- ⚠️ api 子域本机直连常断，需走本机代理 7890；cf-static 与 gameo 直连可达。
- 模块 id 用 `sc`（路由 `#/sc/...`），全局筛选的 kind 用 P/S（Produce/Support）。

### 5.4 Our Notes（bdon.moe / Moenotes）

**站点特性（极重要）**：静态 Markdown 站 + 专用图床，**专为程序化访问设计**——robots 全开放、有 `llms.txt` 索引、**任意页面 URL 加 `.md` 即得纯 Markdown**（或发 `Accept: text/markdown`）。13 语言，默认 zh-CN。

| 类型 | URL |
|---|---|
| 角色卡索引 | `https://bdon.moe/cards.md` |
| 支援卡索引 | `https://bdon.moe/support-cards.md` |
| 角色索引 | `https://bdon.moe/characters.md` |
| 详情 | `https://bdon.moe/cards/{id}.md` / `https://bdon.moe/support-cards/{id}.md` |
| 缩略图 | `https://assets.bdon.moe/zh-Hans/MemberCard/{id}/member_thumbnail/member_thumbnail.webp`（384×512）/ 支援卡 `SupportCard/{id}/snap_thumbnail/…` |
| 原图 | `MemberCard/{id}/member_full/member_full.webp`（1440×1920）/ 支援卡 `SupportCard/{id}/snap_full/…`（**1920×1080 横版**） |
| 立绘/背景/技能条 | `member_character/`（RGBA 透明）、`member_background/`、`skill_sprite/` |
| 站点图标素材 | `https://bdon.moe/assets/CardType-{Red|Blue|Green|Yellow|Purple}.png`（64×64 圆形）、`RarityIcon_{R|SR|SSR|BD}.png`、`SP_CardRarityIcon_EX.png` |

**核心陷阱（强化时务必保留设计）**：
1. **角色卡与支援卡 ID 序列重叠**（1–81 双方都有）→ 全链路必须用 `(kind, id)` 复合键：
   - 缓存文件名 `{kind}_{id}.json`
   - 详情路由 `#/onotes/card/{kind}/{id}`
   - API `/api/onotes/cards/{id}/{kind}`
   - 图片 `{id}_{kind}.webp/png`、下载命名 `OurNotes卡牌_…` / `OurNotes支援卡_…`
2. **支援卡 md 的「稀有度」列是内部档位编号**：`2→R, 3→SR, 4→SSR, 10→特殊`（特殊档官方图标叫 EX）→ 爬虫 `SUPPORT_RARITY_MAP` 映射为显示名。
3. **支援卡属性 md 完全没给**：从官方 HTML 页提取（`RarityIcon alt` + 邻近 Red/Blue/Green/Yellow/Purple 词），缓存 `support_meta_{id}.json`。属性官方原名以 **ja 页**为准：Red=紅赤、Blue=紺碧、Green=翡翠、Yellow=山吹、Purple=紫苑（zh 角色卡页显示英文，本地化不一致）。
4. 每卡单立绘（分层设计），**无特训后独立图**。
5. 前端角标：左上角属性图标、**右上角**稀有度艺术字（特殊档用 EX 图，`ONOTES_RARITY_ICON` 映射 特殊→EX）。
6. 站点为粉丝团队维护，持续性有风险；**断连时必须离线降级**（见 8.3）。

---

## 6. 后端 server.py 详解

### 6.1 基础
- `http.server.ThreadingHTTPServer`，`127.0.0.1:8819`，`SERVER_VERSION` 常量随行为变更递增。
- 静态文件服务（web/ 目录，带缓存头）+ API 路由用**正则逐个匹配**（无框架路由器）。
- `_send` / `_send_file` / `_safe_join`（防路径穿越）。

### 6.2 API 一览

**通用**
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/index` `/api/status` `/api/cards/:id` | pjsk 索引/状态/详情 |
| GET | `/api/thumbs/{id}_{kind}.webp` | pjsk 缩略 |
| GET | `/api/originals/{id}_{normal|after_training}[_2k|_4k].png` | pjsk 原图/超分图 |
| GET | `/api/costume-thumb/{abn}.webp` | 服装缩略 |
| GET | `/api/download-jobs` `/api/download-progress/:jobId` | 任务列表/单任务 |
| POST | `/api/download/:id/:kind` `/api/superres/:id/:kind?target=2k|4k&engine=ai|pillow` | pjsk 建任务 |
| POST | `/api/job-remove/:jobId` `/api/cache-clear` `/api/cache-stats` | 管理 |

**邦多利**：`/api/bandori/{index,status,cards/:id,thumbs/:id_(normal|trained|after_training).webp,originals/:id_(normal|after_training)[_2k|_4k].png}`，POST `/api/bandori/{download/:id/:kind, superres/:id/:kind}`

**闪彩**：`/api/shinycolors/{index,status,cards/:id,thumbs/:id_(normal|trained).webp,originals/:id[_fes][_2k|_4k].(jpg|png)}`，POST `/api/shinycolors/{download/:id[/:kind], superres/:id[/:kind]}`

**Our Notes**：`/api/onotes/{index,status,cards/:id[/:kind],thumbs/:id_(card|support).webp,originals/:id_(card|support)[_2k|_4k].png}`，POST `/api/onotes/{download/:id/(card|support), superres/:id/(card|support)}`

### 6.3 Job 队列
- `_JOBS` 全局 dict + **`threading.RLock`**（必须 RLock：回调链与 POST 线程会嵌套加锁，普通 Lock 曾导致整个 API 死锁）。
- 上限 40，`_prune_jobs` 只清已结束任务（jobId 前缀是时间戳，最早优先）。
- 每个 job 带 `mod` 字段（pjsk/bandori/shinycolors/onotes）隔离，前端面板据此决定走哪个 API。
- job 状态机：`running → done | error`；字段含 `phase`（download/superres/ai）、`downloaded/total`、`source`（直连/代理/AI/Pillow）、`srProgress`、`engineFallback`、`filename`、`url`、`already`、`label`。
- 同一 (card, kind, mod) 已有 running 任务时复用（`reused: true`）。

### 6.4 下载落盘命名
- pjsk：`Pjsk卡牌_{id}_{prefix}_{角色}_{突破前|突破后}.png`
- 邦多利：`Bandori卡牌_{id}_{prefix}_…png`
- 闪彩：`ShinyColors卡牌_{id}_{prefix}[_特训后].png`
- Our Notes：`OurNotes卡牌_{id}_{prefix}.png` / `OurNotes支援卡_{id}_{prefix}.png`
- 超分追加 `_2K超分` / `_4K超分`；文件名经 `_sanitize_name` 净化（Windows 非法字符）。
- 目标目录 `downloads_dir()`：**读注册表 `User Shell Folders\{374DE290-...}` 解析系统「下载」**（兼容 OneDrive 重定向），失败回退 `~/Downloads`。
- 同名文件已存在则跳过（`already: true`）。

### 6.5 超分三级管线
1. **AI 首选**：`ai_engine/realesrgan-ncnn-vulkan.exe`（Real-ESRGAN ncnn-vulkan v0.2.5.0）
   - 模型 `AI_MODELS = ["realesr-animevideov3-x4", "realesrgan-x4plus-anime"]`（逐个尝试）
   - 参数：`-s 4 -t 128 -g 0`（固定 4× 推理 → 按档位长边 BOX 缩回；tile 128 防显存溢出；g 0 显式锁独显）
   - `_ai_prepare`：RGBA 真透明合成白底（该系列模型对 RGBA 大图会输出**全黑帧**）
   - `_ai_validate`：三重校验（输出尺寸符合预期 / 非空图 / MAD 与源图差异合理），任一失败即换模型
   - 进度：解析 stderr 的 `\r`/`\n` 百分比
   - 后处理：输出 4× 后 BOX 缩到目标长边 + `USM(1.0, 30, 3)` 轻锐化
2. **失败回退 Pillow 经典管线** `_progressive_upscale`：每步 ≤1.3× 放大 + GaussianBlur(0.5) 平滑 + 末步 0.6 + 温和 USM(2.2, 85, 4)，抗锯齿优先。
3. **档位**：`SR_TIERS = {"2k": 2560, "4k": 3840}`（长边像素）。

引擎缺失 / 推理失败 / 超时（600s）一律自动回退，**永不炸主功能**；`job["engineFallback"]=True` 会告知前端。

---

## 7. 前端详解

### 7.1 模块系统（加新游戏只需改一处）
`main.js` 的 `MODULES` 数组：

```js
{ id: 'pjsk', name: 'PJSK 卡面', icon: '🐳', pages: [
    { route: 'home',  icon: '🏠', label: '首页',     handler: renderHome },
    { route: 'cards', icon: '🃏', label: '卡牌图鉴', handler: renderCards },
] }
```

- 循环注册 `#/{mod}/{route}` 路由；侧栏「模块切换器 + 当前模块子导航 + 通用(设置/关于)」由同一数组渲染。
- 详情路由单独注册（pjsk 兼容旧链接 `#/card/:id`；onotes 必须带 kind 两段捕获）。
- 旧链接迁移表 `LEGACY_HASH`（含空 hash：裸域名 → `#/pjsk/home`）。

### 7.2 主题系统
- `:root` 一套设计令牌；`html[data-theme='bandori'|'onotes'|'sc']` 覆盖主色（pjsk 用默认青蓝）。
- 切换不用 `@property` + transition（本环境会把注册的自定义属性**冻结在初始值**，连 inline 都改不动）；
- 实际方案：`applyTheme()` 给 `html` 挂 `.theme-anim` 类 650–700ms → CSS 通配 `transition` 让全站颜色平滑过渡，平时组件 hover 不受影响。
- 模块切换时序：**先切内容（重建侧栏+路由），60ms 后再变色**（反之新 DOM 无过渡会瞬变）。

### 7.3 图鉴页（cards.js，四模块共用，CFG 表驱动）
- `filters = { q, unit, characterId, attr, rarity, kind, sort }`，模块级共享；**切模块自动清空**（否则残留筛选会把另一模块筛空）。
- `filterCards(f, cards)`（store.js）统一过滤：稀有度用 **`String()` 比较**（pjsk 是数字星数、onotes 是 'SSR'/'特殊' 字符串，曾因 `Number('SSR')=NaN` 导致闪彩一点稀有度就筛空）。
- CFG 每模块配置：`unitOrder` / `specialUnits`（Our Notes 的 283pro 等衍生团单独一行「特殊组合」）/ `rarityChips` / `kindChips` / `attrNames` / `cell` / `row`。
- **筛选栏可收缩**：默认收起只留「搜索 + 排序 + 视图切换 + ▸展开筛选」一行；展开显示全部 chip 行；按钮带**激活筛选数角标**。
- 两级筛选：先选团体 → 角色下拉只剩该团角色；切换团体时清掉不匹配的角色选择。
- 网格卡片（ui.js `cardCellHtml`）：缩略图**1:1 方形锁死**（`img{position:absolute; inset:0; object-fit:cover}`——用 `height:100%` 会和 `aspect-ratio` 形成循环依赖，图片加载完后把格子撑成原图比例）。
- 角标：pjsk 属性图案图标左上 + 金色星；邦多利四色图案左上；闪彩稀有度白胶囊**左上**；Our Notes 属性图标左上 + 稀有度艺术字**右上**。

### 7.4 下载面板（dlpanel.js）
- 左下角可拖动 FAB（纯白下载箭头 SVG），点击展开面板；**`display:flex`**（曾用 inline `display:block` 顶掉 CSS 导致不滚动）。
- 列表 `flex:1; min-height:0` 才能正常滚动；每条含进度条/来源/引擎标签/「✨超分」/「✕删除」。
- 1s 轮询 running 任务；`__dlSR` 读 job 的 `mod/kind/card` 调对应超分 API（档位/引擎取设置页）。

### 7.5 设置页
`localStorage` 键 `cardRadar.settings`：`gameModule`（上次模块）、`srTarget`（2k/4k）、`srEngine`（ai/pillow）。设置页还提供缓存统计/清缓存。

---

## 8. 爬虫详解

### 8.1 通用模式（四个爬虫一致）
1. 拉索引（一次全量）→ 构建 pjsk 兼容的 `index.json`（`{updatedAt, cards:[…]}`）
2. **增量缩略图**：本地已有且非空即跳过（`skipped` 计数）；并发 4（`WORKERS`，从 8 降下来控内存/带宽）
3. **详情预爬**：写 `card_{id}.json`（onotes 为 `{kind}_{id}.json`），供 server 秒回详情
4. **state.json**：`{last_run, last_result: ok|partial, counts:{downloaded,skipped,failed,…}}`；失败进入记忆队列 14 天重试
5. **失败弹窗**：脚本退出码非 0 → `scripts/popup_fail.ps1` 桌面提醒
6. 网络三通路回退：直连 → `127.0.0.1:7890` → `7897`（自动适应 VPN 开关）

各模块差异：
- pjsk：`race_fetch` 主备竞速；`TRAINABLE_RARITY={rarity_3,rarity_4}`
- 邦多利：单线程 0.4s 限速抓详情（bestdori 限流严格）；区域回退 jp→cn→en
- 闪彩：限速 0.25–0.3s；缩略图 normal + fes_card(trained)
- onotes：**详情每轮全量重拉**（校准上线时间，内容有变才落盘）；支援卡元数据补全带**熔断器**

### 8.2 「上线时间校准」原则
每次扫描不只确认卡面是否存在，还要重新核对实装时间：
- pjsk / bandori / 闪彩：索引本身每轮全量重拉，`releaseAt` 自然刷新
- 邦多利：额外记录 `releaseJp` / `releaseCn` 双服时间
- onotes：详情每轮重拉（Release 字段随官方公开变化），比对后仅在有变化时写盘

### 8.3 可自愈失败的判定分层（onotes 范例）
- `last_result=partial` **只由「影响内容」的失败决定**（缩略图、详情失败）
- 支援卡稀有度/属性补全失败 = 可自愈增量增强 → 走映射兜底、不计 partial（否则首页误报「部分图片失败」）
- **熔断器**：连续 3 次连接失败即跳过剩余补全，断网时整轮 2 分钟收工而非 14 分钟
- **离线降级**：索引拉取失败且本地有旧索引 → 沿用本地索引、跳过一切网络步骤、state 保持 ok；首跑无索引才抛错

### 8.4 计划任务（全部两周一次，错峰）
| 任务名 | 时间 | 内容 |
|---|---|---|
| `PjskCardWikiWeeklyScrape` | 周一 09:00 | pjsk |
| `BandoriCardWikiWeeklyScrape` | 周一 09:20 | 邦多利 |
| `ShinyColorsCardWikiScrape` | 周一 09:40 | 闪彩 |
| `OnotesCardWikiScrape` | 周一 10:00 | Our Notes |
| `PjskCardWikiServer` | 登录时 | 启动本地站 |

注册：`New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At HH:mm -WeeksInterval 2`；`StartWhenAvailable`（关机错过开机补跑）；`MultipleInstances IgnoreNew`。

---

## 9. 部署与自启链路

```
计划任务(登录) ─┐
                ├→ wscript //nologo autostart_hidden.vbs
启动文件夹 .lnk ─┘        └→ run_server.cmd（幂等：端口已监听即退出）
                              └→ wscript run_server_hidden.vbs
                                    └→ py -X utf8 server\server.py   ← 必须直接起 python
```

⚠️ **绝对不能形成环**：`run_server_hidden.vbs` 若回调 `run_server.cmd` 会无限递归，服务永不启动（v1.16.0 真实事故，已修）。6 个 vbs 全部用 `FileSystemObject` 相对脚本目录推导项目根，项目可放任意路径。

其他：`.cmd/.vbs` 纯 ASCII；`verify_setup.cmd` 一键自愈（补任务/补自启/重启服务）；安全软件建议加白名单。

---

## 10. 错误台账（真实踩过，强化时勿重犯）

| # | 症状 | 根因 | 解法 |
|---|---|---|---|
| T1 | 服务 30 分钟后假死 | 下载回调与 POST 线程嵌套加锁，普通 Lock 不可重入 | 改 `RLock` |
| T2 | 图片全部 404 | 数据源迁移了域名路径 | 主备竞速 + 双源 |
| T3 | 中文名显示日文 | 片假名直接当名 | 硬编码 CHAR_ZH 映射表 |
| T4 | 批量改脚本静默失败 | bash 双引号吞 `$变量` | 用脚本文件（.ps1/.py）做批量替换 |
| T5 | 启动黑框闪烁 | cmd 直接当任务 Action | wscript + 隐藏 vbs |
| T7 | 缩略图 000 字节 | 并发过高被限流 | WORKERS 4 + 落盘前校验非空 |
| T8 | 详情页空白 | 详情接口失败没兜底 | 两段渲染（先骨架后补齐） |
| T9 | 下载面板不滚动 | inline `display:block` 顶掉 CSS flex | 改 `display:flex` + `flex:1;min-height:0` |
| T10 | 主题变量改不动 | `@property` + transition 冻结变量 | 改 theme-anim 类 + 通配 transition |
| T11 | 裸域名 404 | 迁移表缺空 hash 键 | 迁移表加 `''` |
| T12 | 同号卡互相覆盖（onotes） | 角色卡/支援卡 ID 序列重叠 | 全链路 (kind,id) 复合键 |
| T13 | 一点稀有度就筛空 | `Number('SSR')=NaN` | 统一 `String()` 比较 |
| T14 | 跨模块切换整页空 | filters 模块级共享残留 | 切模块自动清空 |
| T15 | 筛选栏行距变窄 | flex gap 只作用直接子元素 | 容器补 `flex-direction/gap` |
| T16 | 收起筛选无效 | `display:flex` 与 `[hidden]` 同特异性、后写取胜 | 隐藏规则后置并加前缀 |
| T17 | 网格大小不一 | `height:100%` 子图 + `aspect-ratio` 父级循环依赖 | 图改 absolute inset:0 |
| T18 | 站点打不开 | vbs 自噬循环（cmd↔vbs） | hidden.vbs 必须直接起 python |
| T19 | 双实例抢端口 | Python SO_REUSEADDR 允许双绑 | 重启前确认单 LISTENING |
| T20 | 邦多利 404（文件明明在） | URL kind ↔ 磁盘名映射错位 | 全站一张映射表，URL 原文 |
| T21 | HEAD 200 误判资源存在 | bestdori 对不存在路径回 SPA 壳 | GET + Content-Type 判定 |
| T22 | 超分 404 | 前端发 `/superres/:id/:kind`，后端只匹配 `/:id` | 路由补 kind 段 |
| T23 | 闪彩只有 100KB | 官方只有 1136×640 | 跨站找 gameo 2272 档 |
| T24 | 「部分图片失败」误报 | 可自愈补全失败计入了 partial | 判定分层 |
| T25 | 稀有度显示数字 | 支援卡 md 稀有度是内部编号 | 映射表 2/3/4/10 |

---

## 11. 版本与发布规程

- 单一版本号贯穿：`server.py:SERVER_VERSION` + 所有前端 `?v=`（由 `tools/bump_version.ps1` 批量替换，脚本内 `$V` 与 `$old` 两处都要改，只许用编辑器改，不许 shell 拼接）。
- bump 后**必须抽查** `web/index.html` 的 `?v=` 实际值（历史上出现过「bumped 但值没变」的假成功）。
- 验证前端改动：浏览器必须 **Ctrl+F5 / URL 加 cache-bust**——本环境（IAB）memory cache 不遵守 no-cache，会跑到旧 JS。
- 提交规范：`vX.Y.Z: 简短英文描述`；仓库已连 GitHub（`origin/main`）。

---

## 12. 当前状态

| 项 | 值 |
|---|---|
| 版本 | v1.16.2 |
| 服务 | `http://127.0.0.1:8819`，单实例，隐藏窗口 |
| 数据量 | pjsk 1478 / 邦多利 2512 / 闪彩 1519 / Our Notes 167 |
| 缩略图 | 2466 / 3594 / 2071 / 167 |
| 原图缓存 | 0 / 15 / 81 / 20（按需） |
| 邦多利状态 | `partial`（128 张 bestdori 限流/资源缺失，14 天队列自愈中，属真实失败） |
| Our Notes 状态 | 支援卡属性补全待网络恢复自愈（熔断跳过 82 张） |
| 已知小缺口 | 闪彩 originals 中部分 1136 旧档待升级；onotes 167 张中新增 1 张详情待校准 |

---

## 13. 可强化方向（建议给强化方按序评估）

**A. 架构层**
1. `server.py` 2415 行单文件 → 按模块拆包（`server/api_{pjsk,bandori,shiny,onotes}.py` + `server/jobs.py`），但**保持零依赖与线程模型**。
2. 路由层用「(method, regex, handler) 表」替代 if 链，便于静态检查重复/漏注册（历史上多次因路由正则漏段 404）。
3. job 队列加持久化（重启后恢复历史/失败可重试），并暴露 `/api/jobs?mod=`。

**B. 数据层**
4. 索引增量：用数据源的 `data_version` / hash 判断是否需要重拉（onotes 已有 `dataVersion` 字段未充分利用）。
5. 统一 `releaseJp/releaseCn` 双服模型到四模块（目前仅邦多利有），详情页统一「上线时间」组件。
6. 抓取失败重试队列显式化（现在是 state 里 14 天记忆，可做独立 `retry.json` + 指数退避）。

**C. 功能层**
7. 图鉴批量选择 + 批量下载/批量超分（现在只能单卡）。
8. 收藏/分组（localStorage），以及「只看新卡」视图（按 releaseAt 过滤最近 N 天）。
9. 卡面收藏包导出（zip，按乐队/稀有度分目录）。
10. 详情页图片对比滑块（原图 vs 超分图并排/滑动对比）。
11. 离线 PWA（Service Worker 缓存已下载缩略图），断网仍可浏览图鉴。

**D. 体验/视觉**
12. 骨架屏替代「正在加载」文本；图片懒加载占位 shimmer。
13. 深色主题（设计令牌已集中，只差一套 `[data-theme]` 深色值）。
14. 键盘导航（←/→ 翻卡，/ 聚焦搜索，Esc 关弹窗）。
15. 移动端自适应（侧栏改抽屉式；网格列数断点）。

**E. 工程化**
16. 后端单测（爬虫的 Markdown/JSON 解析函数、文件名净化、筛选函数）——目前只有 `tools/js_check.mjs` 语法检查。
17. GitHub Actions：`py_compile` + `node --check` + 版本一致性校验（`SERVER_VERSION` 必须等于 `?v=`）。
18. 一键安装脚本（检测 Python/Pillow → 建任务 → 起服务 → 打开浏览器），替代现在分散的说明。

**F. 合规/稳健**
19. 各数据源可用性探测（启动时轻量 HEAD，失败则 UI 提示「数据源不可达，展示本地缓存」）。
20. 素材版权提示与「仅个人使用」二次确认（仓库已有免责声明，可在下载按钮旁加一次提示）。

---

## 14. 给强化方的交接提示

- 改任何后端行为 → 必须 bump `SERVER_VERSION` 并重启服务（`schtasks /run /tn PjskCardWikiServer`），用 `/api/status` 的 `version` 确认新代码生效。
- 改前端 → bump `?v=` → 浏览器 Ctrl+F5 → 用真实点击验证（不能只看 HTML 字符串）。
- 任何「多形态资源」（normal/fes、card/support）→ 路由/任务/落盘/前端按钮**四处同时带 kind**。
- 任何「通用函数接新数据集」→ 先逐字段对类型（数字 vs 字符串）。
- 任何「aspect-ratio 图片网格」→ 图片用 `position:absolute; inset:0`。
- 任何「计划任务/locale/字段名」→ 用真实数据源抽样核对，不信任文档字面（md 的「稀有度」列其实是内部编号就是例子）。
