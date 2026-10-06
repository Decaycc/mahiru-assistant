/* ===========================================================================
   启动引导。
   职责：等桥就绪 -> 取应用信息 -> 初始化各页 -> 启动路由 -> 显示界面。

   注意：全局的 Pages 容器在 index.html 里用 <script>var Pages = {};</script>
   提前声明（页面脚本要先于本文件加载并往它上面挂载）。
   =========================================================================== */

async function boot() {
  Store.initTheme();

  /* 全局按钮 */
  UI.$('#theme-btn').addEventListener('click', () => {
    Store.toggleTheme();
    if (Pages.settings) Pages.settings.syncThemeButton();
  });

  /* 提权（顶栏）。提权会重启进程，所以先把配置落盘。 */
  UI.$('#relaunch-btn').addEventListener('click', () => Pages.settings.relaunch());

  /* 各页初始化 */
  Pages.overview.init();
  Pages.memory.init();
  Pages.junk.init();
  Pages.tools.init();
  Pages.settings.init();

  Router.register('overview', Pages.overview.enter);
  Router.register('memory', Pages.memory.enter);
  Router.register('junk', Pages.junk.enter);
  Router.register('tools', Pages.tools.enter);
  Router.register('settings', Pages.settings.enter);

  try {
    await Bridge.waitReady();

    const info = await Bridge.call('get_app_info');
    if (info && info.ok) {
      UI.$('#ver').textContent = `v${info.version}`;
      UI.$('#env-note').textContent =
        `Python ${info.python}${info.frozen ? ' · 打包运行' : ' · 源码运行'}`;
    }

    const ov = await Pages.overview.refresh();
    if (ov) {
      // 管理员状态也要给设置页用
      Store.state.ui.admin = !!ov.admin;
    }

    Router.init();
    UI.$('#boot').style.display = 'none';
    Store.state.ui.ready = true;
    Store.emit('ready');
  } catch (e) {
    UI.$('#boot').innerHTML =
      `<div class="err-box">后端连接失败<br>${UI.esc(e.message)}</div>`;
  }
}

/* Python 侧窗口就绪后会调用这个（见 main.py 的 _on_start） */
window.__dshReady = () => {
  const b = UI.$('#boot');
  if (b) b.style.display = 'none';
};

/* 把模块挂到 window 上：一是方便调试与自动化直接从外部驱动，
   二是 const 声明只产生词法绑定，Python 侧 evaluate_js 里写 window.X 会取不到。 */
window.App = { UI, Store, Router, Bridge, Pages };

document.addEventListener('DOMContentLoaded', boot);
