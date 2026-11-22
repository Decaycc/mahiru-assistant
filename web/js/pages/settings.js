/* 设置页：软件功能 / 关于 / 软件更新。
   提权入口 relaunch 仍被顶栏 #relaunch-btn 与内存页 #mem-relaunch 调用，必须保留。 */

Pages.settings = (() => {

  // 更新检查走真实后端（bridge.check_update 读 GitHub Releases 最新 tag）。
  // 下载走 open_url 白名单；NEW_URL 仅作为后端未返回 url 时的兜底。
  const NEW_URL = 'https://github.com/Decaycc/mahiru-assistant/releases/latest';
  const GITHUB_URL = 'https://github.com/Decaycc/mahiru-assistant';

  let checkBtn = null;
  let stLatest = null;
  let stNew = null;
  let stNewVer = null;
  let btnLabel = null;
  let checking = false;

  /* 提权。会重启进程，所以顺序很关键：
     先把界面状态落盘 → 再发起提权 → 用户重新打开后能恢复。 */
  async function relaunch() {
    const r = await Bridge.call('relaunch_admin');
    if (r && r.ok) {
      UI.toast('已发起提权，正在关闭本窗口…');
      // 必须真的关掉本进程：新进程在等本进程退出（两者共用同一个
      // WebView2 用户数据目录，不能同时打开），不关就会留下两个窗口。
      await Bridge.call('quit_app');
    } else {
      UI.toast((r && (r.message || r.error)) || '提权失败', 'err');
    }
    return r;
  }

  function openUrl(url) {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.open_url) {
      window.pywebview.api.open_url(url);
    } else {
      // 桥未就绪时静默占位；真实项目里进入此分支说明 waitReady 没等到。
      console.warn('[settings] open_url 不可用 -> ' + url);
    }
  }

  function setStatus(show) {
    if (stLatest) stLatest.classList.remove('show');
    if (stNew) stNew.classList.remove('show');
    if (show) show.classList.add('show');
  }

  async function checkUpdate() {
    if (checking) return;
    checking = true;
    checkBtn.classList.add('loading');
    checkBtn.disabled = true;
    setStatus(null);
    btnLabel.textContent = '检查更新';

    const r = await Bridge.call('check_update');
    checking = false;
    checkBtn.classList.remove('loading');
    checkBtn.disabled = false;

    if (!r || !r.ok) {
      UI.toast((r && (r.error || r.message)) || '检查更新失败，请稍后再试', 'err');
      return;
    }
    if (r.has_update) {
      setStatus(stNew);
      if (stNewVer) stNewVer.textContent = 'v' + r.latest;
      checkBtn.classList.add('download');
      btnLabel.textContent = '下载更新';
      checkBtn.setAttribute('data-url', r.url || NEW_URL);
    } else {
      setStatus(stLatest);
      checkBtn.classList.remove('download');
      btnLabel.textContent = '检查更新';
      checkBtn.removeAttribute('data-url');
    }
  }

  function enter() {
    refreshVersion();
  }

  async function refreshVersion() {
    try {
      const info = await Bridge.call('get_app_info');
      const el = document.getElementById('settings-version');
      if (el && info && info.ok && info.version) {
        el.textContent = `v${info.version}`;
      }
    } catch (e) { /* 版本号标签已有兜底值，拉取失败不打断设置页 */ }
  }

  function init() {
    checkBtn = document.getElementById('settings-check');
    stLatest = document.getElementById('st-latest');
    stNew = document.getElementById('st-new');
    stNewVer = document.getElementById('st-new-ver');
    const githubBtn = document.getElementById('settings-github');
    if (checkBtn) btnLabel = checkBtn.querySelector('.check-label');

    if (checkBtn) {
      checkBtn.addEventListener('click', () => {
        const url = checkBtn.getAttribute('data-url');
        if (url) openUrl(url);       // 已是「下载更新」态 → 直接打开
        else checkUpdate();
      });
    }
    if (githubBtn) {
      githubBtn.addEventListener('click', () => openUrl(GITHUB_URL));
    }
  }

  return { init, enter, relaunch };
})();
