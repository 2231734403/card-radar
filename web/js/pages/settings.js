// 设置页：个性化偏好，模块化分节（新增设置项只需加一节卡片）。
import { esc } from '../ui.js?v=1.16.2';
import { getSettings, setSetting } from '../userSettings.js?v=1.16.2';
import { resetFabPos } from '../dlpanel.js?v=1.16.2';
import { cacheStats, cacheClear, fetchStatus } from '../api.js?v=1.16.2';

const SR_OPTIONS = [
  { v: "4k", title: "4K 超清", desc: "长边 3840 · 2520×1440 源 → 3840×2194", tag: "壁纸首选 · 推荐" },
  { v: "2k", title: "2K 高清", desc: "长边 2560 · 更小体积、生成更快", tag: "轻量" },
];

const SR_ENGINE_OPTIONS = [
  { v: "ai", title: "AI 超分", desc: "Real-ESRGAN 动漫模型 · 独立显卡 Vulkan 推理 · 秒级完成", tag: "首选 · 推荐" },
  { v: "pillow", title: "经典管线", desc: "LANCZOS 渐进放大 · 无显卡要求 · 约 10~40 秒", tag: "备选 · 稳定" },
];

export function renderSettings(app) {
  const s = getSettings();
  app.innerHTML = `
  <div class="detail-head">
    <div>
      <div class="page-title">⚙️ 设置</div>
      <div class="page-desc">个性化偏好 · 保存在浏览器本地，即改即用</div>
    </div>
  </div>
  <div class="section-gap"></div>
  <div class="info-grid">
    <div class="card-panel">
      <h3 style="margin-bottom:8px">✨ 超分辨率档位</h3>
      <p style="font-size:13px;color:var(--text-3);margin-bottom:12px">
        下载面板里每个条目的「✨ 超分」按钮按此档位执行；两种档位生成后可并存，按钮旁会显示 ✓ 标记。</p>
      <div class="option-cards" id="sr-opts">
        ${SR_OPTIONS.map(o => `
          <button class="opt-card ${s.srTarget === o.v ? 'on' : ''}" data-v="${o.v}">
            <b>${esc(o.title)}</b>
            <span>${esc(o.desc)}</span>
            <em>${esc(o.tag)}</em>
          </button>`).join('')}
      </div>
    </div>
    <div class="card-panel">
      <h3 style="margin-bottom:8px">🚀 超分引擎</h3>
      <p style="font-size:13px;color:var(--text-3);margin-bottom:12px">
        默认走 AI 引擎：借独立显卡的 Vulkan 算力跑 Real-ESRGAN 动漫模型（无需 CUDA、零 Python 依赖），
        线条与发丝明显更优秀、秒级完成；引擎缺失或推理失败自动回退经典管线。
        <span id="ai-engine-state"></span></p>
      <div class="option-cards" id="sr-engine-opts">
        ${SR_ENGINE_OPTIONS.map(o => `
          <button class="opt-card ${s.srEngine === o.v ? 'on' : ''}" data-v="${o.v}">
            <b>${esc(o.title)}</b>
            <span>${esc(o.desc)}</span>
            <em>${esc(o.tag)}</em>
          </button>`).join('')}
      </div>
    </div>
    <div class="card-panel">
      <h3 style="margin-bottom:8px">🧹 缓存管理</h3>
      <p style="font-size:13px;color:var(--text-3);margin-bottom:12px">
        已下载图片的内部缓存（原图 + 各档超分图）。清除后「在线查看」与重复超分将需要重新抓取；
        「下载」文件夹里的成品不受影响。</p>
      <div class="cache-stats" id="cache-stats">统计中…</div>
      <button class="btn small" id="cache-clear" style="margin-top:12px">🗑️ 清除图片缓存</button>
    </div>
    <div class="card-panel">
      <h3 style="margin-bottom:8px">📥 下载面板</h3>
      <div style="font-size:13.5px;color:var(--text-2);line-height:2">
        · 左下角<b>下载球</b>是悬浮的：按住拖到屏幕任意位置，面板会贴随出现，位置自动记忆<br>
        · 轻点下载球 = 开/合面板；面板里集中处理下载与超分：进度、竞速源、成败原因<br>
        · 完成的条目可直接超分、点击查看大图<br>
        · <button class="btn small" id="reset-fab-pos">⌖ 复位下载球位置</button>
      </div>
    </div>
    <div class="card-panel">
      <h3 style="margin-bottom:8px">🧩 预留扩展</h3>
      <div style="font-size:13.5px;color:var(--text-3);line-height:2">
        · 默认排序、每页数量、主题色…后续版本将在此页陆续加入<br>
        · 设置页为模块化结构：新设置项 = 一节卡片 + userSettings.js 一个默认值
      </div>
    </div>
  </div>`;

  app.querySelectorAll("#sr-opts .opt-card").forEach(el => {
    el.onclick = () => {
      setSetting("srTarget", el.dataset.v);
      app.querySelectorAll("#sr-opts .opt-card").forEach(x =>
        x.classList.toggle("on", x === el));
    };
  });
  app.querySelectorAll("#sr-engine-opts .opt-card").forEach(el => {
    el.onclick = () => {
      setSetting("srEngine", el.dataset.v);
      app.querySelectorAll("#sr-engine-opts .opt-card").forEach(x =>
        x.classList.toggle("on", x === el));
    };
  });
  // AI 引擎就绪状态（/api/status 的 aiEngine 字段）
  fetchStatus().then(st => {
    const el = app.querySelector("#ai-engine-state");
    if (!el) return;
    el.innerHTML = st.aiEngine
      ? '<span style="color:var(--primary-strong)">引擎就绪 ✓（Real-ESRGAN · Vulkan）</span>'
      : '<span style="color:var(--danger)">⚠ 引擎未安装（ai_engine/），暂回退经典管线</span>';
  }).catch(() => {});
  const rf = app.querySelector("#reset-fab-pos");
  if (rf) {
    rf.onclick = () => {
      resetFabPos();
      rf.textContent = "⌖ 已复位";
      setTimeout(() => { rf.textContent = "⌖ 复位下载球位置"; }, 1500);
    };
  }

  // 缓存统计与清除
  const statsEl = app.querySelector("#cache-stats");
  const clearBtn = app.querySelector("#cache-clear");
  async function refreshStats() {
    try {
      const st = await cacheStats();
      statsEl.innerHTML = st.count
        ? `<span class="badge chip">📦 ${st.count} 个文件</span>
           <span class="badge chip" style="margin-left:6px">💾 ${st.mb} MB</span>
           <span style="font-size:12px;color:var(--text-3);margin-left:6px">（data/originals 内部缓存）</span>`
        : '<span style="font-size:13px;color:var(--text-3)">缓存为空 ✓</span>';
      clearBtn.disabled = !st.count;
    } catch (e) {
      statsEl.textContent = '统计失败：' + e.message;
    }
  }
  refreshStats();
  clearBtn.onclick = async () => {
    clearBtn.disabled = true;
    clearBtn.textContent = '清除中…';
    try {
      const r = await cacheClear();
      statsEl.innerHTML = `<span style="font-size:13px;color:var(--primary-strong)">✓ 已清除 ${r.removed} 个文件，释放 ${r.freedMB} MB</span>`;
    } catch (e) {
      statsEl.innerHTML = `<span style="color:var(--danger);font-size:13px">清除失败：${esc(e.message)}</span>`;
    }
    setTimeout(refreshStats, 400);
    clearBtn.disabled = false;
    clearBtn.textContent = '🗑️ 清除图片缓存';
  };
}
