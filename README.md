# 卡牌雷达 · Card Radar v2.0.0

多游戏二次元卡面图鉴的纯本地镜像站：把四款音乐/偶像游戏的公开数据库同步到本地，提供极速图鉴浏览、批量原图下载、ZIP 收藏包打包导出、GPU 串行保护的 Real-ESRGAN AI 超分与交互画质对比。

严守**零第三方 Python 依赖**（标准库 + Pillow）、**零前端框架/零构建**（原生 ES Module SPA + PWA 离线缓存）、**纯本地运行**（`127.0.0.1:8819`）与**高清素材按需抓取**原则。

## 界面预览

| PJSK 卡面（青蓝主题） | Our Notes 卡面（星空紫主题） |
|---|---|
| ![PJSK 卡面图鉴首页](docs/screenshot-pjsk.png) | ![Our Notes 卡面图鉴首页](docs/screenshot-onotes.png) |

## 支持的游戏

| 模块 | 数据来源 | 同步计划 | 特点 |
|---|---|---|---|
| 🐳 PJSK 卡面 | [pjsk.moe](https://pjsk.moe)（JP 服） | 每两周 · 周一 09:00 | 主备源竞速、中文翻译覆盖层、3D 服装预览、PNG 无损原档 |
| 🎸 邦多利卡面 | [bestdori.com](https://bestdori.com) | 每两周 · 周一 09:20 | 日服/国服双服上线时间、`jp→cn→en` 三区回退（含 B 站服特有卡）、多语言技能 |
| 🎶 Our Notes 卡面 | [bdon.moe](https://bdon.moe)（Moenotes） | 每两周 · 周一 10:00 | 角色卡 + 支援卡 `(kind, id)` 复合键双图鉴、1440×1920 高清原图、官方属性/稀有度图标 |
| ✨ 闪彩卡面 | [shinycolors.moe](https://shinycolors.moe) + gameo 2× | 每两周 · 周一 09:40 | 优先抓取 2272×1280 高清档无损转 PNG、P 卡 Fes 特训双图盒、萌百团体自检 |

## v2.0.0 核心特性与架构升级

- **后端微内核（`server/`）**：由原 2415 行单文件拆分为 `config / router / http_utils / net / upscaler / jobs / user_data / modules/`；声明式路由表 + 统一 `ResourceKey(mod, id, kind)` 契约 + mtime JSON 内存缓存 + `SO_EXCLUSIVEADDRUSE` 与命名互斥体双保险防双实例。
- **GPU 串行超分 + 任务持久化**：下载线程池与 Real-ESRGAN Vulkan 推理信号量彻底隔离，批量超分绝不爆显存；任务队列原子落盘 `data/jobs.json`，重启后自动恢复历史并支持失败/中断任务一键重试。
- **爬虫公共韧性底座（`scraper/common/`）**：四模块统一接入三通路粘性代理（直连 → 7890 → 7897）、Magic Bytes 图像验真（防 0 字节与 SPA 假 200）、连续失败熔断器、断网离线降级与独立 `retry.json` 指数退避队列（1d → 3d → 7d → 14d）。
- **前端体验全面跃升（`web/`）**：
  - **批量操作与 ZIP 导出**：图鉴页支持多选 → 一键批量下载原图 / 批量超分 / 按乐队或稀有度分目录打包导出 `.zip`（纯标准库 `zipfile`）。
  - **原图 vs 超分交互对比滑块**：详情页支持拖拽分割线与键盘微调，直观对比原图与 2K/4K 超分细节。
  - **跨游戏收藏夹与分组**：支持自由建组与「仅看收藏 / 近 30 天新卡」筛选，双写浏览器 `localStorage` 与 `data/user_profile.json` 防止清缓存丢失。
  - **正交深色模式 & 响应式抽屉**：四大游戏主题色与浅色/深色/跟随系统自由组合，窄屏自动切为滑出式侧栏抽屉。
  - **全模块缓存管理 & 数据源探活**：设置页按模块统计并精准清理 `data/originals*` 缓存，一键探测四源站连通性与延迟。
  - **键盘快捷键 & PWA 离线缓存**：`/` 聚焦搜索、`←/→` 详情翻卡、`D` 切深色、`?` 查看快捷键、`Esc` 关弹窗；Service Worker 缓存已浏览缩略图与索引。
- **工程化与自动化护栏**：根目录 `VERSION` 单一版本真源（`scripts/bump_version.py` + `scripts/check_integrity.py`）、零依赖 Python `unittest` + HTTP E2E + Node `node:test` 测试套件与 GitHub Actions CI。

## 环境要求

- Windows 10 / 11
- Python 3.10+（仅需 `pip install --user pillow`）
- 可选：独立显卡（放入 `ai_engine/` 启用 Real-ESRGAN Vulkan AI 超分；缺失自动回退 Pillow 渐进抗锯齿管线）

## 快速开始

```bat
git clone https://github.com/2231734403/card-radar.git
cd card-radar

:: 方式一：一键环境检测、安装 Pillow、注册任务并启动打开浏览器（推荐）
scripts\setup.cmd

:: 方式二：手动运行
pip install --user pillow
scripts\run_server.cmd                 :: 隐藏窗口启动 127.0.0.1:8819
scripts\run_scrape.cmd                 :: 首次抓取 PJSK
scripts\run_bandori_scrape.cmd         :: 首次抓取邦多利
scripts\run_onotes_scrape.cmd          :: 首次抓取 Our Notes
scripts\run_shinycolors_scrape.cmd     :: 首次抓取闪彩
```

遇到任何服务打不开的问题，双击运行 `scripts\verify_setup.cmd` 即可一键自检修复全部 5 个计划任务并校验 `/api/v2/health`。

## 目录结构

```
VERSION                   单一版本真源（当前 2.0.0）
server/                   后端微内核（路由 / 网络 / GPU 串行超分 / 持久化队列 / 四游戏适配器）
scraper/                  爬虫体系（common/ 公共韧性底座 + 4 个游戏增量爬虫）
web/                      纯原生 ES Module SPA（统一模块注册表 / 四游戏统一页 / PWA sw.js）
scripts/                  纯 ASCII .cmd/.vbs 启动与自愈脚本 + 一键安装 + 版本同步/完整性校验
tests/                    零依赖自动化测试套件（Python unittest + HTTP E2E + Node node:test）
.github/workflows/ci.yml  GitHub Actions 持续集成
data/                     抓取与运行产物（.gitignore，不入库）
ai_engine/                可选 Real-ESRGAN 二进制与模型（.gitignore，不入库）
```

## 开发与验证命令

```bat
:: 同步版本号（自动更新 VERSION、sw.js、index.html 与全部 web/js ?v=）
py -X utf8 scripts\bump_version.py 2.0.1

:: 工程完整性护栏（编译校验 + 版本一致性 + 路由校验 + ASCII/T18 + 隐私路径扫描）
py -X utf8 scripts\check_integrity.py

:: 运行全部后端/爬虫/HTTP E2E 单元测试
py -X utf8 -m unittest discover -s tests -p "test_*.py" -v

:: 运行前端 ESM 符号与筛选器测试（需 Node 20+）
node --test tests\frontend.test.mjs
```

## 免责声明

本项目仅为个人学习研究用途的纯本地镜像工具，通过各公开资料站的开放接口获取数据。
所有游戏图片、名称与商标版权归 **Craft Egg / Bushiroad / SEGA / Colorful Palette / Bandai Namco** 及各权利方所有。请勿将抓取到的素材二次分发或用于商业用途。
