/* 概览页：机器现状 + 快捷入口。全部数据来自 get_overview（实时读取）。 */

Pages.overview = (() => {

  function render(d) {
    const m = d.memory || {};

    UI.$('#ov-mem').innerHTML = `${UI.bytes(m.used)} <small>/ ${UI.bytes(m.total)}</small>`;
    const bar = UI.$('#ov-mem-bar');
    bar.className = UI.barClass(m.percent);
    bar.firstElementChild.style.width = `${Math.min(100, m.percent || 0)}%`;
    UI.$('#ov-mem-foot').textContent =
      `可用 ${UI.bytes(m.avail)} · 占用 ${UI.pct(m.percent)}`
      + (m.cache ? ` · 系统缓存 ${UI.bytes(m.cache)}` : '');

    // 磁盘
    const box = UI.$('#ov-disks');
    box.innerHTML = '';
    (d.disks || []).forEach((k) => {
      box.appendChild(UI.h(`
        <div>
          <div class="disk-head">
            <span>${UI.esc(k.root)}</span>
            <b>${UI.bytes(k.free)} 可用 / ${UI.bytes(k.total)}</b>
          </div>
          <div class="${UI.barClass(k.percent)}"><i style="width:${Math.min(100, k.percent)}%"></i></div>
        </div>`));
    });
    if (!(d.disks || []).length) box.innerHTML = '<div class="muted">未检测到固定磁盘</div>';

    // 规则规模
    const r = d.rules || {};
    const lv = r.by_level || {};
    const tp = d.third_party_rules || {};
    UI.$('#ov-rules').innerHTML = `${r.total || 0} <small>条规则</small>`;
    UI.$('#ov-rules-foot').textContent =
      `安全 ${lv.safe || 0} · 谨慎 ${lv.caution || 0} · 风险 ${lv.risky || 0}`;
    UI.$('#ov-tp').innerHTML =
      `${(tp.safe || 0) + (tp.caution || 0) + (tp.files || 0)} <small>个目录</small>`;
    UI.$('#ov-tp-foot').textContent =
      `缓存 ${tp.safe || 0} · 谨慎 ${tp.caution || 0} · 按模式 ${tp.files || 0}`;

    // 回收站
    const rb = d.recycle_bin || {};
    UI.$('#ov-rb').innerHTML = `${UI.bytes(rb.size)} <small>/ ${rb.items || 0} 项</small>`;
    UI.$('#ov-rb-foot').textContent = rb.accessible ? '可在垃圾清理页清空' : '回收站不可访问';

    // 权限
    const badge = UI.$('#admin-badge');
    badge.className = `badge ${d.admin ? 'badge-ok' : 'badge-warn'}`;
    badge.textContent = d.admin ? '管理员权限' : '普通权限';
    UI.$('#relaunch-btn').disabled = !!d.admin;
    Store.state.ui.admin = !!d.admin;
  }

  async function refresh() {
    const d = await Bridge.call('get_overview');
    if (!d || d.ok === false) {
      UI.toast((d && d.error) || '读取概览失败', 'err');
      return null;
    }
    Store.state.overview = d;
    render(d);
    return d;
  }

  /* ---------------------------------------------------------- 环境自检 */
  let tracker = null;

  async function runDiag() {
    if (tracker) return;                       // 已经在跑就别重入
    UI.logClear('#diag-log');
    UI.$('#diag-btn').disabled = true;
    UI.$('#diag-state').className = 'badge badge-warn';
    UI.$('#diag-state').textContent = '运行中';

    const r = await Bridge.call('start_diag');
    if (!r || r.ok === false) {
      UI.logAppend('#diag-log', (r && r.error) || '启动失败', true);
      UI.$('#diag-btn').disabled = false;
      return;
    }

    tracker = Bridge.track(r.job_id, (s) => {
      (s.logs || []).forEach((line) => UI.logAppend('#diag-log', line));

      if (s.state === 'running') {
        if (s.progress) UI.$('#diag-progress').textContent = s.progress;
        return;
      }
      tracker = null;
      UI.$('#diag-btn').disabled = false;
      UI.$('#diag-progress').textContent = `耗时 ${UI.duration(s.elapsed)}`;
      if (s.state === 'done') {
        UI.$('#diag-state').className = 'badge badge-ok';
        UI.$('#diag-state').textContent = '已完成';
        const res = s.result || {};
        UI.logAppend('#diag-log', '');
        UI.logAppend('#diag-log',
          `结论：内存 ${UI.bytes(res.mem_total)} · 进程 ${res.processes} 个`
          + ` · 规则 ${res.rules} 条 · ${res.admin ? '管理员' : '普通用户'}`);
      } else if (s.state === 'cancelled') {
        UI.$('#diag-state').className = 'badge badge-mute';
        UI.$('#diag-state').textContent = '已取消';
      } else {
        UI.$('#diag-state').className = 'badge badge-danger';
        UI.$('#diag-state').textContent = '出错';
        UI.logAppend('#diag-log', s.error || '未知错误', true);
      }
    });
  }

  async function enter() {
    await refresh();
  }

  function init() {
    UI.$('#ov-refresh').addEventListener('click', refresh);
    UI.$('#ov-to-memory').addEventListener('click', () => Router.go('memory'));
    UI.$('#ov-to-junk').addEventListener('click', () => Router.go('junk'));
    UI.$('#diag-btn').addEventListener('click', runDiag);
  }

  return { init, enter, refresh, runDiag };
})();
