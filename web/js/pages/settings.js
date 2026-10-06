/* 设置页：主题、权限、环境信息、配置的读写。 */

Pages.settings = (() => {

  function renderTheme() {
    const dark = Store.state.ui.theme === 'dark';
    UI.$('#set-dark').checked = dark;
    UI.$('#theme-btn').classList.toggle('on', dark);
    // 按钮文字要说「点了会变成什么」，而不是一直写「深色模式」——
    // 之前不管当前是什么主题都显示「深色模式」，看不出当前状态。
    const label = UI.$('#theme-label');
    if (label) label.textContent = dark ? '浅色模式' : '深色模式';
    const hint = UI.$('#set-dark-hint');
    if (hint) hint.textContent = dark ? '当前是深色模式' : '当前是浅色模式（默认）';
  }

  async function renderEnv() {
    const info = await Bridge.call('get_app_info');
    const ov = Store.state.overview;
    UI.$('#set-env').innerHTML = [
      ['版本', info && info.ok ? `v${info.version}` : '—'],
      ['作者', info && info.ok ? (info.author || '—') : '—'],
      ['运行方式', info && info.frozen ? '打包 EXE' : '源码运行'],
      ['Python', info && info.ok ? info.python : '—'],
      ['权限', ov ? (ov.admin ? '管理员' : '普通用户') : '—'],
      ['配置文件', 'config/junkclean_config.json'],
      ['界面存储', 'config/webview'],
    ].map(([k, v]) =>
      `<dt>${UI.esc(k)}</dt><dd>${UI.esc(v)}</dd>`).join('');
  }

  /* 提权。会重启进程，所以顺序很关键：
     先把界面状态落盘 → 再发起提权 → 用户重新打开后能恢复。 */
  async function relaunch() {
    await Bridge.call('save_config', { theme: Store.state.ui.theme });
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

  function bind() {
    UI.$('#set-dark').addEventListener('change', (e) => {
      Store.setTheme(e.target.checked ? 'dark' : 'light');
      renderTheme();
    });

    UI.$('#set-diagnose').addEventListener('click', async () => {
      // 自检面板在概览页，跳过去并直接开跑
      await Router.go('overview');
      const card = UI.$('#diag-card');
      if (card) card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      Pages.overview.runDiag();
    });
    UI.$('#set-open-config').addEventListener('click', async () => {
      const r = await Bridge.call('open_in_explorer', 'config');
      if (r && r.ok === false) UI.toast(r.error || '打开失败', 'err');
    });
    UI.$('#set-relaunch').addEventListener('click', relaunch);

    /* --- 清理规则库 --- */
    UI.$('#rules-update').addEventListener('click', () => runRuleUpdate(false));
    UI.$('#rules-offline').addEventListener('click', () => runRuleUpdate(true));
    UI.$('#rules-check').addEventListener('click', checkRuleUpdate);
  }

  /* ---------------------------------------------------- 清理规则库 */

  async function renderRules() {
    const d = await Bridge.call('rules_info');
    if (!d || d.ok === false) {
      UI.$('#rules-status').textContent = '读取失败';
      return;
    }
    const m = d.matched || {};
    UI.$('#rules-status').innerHTML =
      `本机命中 <b>${d.matched_total}</b> 个目录`
      + `（缓存 ${m.safe || 0} · 谨慎 ${m.caution || 0}`
      + ` · 按模式 ${m.files || 0}）`;

    const badge = UI.$('#rules-badge');
    // 「已更新」是在说规则来自可写目录那份，不是「已是最新」——
    // 要不容易被误读成「刚检查过、无需更新」。
    badge.textContent = d.using_override ? '用更新版' : '内置版';
    badge.title = d.using_override
      ? '正在使用你更新过的规则（配置目录里那份）'
      : '正在使用程序内置的规则，还没更新过';
    badge.className = 'badge ' + (d.using_override ? 'badge-ok' : 'badge-mute');

    // versions 是生成文件头部里成对出现的「来源行 + 版本行」：
    //   "* winapp2    https://github.com/..."
    //   "版本 260915 / 4,068 条 / CC-BY-SA-4.0"
    // 名字、URL、版本混在一行会很糊，所以拆成两行渲染。
    const rows = [];
    for (let i = 0; i + 1 < (d.versions || []).length; i += 2) {
      const head = (d.versions[i] || '').replace(/^\*\s*/, '');
      rows.push({
        name: head.split(/\s+/)[0] || head,
        url: (head.match(/https?:\/\/\S+/) || [''])[0],
        meta: d.versions[i + 1] || '',
      });
    }
    const box = UI.$('#rules-src');
    box.classList.toggle('hide', rows.length === 0);
    box.innerHTML = rows.map((r) => `
      <div class="src-row">
        <div class="src-head">
          <span class="src-name">${UI.esc(r.name)}</span>
          <span class="src-meta">${UI.esc(r.meta)}</span>
        </div>
        <div class="src-url" title="${UI.esc(r.url)}">${UI.esc(r.url)}</div>
      </div>`).join('');
  }

  async function checkRuleUpdate() {
    const btn = UI.$('#rules-check');
    btn.disabled = true;
    UI.toast('正在查询上游版本…');
    const d = await Bridge.call('check_rule_update');
    btn.disabled = false;
    if (!d || !d.ok) {
      UI.toast((d && d.error) || '查询失败（可能没联网）', 'warn');
      return;
    }
    const parts = Object.entries(d.sources || {})
      .map(([k, v]) => `${k} ${v.ok ? v.size + 'B' : '失败'}`);
    UI.toast('上游：' + parts.join(' · '), 'ok');
  }

  async function runRuleUpdate(offline) {
    const ids = ['rules-update', 'rules-check', 'rules-offline'];
    const setDisabled = (v) => ids.forEach((i) => {
      const el = UI.$(i);
      if (el) el.disabled = v;               // 取不到就别让整个流程崩掉
    });
    setDisabled(true);

    const status = UI.$('#rules-status');
    if (!offline) status.textContent = '正在查询接口额度…';

    try {
      const r = await Bridge.call('start_rule_update', !!offline);
      if (!r || r.ok === false) {
        status.textContent = '启动失败';
        UI.toast((r && r.error) || '启动失败', 'err');
        return;
      }

      // 任务跑多久都要有反馈：定期把「已用 Ns」刷到状态里，
      // 否则网络卡住时界面看起来就是死的。
      const t0 = Date.now();
      let lastLine = offline ? '正在用缓存重建…' : '正在联网获取…';
      status.textContent = lastLine;
      const tick = setInterval(() => {
        status.textContent =
          `${lastLine}（已用 ${Math.round((Date.now() - t0) / 1000)}s）`;
      }, 1000);

      Bridge.track(r.job_id, async (s) => {
        if (s.state === 'running') {
          if (s.logs && s.logs.length) lastLine = s.logs[s.logs.length - 1];
          else if (s.progress) lastLine = s.progress;
          return;
        }
        clearInterval(tick);
        setDisabled(false);

        const res = s.result || {};
        if (s.state !== 'done' || res.ok === false) {
          status.textContent = '更新失败，规则未改动';
          UI.toast(res.error || s.error || '更新失败', 'err');
        } else {
          UI.toast(`规则已更新：本机命中 ${res.matched_total} 个目录`);
          // 规则变了，垃圾清理页之前扫出来的结果就过期了，
          // 清掉扫描状态，下次进那一页会重新拉规则并重扫。
          // 注意 Store 没有 set()，直接改 state 字段。
          const j = Store.state.junk;
          j.results = {};
          j.scanned = false;
          j.selected = new Set();
        }
        await renderRules();
      });
    } catch (e) {
      // 任何意外都不能把按钮永久禁用 —— 那样用户再点就没反应了
      setDisabled(false);
      status.textContent = '更新出错';
      UI.toast(String(e && e.message ? e.message : e), 'err');
    }
  }

  Store.on('theme', renderTheme);

  async function enter() {
    renderTheme();
    await renderEnv();
    const admin = Store.state.ui.admin;
    UI.$('#set-relaunch').disabled = admin;
    UI.$('#set-relaunch').textContent = admin ? '已是管理员' : '以管理员重启';
    await renderRules();
  }

  function init() { bind(); }

  // 主题按钮同时出现在侧栏底部，两处状态要同步
  function syncThemeButton() { renderTheme(); }

  return { init, enter, relaunch, syncThemeButton };
})();
