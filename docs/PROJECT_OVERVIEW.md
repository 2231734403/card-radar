# 卡牌雷达（Card Radar）· v2.0.0 架构技术档案

> 版本：**v2.0.0** ｜ 平台：Windows 10/11 ｜ 语言：Python 3.10+（零第三方依赖，仅 Pillow）/ 原生 JavaScript ES Module（零构建）
> 仓库：`card-radar`（MIT License）

---

## 1. 架构演进摘要（v1.16.2 → v2.0.0）

| 维度 | v1.16.2 原状 | v2.0.0 强化架构 |
|---|---|---|
| **后端结构** | `server.py` 2415 行巨石 + if-elif 正则链 | `server/` 微内核 11 模块 + 声明式 `Router`（57 路由）+ `GameModule` / `ResourceKey` 统一契约 |
| **并发与稳定性** | 内存 Job 字典、下载与 AI 混跑易爆显存、`SO_REUSEADDR` 双绑风险 | `RLock` + `data/jobs.json` 原子持久化与重启恢复 + 下载池与 `GPU_SEMAPHORE(1)` 分离 + `SO_EXCLUSIVEADDRUSE` 互斥锁 |
| **API 体系** | 四模块路径分散、参数风格不统一 | 清爽统一 RESTful `/api/v2/*`（支持 ETag/304、批量任务、ZIP 导出、全四模块缓存治理、用户档案同步、源站探活），100% 保留 v1 兼容路由 |
| **爬虫体系** | 4 个爬虫互不复用、容错参差不齐 | `scraper/common/` 公共底座：三通路粘性代理、Magic Bytes 验真、熔断器、离线降级、独立 `retry.json` 指数退避（1/3/7/14 天） |
| **前端结构** | `module.js` 750 行与 `home.js`/`detail.js` 割裂 | `web/js/modules/registry.js` 单一配置真源 + 四游戏统一 `home/cards/detail` 引擎 + `favorites` 收藏页 + PWA `sw.js` |
| **工程化与验证** | 手工双处改版本号、仅简易 JS 静态脚本 | 根目录 `VERSION` 单一真源 + `bump_version.py` + `check_integrity.py` + 27 项零依赖单测与 HTTP E2E + GitHub Actions CI |

---

## 2. 本次架构重构顺带修复的原版线上缺陷

1. **启动误删缓存 Bug**：旧版 `server.py:main()` 每次启动自动删除 `data/originals/*_2k.png`，导致 2K 超分缓存重启即毁，现已彻底移除。
2. **PJSK / 邦多利突破后超分 404 Bug**：旧版超分落盘 `{id}_trained_{tier}.png`，而 GET 路由与 URL 读取 `{id}_after_training_{tier}.png`；现统一规范为 `after_training`，且 `find_existing_original` 兼容读取历史遗留 `_trained_{tier}.png`。
3. **邦多利原图缺失 `cn` 区域回退**：`resolve_bandori_original` 原仅查 `("jp", "en")`，现补齐 `("jp", "cn", "en")` 支持 bilibili 特有卡 `bili_res*` 并接入 SPA HTML 壳验真。
4. **邦多利爬虫 404 误报失败 Bug**：旧版返回 `"missing:..."` 而判断条件写 `status == "missing"` 导致全部 404 落入 `failed` 且永不记入缺失队列，现已彻底修复。
5. **Our Notes 支援卡属性补全 100% 熔断 Bug**：旧版 `fetch_bytes` 拒绝所有 `text/html`，导致抓 HTML 详情页必抛异常熔断跳过 82 张；现通过 `allow_html=True` 彻底修复。
6. **Our Notes 原图与前端下载遗漏复合键**：补齐 `resolve_original` 与前端下载标签按 `(kind, id)` 严格查卡。
7. **闪彩爬虫代理 URL 缺前缀 & 下载无进度**：补齐 `http://127.0.0.1:` 代理前缀与 `progress_cb` 传递，所有 Pillow `Image.open` 统一使用上下文管理器防 Windows 文件句柄锁冲突。
8. **缓存管理漏计其余三模块**：`/api/v2/cache` 与 `/api/cache-stats` 现覆盖全部 4 模块（实测释放发现原版隐藏的 617 MB 缓存）并支持按模块精准清理。
9. **无查询参数 POST 超分 500 崩溃**：`split_path_query` 取代 `split("?")[1]`，杜绝 `IndexError`。
10. **前端筛选细节修复**：活跃筛选计数实时更新、角色下拉外部点击稳定关闭、重置恢复完整角色列表、下载面板按模块准确显示 `kindLabel`、全四模块下载完成后自动刷新详情页。

---

## 3. 核心 API 速查（v2）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v2/health` | 版本、PID、AI 引擎状态、四模块汇总 |
| GET | `/api/v2/modules/{mod}/index` | 模块索引（支持 `ETag` / `304`） |
| GET | `/api/v2/modules/{mod}/cards/{id}` 或 `/cards/{kind}/{id}` | 统一详情（含原图与 2K/4K 缓存矩阵 `media`） |
| GET | `/api/v2/modules/{mod}/thumbs/{id}/{kind}` | 统一缩略图 |
| GET | `/api/v2/modules/{mod}/originals/{id}/{kind}?tier=2k\|4k` | 统一原图/超分图 |
| GET/POST/DELETE | `/api/v2/jobs`、`/jobs/download`、`/jobs/superres`、`/jobs/batch`、`/jobs/{id}/retry` | 持久化任务管理与批量调度 |
| POST | `/api/v2/export/zip` | 按乐队/稀有度/平铺打包导出卡面 ZIP |
| GET/DELETE | `/api/v2/cache?mod=all\|pjsk\|bandori\|shinycolors\|onotes` | 全模块缓存统计与按模块清理 |
| GET/PUT | `/api/v2/user-data` | 收藏夹、分组与偏好持久化（`data/user_profile.json`） |
| GET | `/api/v2/sources/probe` | 四数据源连通性与延迟探测 |

所有旧版 `/api/*` 路由均保持向后兼容。
