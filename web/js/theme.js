// 主题与深浅外观引擎（正交控制 data-theme 与 data-mode）
// 严守 T10 教训：不使用 @property + transition（部分环境会冻结自定义属性），
// 统一在切换瞬间挂 html.theme-anim 类 650ms，驱动平滑色彩过渡。

let _animTimer = null;
let _mediaQuery = null;

function triggerTransition(animate) {
  const root = document.documentElement;
  if (!animate) return;
  root.classList.add('theme-anim');
  clearTimeout(_animTimer);
  _animTimer = setTimeout(() => root.classList.remove('theme-anim'), 680);
}

/** 切换游戏品牌主题色：pjsk | bandori | onotes | sc */
export function applyTheme(themeId, animate = true) {
  const root = document.documentElement;
  triggerTransition(animate);
  if (!themeId || themeId === 'pjsk') {
    root.removeAttribute('data-theme');
  } else {
    root.setAttribute('data-theme', themeId);
  }
}

function resolveMode(mode) {
  if (mode === 'dark' || mode === 'light') return mode;
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

/** 切换浅色/深色外观模式：light | dark | auto */
export function applyColorMode(mode = 'light', animate = true) {
  const root = document.documentElement;
  triggerTransition(animate);
  const effective = resolveMode(mode);
  root.setAttribute('data-mode', effective);
  if (mode === 'auto' && window.matchMedia) {
    if (!_mediaQuery) {
      _mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
      _mediaQuery.addEventListener('change', () => {
        if (document.documentElement.dataset.modePref === 'auto') {
          applyColorMode('auto', true);
        }
      });
    }
  }
  root.dataset.modePref = mode;
  return effective;
}

export function currentEffectiveMode() {
  return document.documentElement.getAttribute('data-mode') || 'light';
}
