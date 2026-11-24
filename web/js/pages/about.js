// 关于与架构策略页（v2.0.0 四游戏完整档案）
import { MODULES } from '../modules/registry.js?v=2.0.0';
import { fetchHealth } from '../api.js?v=2.0.0';
import { esc } from '../ui.js?v=2.0.0';

export async function renderAbout(app) {
  app.innerHTML = '<div class="loading-block">正在加载…</div>';
  let health = null;
  try { health = await fetchHealth(); } catch { /* 静默 */ }

  app.innerHTML = `
  <div class="detail-head">
    <div>
      <div class="page-title">关于 <span class="hl">卡牌雷达 v2</span></div>
      <div class="page-desc">多游戏本地卡面镜像微内核 · 零第三方依赖 · 按需抓图省空间${health?.version ? ` · 服务版本 v${esc(health.version)}` : ''}</div>
    </div>
  </div>
  <div class="section-gap"></div>
  <div class="info-grid">
    <div class="card-panel">
      <h3 style="margin-bottom:10px">🎮 覆盖的四款游戏与错峰同步</h3>
      <div style="font-size:13.5px;color:var(--text-2);line-height:2">
        ${MODULES.map(m => `· ${m.icon} <b>${esc(m.name)}</b>：${esc(m.schedule)} · ${esc(m.sourceName)}<br>`).join('')}
        · 全部爬虫共用 <code>scraper/common/</code> 韧性底座：三通路粘性代理、Magic Bytes 验真、熔断器、离线降级与指数退避重试队列（<code>retry.json</code>）
      </div>
    </div>
    <div class="card-panel">
      <h3 style="margin-bottom:10px">🏗️ v2 微内核与高可用架构</h3>
      <div style="font-size:13.5px;color:var(--text-2);line-height:2">
        · <b>后端拆包</b>：声明式路由表 + 统一 <code>ResourceKey(mod, id, kind)</code> 契约，消除多形态命名错位<br>
        · <b>并发隔离</b>：下载线程池与 Real-ESRGAN GPU 推理串行信号量分离，批量超分绝不爆显存<br>
        · <b>持久化</b>：任务队列（<code>data/jobs.json</code>）重启恢复支持一键重试；收藏夹双写 <code>data/user_profile.json</code><br>
        · <b>防双实例</b>：Windows 命名互斥体 + 禁用端口复用，杜绝 T19 双实例抢占
      </div>
    </div>
    <div class="card-panel">
      <h3 style="margin-bottom:10px">💾 存储与离线策略</h3>
      <div style="font-size:13.5px;color:var(--text-2);line-height:2">
        · 常驻本地仅保存低清 WebP 缩略图；高清 PNG 原图仅在点击「下载原图 / 超分 / 导出 ZIP」时按需拉取<br>
        · 浏览器端集成轻量 PWA Service Worker，断网环境下仍可离线浏览已缓存缩略图与最近索引<br>
        · 服务端 mtime 文件缓存加速大 JSON 读取，爬虫更新后自动失效无缝生效
      </div>
    </div>
    <div class="card-panel">
      <h3 style="margin-bottom:10px">⚖️ 版权与免责声明</h3>
      <div style="font-size:13.5px;color:var(--text-2);line-height:2">
        · 本项目为个人学习研究用途的纯本地镜像工具（仅监听 <code>127.0.0.1:8819</code>）<br>
        · 游戏图片、角色名与商标版权均归 <b>SEGA / Colorful Palette / Bushiroad / Craft Egg / Bandai Namco</b> 及各权利方所有<br>
        · 公开数据源致谢：pjsk.moe / bestdori.com / bdon.moe / shinycolors.moe / Real-ESRGAN<br>
        · 请勿将下载的素材用于二次公开分发或商业用途
      </div>
    </div>
  </div>`;
}
