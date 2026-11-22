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

    // 表情包：内存占用偏高（>=75%）时收起，保持克制，不渲染"紧张"情绪。
    const memSticker = document.querySelector('[data-sticker="mem"]');
    if (memSticker) memSticker.classList.toggle('hide', (m.percent || 0) >= 75);

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

    // 规则规模（并入内存主卡右侧的小统计）
    const r = d.rules || {};
    const lv = r.by_level || {};
    const tp = d.third_party_rules || {};
    UI.$('#ov-rules').innerHTML = `${r.total || 0} <small>条</small>`;
    UI.$('#ov-rules-foot').textContent =
      `安全 ${lv.safe || 0} · 谨慎 ${lv.caution || 0} · 风险 ${lv.risky || 0}`;
    UI.$('#ov-tp').innerHTML =
      `${(tp.safe || 0) + (tp.caution || 0) + (tp.files || 0)} <small>个</small>`;
    UI.$('#ov-tp-foot').textContent =
      `缓存 ${tp.safe || 0} · 谨慎 ${tp.caution || 0} · 按模式 ${tp.files || 0}`;

    // 回收站
    const rb = d.recycle_bin || {};
    UI.$('#ov-rb').innerHTML = `${UI.bytes(rb.size)} <small>/ ${rb.items || 0} 项</small>`;
    UI.$('#ov-rb-foot').textContent = rb.accessible ? '可在垃圾清理页清空' : '回收站不可访问';

    // 权限：已经是管理员时，"以管理员重启"既没用也没意义，直接收起来
    const badge = UI.$('#admin-badge');
    badge.className = `badge ${d.admin ? 'badge-ok' : 'badge-warn'}`;
    badge.textContent = d.admin ? '管理员权限' : '普通权限';
    const relaunch = UI.$('#relaunch-btn');
    relaunch.disabled = !!d.admin;
    relaunch.classList.toggle('hide', !!d.admin);
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

  async function enter() {
    await refresh();
  }

  function init() {
    UI.$('#ov-refresh').addEventListener('click', refresh);
    UI.$('#ov-to-memory').addEventListener('click', () => Router.go('memory'));
    UI.$('#ov-to-junk').addEventListener('click', () => Router.go('junk'));
  }

  return { init, enter, refresh };
})();
