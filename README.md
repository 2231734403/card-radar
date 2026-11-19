# 卡牌雷达 · Card Radar

多游戏卡面图鉴的本地镜像站：把公开数据库同步到本地，提供图鉴浏览、原图下载与 AI 超分。
纯本地运行（http://127.0.0.1:8819），零第三方 Python 依赖（标准库 + Pillow），低清预览常驻本地、
高清原图只在点击「下载原图」时抓取，最大程度节省存储空间。

## 支持的游戏

| 模块 | 数据来源 | 内容 |
|---|---|---|
| 🐳 PJSK 卡面 | [pjsk.moe](https://pjsk.moe) 公开接口（JP 服） | 1478+ 卡，中文化显示，PNG 无损原档 |
| 🎸 邦多利卡面 | [bestdori.com](https://bestdori.com) 公开 API | 2500+ 卡，**日服/国服双服上线时间**（国服未上线明确标注），属性角标 |
| 🎶 Our Notes 卡面 | [bdon.moe](https://bdon.moe)（Moenotes） | 角色卡 + 支援卡双图鉴，1440×1920 高清原图，资源站同款属性/稀有度图标 |
| ✨ 闪彩卡面 | [shinycolors.moe](https://shinycolors.moe) 公开 API | 全量卡面，Fes 卡面（特训后）双图盒 |

## 功能

- **图鉴浏览**：网格/列表视图；筛选栏可折叠（收起时只留搜索框）——乐队两级筛选 → 角色下拉、属性/稀有度/卡面种类 chip、搜索框、激活筛选数角标
- **原图下载**：统一下载面板（进度条、单条删除、PNG 规范命名落盘到系统「下载」文件夹）
- **AI 超分**：Real-ESRGAN（ncnn-vulkan，NVIDIA 独显）2K/4K 档，失败自动回退 Pillow 经典管线
- **定时同步**：Windows 计划任务**每两周**自动增量抓取（四模块错峰 09:00/09:20/09:40/10:00），错过开机补跑，失败桌面弹窗提醒
- **上线时间校准**：每次扫描都会重新校对各卡实装时间（不只确认卡面是否存在）

## 环境要求

- Windows 10 / 11
- Python 3.10+（`pip install --user pillow`）
- 可选：NVIDIA 显卡（AI 超分用；无卡自动回退经典管线，功能不受影响）

## 快速开始

```bat
git clone https://github.com/<你的用户名>/card-radar.git
cd card-radar
pip install --user pillow

:: 1. 启动本地站（隐藏窗口；也可直接浏览器访问，服务未起时双击 scripts\verify_setup.cmd 自愈）
scripts\run_server.cmd
:: 打开浏览器访问 http://127.0.0.1:8819

:: 2. 首次抓取（各模块独立，增量模式）
scripts\run_scrape.cmd                 :: PJSK
scripts\run_bandori_scrape.cmd         :: 邦多利
scripts\run_onotes_scrape.cmd          :: Our Notes
scripts\run_shinycolors_scrape.cmd     :: 闪彩

:: 3. （可选）注册双周自动抓取 + 登录自启
powershell -ExecutionPolicy Bypass -File scripts\install_tasks.ps1
```

服务保活设计：计划任务 + 启动文件夹双通道自启、无黑窗口、错过补跑（StartWhenAvailable）、
`/api/status` 返回版本号便于确认新代码生效。

## AI 超分引擎（可选）

引擎与模型不随仓库分发：从 [Real-ESRGAN releases](https://github.com/xinntao/Real-ESRGAN/releases)
下载 `realesrgan-ncnn-vulkan.exe` 及 `models/`，放入项目根目录 `ai_engine\` 下即可。
缺失时超分自动回退 Pillow 管线。

## 目录结构

```
scraper/   各游戏模块爬虫（增量缩略图 + 详情缓存 + state 记忆）
server/    本地站（标准库 http.server，下载/超分任务队列）
web/       前端（原生 ES Module SPA，hash 路由，四主题色顺滑切换）
scripts/   启动/抓取入口（隐藏窗口）、计划任务安装、自愈自检
data/      抓取产物（不入库，运行时自动生成）
```

## 免责声明

本项目仅为个人学习研究用途的本地镜像工具，通过各公开资料站的开放接口获取数据。
所有游戏图片、名称与商标的版权归 **Craft Egg / Bushiroad / SEGA / Bandai Namco** 及各权利方所有。
请勿将抓取到的素材二次分发或用于商业用途；如侵犯权益请联系删除。

## 致谢

数据与部分 UI 图标素材来自以下站点的公开接口与公开页面素材：

- [pjsk.moe](https://pjsk.moe) / [translation.exmeaning.com](https://translation.exmeaning.com)
- [bestdori.com](https://bestdori.com)
- [bdon.moe](https://bdon.moe)（Moenotes by StarMoe）
- [shinycolors.moe](https://shinycolors.moe)
- [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)
