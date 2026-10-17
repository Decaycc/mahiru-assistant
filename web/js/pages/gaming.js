/* 游戏与性能页：Winhance 游戏/性能调校（116 项）。
 *
 * 游戏优先级与电源计划在「内存优化」页（memory.js）。
 *
 * 调校项全部写注册表/计划任务/PowerShell，写前后端会备份旧值到
 * config/winhance_config.json，所以「默认值」能真正还原，不是假按钮。
 */

Pages.gaming = (() => {
  const GROUP_ORDER = [
    '处理器', '显卡', '网络', '系统服务', '计划任务',
    '视觉效果', 'Xbox', '安全', '辅助功能', '其他',
  ];

  /* ------------------------------------------------------------ Winhance 调校 */
  let tunes = [];
  let filterGroup = null;
  let searchTerm = '';
  let states = {};        // id -> {state, label}，来自 gaming_states
  let statesLoaded = false;

  async function loadTunes() {
    const d = await Bridge.call('gaming_list');
    if (!d || d.ok === false) {
      UI.$('#tune-list').innerHTML =
        `<div class="empty err">${UI.esc((d && d.error) || '读取失败')}</div>`;
      return;
    }
    tunes = d.tunes || [];
    renderGroupTabs();
    // 先不渲染列表（那会把所有开关画成"关"），等真实状态回来再画。
    await loadStates();
  }

  /* 读全部真实状态；超过 200ms 才显示加载动画（快速加载不闪骨架）。 */
  async function loadStates() {
    if (!tunes.length) return;
    let timer = setTimeout(showSkeleton, 200);
    const d = await Bridge.call('gaming_states');
    clearTimeout(timer);
    states = (d && d.ok) ? (d.states || {}) : {};
    statesLoaded = true;
    renderTunes();
  }

  function showSkeleton() {
    const n = Math.min(visibleTunes().length, 6);
    UI.$('#tune-list').innerHTML =
      `<div class="skeleton" aria-hidden="true">${
        Array.from({ length: n }, () =>
          '<div class="tune-row skel"><div class="skel-bar w60"></div>' +
          '<div class="skel-bar w16"></div></div>').join('')
      }</div>`;
  }

  function groups() {
    const seen = new Set();
    const list = [];
    (tunes || []).forEach((t) => {
      const g = t.group || '其他';
      if (!seen.has(g)) { seen.add(g); list.push(g); }
    });
    // 按固定顺序排；未知组排最后
    return list.sort((a, b) => {
      const ia = GROUP_ORDER.indexOf(a);
      const ib = GROUP_ORDER.indexOf(b);
      if (ia === -1 && ib === -1) return a.localeCompare(b);
      if (ia === -1) return 1;
      if (ib === -1) return -1;
      return ia - ib;
    });
  }

  function renderGroupTabs() {
    if (filterGroup === null) filterGroup = groups()[0] || null;
    const gs = groups();
    UI.$('#tune-groups').innerHTML = gs.map((g) => {
      const count = tunes.filter((t) => (t.group || '其他') === g).length;
      return `<button class="tab${g === filterGroup ? ' active' : ''}"
                data-group="${UI.esc(g)}">${UI.esc(g)} ${count}</button>`;
    }).join('');
  }

  function visibleTunes() {
    let list = tunes.filter((t) => (t.group || '其他') === filterGroup);
    if (searchTerm) {
      const q = searchTerm.toLowerCase();
      list = list.filter((t) =>
        t.name.toLowerCase().includes(q) || t.desc.toLowerCase().includes(q));
    }
    return list;
  }

  function tuneRow(t) {
    const restart = t.requires_restart
      ? '<span class="badge badge-mute">需重启</span>' : '';

    const st = states[t.id] || {};
    let control;
    if (t.input_type === 'selection') {
      control = `<select class="select" data-tune="${UI.esc(t.id)}">${
        (t.options || []).map((o, i) =>
          `<option value="${i}"${st.state === i ? ' selected' : ''}>${UI.esc(o.display)}</option>`).join('')
      }</select>`;
    } else {
      control = `<input type="checkbox" class="switch" data-tune="${UI.esc(t.id)}"${st.state === true ? ' checked' : ''}>`;
    }

    return `
      <div class="tune-row" data-id="${UI.esc(t.id)}">
        <div class="tune-main">
          <div class="tune-name">
            <b>${UI.esc(t.name)}</b>${restart}
          </div>
          <div class="tune-desc">${UI.esc(t.desc || '')}</div>
        </div>
        <div class="tune-ctl">${control}</div>
        <div class="tune-acts">
          <button class="btn btn-sm" data-rec="${UI.esc(t.id)}"
                  title="设为推荐值：${UI.esc(t.value_hint || '')}">推荐值</button>
          <button class="btn btn-sm" data-def="${UI.esc(t.id)}"
                  title="还原为默认值：${UI.esc(t.default_hint || '')}">默认值</button>
        </div>
      </div>`;
  }

  function renderTunes() {
    const list = visibleTunes();
    UI.$('#tune-count').textContent =
      `${list.length} / ${tunes.length} 项`;
    // 表情包：游戏模式（gaming-game-mode）开启时显示兴奋表情
    const st = states['gaming-game-mode'];
    const sticker = UI.$('#game-sticker');
    if (sticker) sticker.classList.toggle('hide', st.state !== true);
    UI.$('#tune-list').innerHTML = list.length
      ? list.map(tuneRow).join('')
      : '<div class="empty">没有匹配的设置</div>';
  }

  async function applyTune(tuneId, value) {
    const r = await Bridge.call('gaming_apply', tuneId, value);
    if (!r || r.ok === false) {
      UI.toast((r && (r.error || r.message)) || '应用失败', 'err');
      return false;
    }
    UI.toast(r.message || '已应用');
    await refreshStates();
    return true;
  }

  async function refreshStates() {
    const d = await Bridge.call('gaming_states');
    states = (d && d.ok) ? (d.states || {}) : {};
    renderTunes();
  }

  async function applyRecommended(tuneId) {
    const r = await Bridge.call('gaming_recommended', tuneId);
    if (!r || r.ok === false) {
      UI.toast((r && (r.error || r.message)) || '设置失败', 'err');
      return;
    }
    UI.toast(r.message || '已设为推荐值');
    await refreshStates();
  }

  async function applyDefault(tuneId) {
    const r = await Bridge.call('gaming_default', tuneId);
    if (!r || r.ok === false) {
      UI.toast((r && (r.error || r.message)) || '还原失败', 'err');
      return;
    }
    UI.toast(r.message || '已还原为默认值');
    await refreshStates();
  }

  /* ------------------------------------------------------------ 事件 */
  function bind() {
    /* --- Winhance 调校 --- */
    UI.$('#tune-groups').addEventListener('click', (e) => {
      const btn = e.target.closest('[data-group]');
      if (!btn) return;
      filterGroup = btn.dataset.group;
      UI.$$('#tune-groups .tab').forEach((b) =>
        b.classList.toggle('active', b === btn));
      renderTunes();
    });

    UI.$('#tune-search').addEventListener('input', (e) => {
      searchTerm = e.target.value.trim();
      renderTunes();
    });

    UI.$('#tune-list').addEventListener('change', (e) => {
      const el = e.target;
      if (el.matches('[data-tune]')) {
        const val = el.type === 'checkbox' ? el.checked : Number(el.value);
        applyTune(el.dataset.tune, val);
      }
    });

    UI.$('#tune-list').addEventListener('click', (e) => {
      const rec = e.target.closest('[data-rec]');
      const def = e.target.closest('[data-def]');
      if (rec) applyRecommended(rec.dataset.rec);
      else if (def) applyDefault(def.dataset.def);
    });
  }

  /* ------------------------------------------------------------ 进入 */
  async function enter() {
    if (!tunes.length) await loadTunes();
  }

  function init() { bind(); }

  return { init, enter };
})();
