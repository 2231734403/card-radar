// 预留模块占位页 + 关于页
import { esc } from '../ui.js?v=1.16.1';

const ROADMAP = [
  { icon: '🎵', t: '音乐列表', d: '同步曲目、JVocal、谱面难度等' },
  { icon: '🧑‍🎤', t: '角色图鉴', d: '角色资料、卡片收录统计' },
  { icon: '👗', t: '服装图鉴', d: '服装数据已随周更落盘，可直接扩充为独立模块' },
  { icon: '🏆', t: '称号 / 活动数据', d: '预留：活动、称号、演出数据' },
];

export function renderPlaceholder(app, name) {
  app.innerHTML = `
  <div class="placeholder-hero">
    <div class="big">🏗️</div>
    <h2>${esc(name)} 模块规划中</h2>
    <p>本网站采用模块化架构 —— 在 <code>js/main.js</code> 的导航配置里注册一个新页面、<br>在 <code>js/pages/</code> 下新增一个模块文件即可上线，不需要改动任何现有代码。</p>
    <div class="module-roadmap">
      ${ROADMAP.map(m => `
        <div class="m"><div class="t">${m.icon} ${esc(m.t)}</div><div class="d">${esc(m.d)}</div></div>`).join('')}
    </div>
    <div class="section-gap"></div>
    <button class="btn primary" onclick="location.hash='#/pjsk/cards'">先去逛逛卡牌图鉴 →</button>
  </div>`;
}

export async function renderAbout(app) {
  app.innerHTML = '<div class="loading-block">正在加载…</div>';
  let version = '';
  try {
    version = (await (await fetch('/api/status')).json()).version || '';
  } catch (e) { /* 状态接口失败不阻塞页面 */ }
  app.innerHTML = `
  <div class="detail-head">
    <div>
      <div class="page-title">关于 <span class="hl">卡牌雷达</span></div>
      <div class="page-desc">本地卡牌镜像站 · 自动周更 · 省存储设计${version ? ` · 服务版本 v${version}` : ''}</div>
    </div>
  </div>
  <div class="section-gap"></div>
  <div class="info-grid">
    <div class="card-panel">
      <h3 style="margin-bottom:10px">🗓️ 自动更新（双通道自启）</h3>
      <div style="font-size:14px;color:var(--text-2);line-height:2">
        · <b>每周一 09:00</b> 由 Windows 计划任务自动运行 <code>scraper/scrape.py</code>（错过自动补跑）<br>
        · 增量抓取：<b>磁盘上已有的卡面自动跳过</b>，只下载新卡<br>
        · 若抓取失败，会<b>弹窗提醒</b>（同时写入 <code>data/logs/scrape.log</code>）<br>
        · 主数据每次运行都会刷新，卡牌资料/技能/服装始终与源站一致
      </div>
    </div>
    <div class="card-panel">
      <h3 style="margin-bottom:10px">🛡️ 服务保活（无窗口设计）</h3>
      <div style="font-size:14px;color:var(--text-2);line-height:2">
        · 网站服务以<b>隐藏窗口</b>运行（VBS 启动），没有可被误关的黑窗口<br>
        · 双通道自启：计划任务 + 启动文件夹，互为备份、可容忍重复启动<br>
        · 网站「打不开」时：<b>双击 <code>scripts\\verify_setup.cmd</code> 一键自愈</b>（补任务、补自启、拉起服务）
      </div>
    </div>
    <div class="card-panel">
      <h3 style="margin-bottom:10px">💾 存储策略</h3>
      <div style="font-size:14px;color:var(--text-2);line-height:2">
        · 常驻本地：每张卡仅保存 <b>低清缩略图</b>（约 20~40KB 的 webp）<br>
        · 按需获取：<b>PNG 原图只在点击「下载原图」时抓取</b>，由镜像服务直接写入系统「下载」文件夹<br>
        · 下载文件名规范：<code>Pjsk卡牌_编号_卡名_角色_突破前/后.png</code>，一眼可辨<br>
        · 下载走<b>主备源竞速</b>：FlClash 开启时主源通常更快、关闭时备源更快，一切以实际速度为准<br>
        · <b>🚀 AI 超分</b>：默认引擎走独立显卡的 Real-ESRGAN 动漫模型（秒级、线条发丝平滑），
          引擎缺失自动回退经典管线；档位 2K / 4K 在设置页选择<br>
        · <code>data/originals</code> 仅作内部缓存用于<b>免重复下载</b>，已下载过的原图不再消耗流量
      </div>
    </div>
    <div class="card-panel">
      <h3 style="margin-bottom:10px">🧩 模块化设计</h3>
      <div style="font-size:14px;color:var(--text-2);line-height:2">
        · 前端：导航 / 路由 / 数据层 / 页面全部独立模块，新页面零侵入接入<br>
        · 后端：API 与静态托管分离，接口集中在 <code>server/server.py</code><br>
        · 数据：<code>data/db</code> 存结构化 JSON，<code>data/thumbs</code> 存预览，<code>data/originals</code> 存 PNG 原图
      </div>
    </div>
    <div class="card-panel">
      <h3 style="margin-bottom:10px">📚 数据来源</h3>
      <div style="font-size:14px;color:var(--text-2);line-height:2">
        · 数据与素材来源：<a href="https://pjsk.moe/zh-cn/" target="_blank" rel="noopener">pjsk.moe（Moesekai）</a>官方同步使用的公开数据源<br>
        · 数据服务器：<b>JP（日本服）</b>以获得最新卡牌，中文显示经翻译覆盖层（未收录的新卡回退日文原文）<br>
        · 游戏素材版权归 © Colorful Palette / SEGA 所有，本镜像仅供个人学习研究<br>
        · 启动网站：运行项目根目录的 <code>启动网站.cmd</code>（或直接访问 127.0.0.1:8819）<br>
        · 建议把本项目目录加入安全软件白名单，防止计划任务/脚本被清理
      </div>
    </div>
  </div>`;
}
