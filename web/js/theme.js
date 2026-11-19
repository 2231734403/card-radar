// 主题：随游戏模块切换的全局配色。
// 切换瞬间给 html 挂 .theme-anim 类 → CSS 通配 transition 让全站颜色平滑渐变；
// 不挂类（animate=false）则直接对齐主题色（初始加载 / 手输链接跳转用）。
// （不用 @property+transition：实测本环境会把注册变量冻结在初始值，见 HANDOFF T17。）
const KNOWN = ['pjsk', 'bandori', 'onotes', 'sc'];
let _timer = null;

export function applyTheme(moduleId, animate = true) {
  const html = document.documentElement;
  const next = KNOWN.includes(moduleId) ? moduleId : 'pjsk';
  if (html.dataset.theme === next) {
    html.dataset.theme = next;
    return;
  }
  if (animate) html.classList.add('theme-anim');
  html.dataset.theme = next;
  if (animate) {
    clearTimeout(_timer);
    _timer = setTimeout(() => html.classList.remove('theme-anim'), 700);
  }
}
