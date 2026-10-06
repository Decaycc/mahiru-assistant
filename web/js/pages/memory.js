/* 内存优化页：进程列表 + 真实动作（整理 / 关闭 / 一键加速 / 优先级）。
 *
 * 安全前提：界面不做任何"这个进程能不能关"的判断，一律以后端为准。
 * 后端在 Optimizer 内部会对每个进程重新跑一遍保护判定，
 * 所以即使这里传错，也不会误杀受保护的进程。
 */

Pages.memory = (() => {
  const S = () => Store.state.mem;
  let searchTerm = '';
  let tracker = null;

  /* 一键加速的选项，默认值与后端保持一致 */
  const DEFAULT_OPTS = {
    kill_safe: true, kill_optional: false, trim: true,
    standby: true, gamedvr: false, power: false,
  };

  const PRIORITY_TEXT = {
    idle: '低', below: '低于正常', normal: '正常',
    above: '高于正常', high: '高', realtime: '实时',
  };

  /* ------------------------------------------------------------ 列表 */
  function rowHtml(p) {
    const checked = S().selected.has(p.pid) ? 'checked' : '';
    const tags = [];
    if (p.protected) {
      tags.push(`<span class="badge badge-mute" title="${UI.esc(p.why || '受保护')}">受保护</span>`);
    } else if (p.closable) {
      tags.push('<span class="badge badge-warn">可关闭</span>');
    }
    if (p.trimmable && !p.protected) tags.push('<span class="badge badge-ok">可整理</span>');

    const box = p.protected
      ? '<span class="tick-empty" title="受保护，不会关闭"></span>'
      : `<input type="checkbox" class="tick" data-pid="${p.pid}" ${checked}>`;

    return `
      <div class="prow${p.protected ? ' is-protected' : ''}" data-pid="${p.pid}">
        <div class="pcell-tick">${box}</div>
        <div class="pcell-name">
          <div class="pname">${UI.esc(p.name)}</div>
          <div class="ptitle">${UI.esc(p.title || `PID ${p.pid}`)}</div>
        </div>
        <div class="pcell-tags">${tags.join('')}</div>
        <div class="pcell-mem">${UI.bytes(p.mem)}</div>
      </div>`;
  }

  function visibleRows() {
    const m = S();
    let list = m.onlyClosable
      ? m.processes.filter((p) => p.closable || p.trimmable)
      : m.processes;
    if (searchTerm) {
      const t = searchTerm.toLowerCase();
      list = list.filter((p) => p.name.toLowerCase().includes(t));
    }
    return list;
  }

  function render() {
    const m = S();
    const list = visibleRows();

    UI.$('#mem-list').innerHTML = list.length
      ? list.map(rowHtml).join('')
      : '<div class="empty">没有匹配的进程</div>';

    UI.$('#mem-stat').textContent =
      `${list.length} / ${m.total} 个 · 可整理合计 ${UI.bytes(m.reclaimable)}`;

    const n = m.selected.size;
    UI.$('#mem-sel').textContent = `已选 ${n} 项`;
    UI.$('#mem-apply').disabled = n === 0 || busy();
    UI.$('#mem-close').disabled = n === 0 || busy();

    const all = UI.$('#mem-all');
    const selectable = list.filter((p) => !p.protected).map((p) => p.pid);
    const picked = selectable.filter((pid) => m.selected.has(pid)).length;
    all.checked = selectable.length > 0 && picked === selectable.length;
    all.indeterminate = picked > 0 && picked < selectable.length;
    all.disabled = selectable.length === 0;
  }

  /* ------------------------------------------------------------ 加载 */
  async function load(force) {
    const m = S();
    if (m.loaded && !force) return;
    UI.$('#mem-list').innerHTML = '<div class="empty">正在枚举进程…</div>';

    const [d, caps] = await Promise.all([
      Bridge.call('list_processes'),
      Bridge.call('get_capabilities'),
    ]);

    if (!d || d.ok === false) {
      UI.$('#mem-list').innerHTML =
        `<div class="empty err">${UI.esc((d && d.error) || '读取失败')}</div>`;
      return;
    }
    m.processes = d.processes || [];
    m.total = d.total || 0;
    m.trimmable = d.trimmable || 0;
    m.closable = d.closable || 0;
    m.reclaimable = d.reclaimable || 0;
    m.selected.clear();
    m.loaded = true;

    applyCapabilities(caps);
    render();
  }

  /* 权限决定哪些选项可用，不能用的直接禁用并说明原因，
     而不是让用户勾了之后执行失败 */
  function applyCapabilities(caps) {
    if (!caps || caps.ok === false) return;
    const admin = !!caps.admin;
    UI.$('#admin-banner').classList.toggle('hide', admin);

    const standbyRow = UI.$('#opt-standby-row');
    const standbyBox = standbyRow.querySelector('input');
    standbyBox.disabled = !caps.can_standby;
    standbyRow.classList.toggle('is-locked', !caps.can_standby);
    standbyRow.querySelector('i').textContent = caps.can_standby
      ? '释放文件缓存；清理后首次打开软件会略慢，属正常'
      : '需要管理员权限（点上方「以管理员重启」后可用）';

    UI.$('#mem-relaunch-closed').disabled = !caps.closed_apps;
    UI.$('#mem-relaunch-closed').textContent = caps.closed_apps
      ? `重启已关闭的应用（${caps.closed_apps}）` : '重启已关闭的应用';
    UI.$('#mem-revert').disabled = !caps.has_gamedvr_backup;
    UI.$('#mem-revert').title = caps.has_gamedvr_backup
      ? '' : '还没有改动过系统设置';
  }

  /* ------------------------------------------------------------ 选项 */
  function readOpts() {
    const o = Object.assign({}, DEFAULT_OPTS);
    UI.$$('#mem-opts input[data-opt]').forEach((el) => {
      o[el.dataset.opt] = el.checked;
    });
    return o;
  }

  function writeOpts(o) {
    UI.$$('#mem-opts input[data-opt]').forEach((el) => {
      if (el.dataset.opt in o) el.checked = !!o[el.dataset.opt];
    });
  }

  /* ------------------------------------------------------------ 任务 */
  const busy = () => !!tracker;

  function setBusy(on, title) {
    UI.$('#mem-log-card').classList.toggle('hide', !on);
    UI.$('#mem-boost').disabled = on;
    UI.$('#mem-apply').disabled = on || S().selected.size === 0;
    UI.$('#mem-close').disabled = on || S().selected.size === 0;
    if (on) {
      UI.$('#mem-log-title').textContent = title || '执行中';
      UI.$('#mem-log-state').className = 'badge badge-warn';
      UI.$('#mem-log-state').textContent = '运行中';
      UI.$('#mem-log-progress').textContent = '—';
      UI.logClear('#mem-log');
      UI.$('#mem-log-card').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  async function runJob(starter, title) {
    if (busy()) { UI.toast('已有任务在运行', 'warn'); return; }
    setBusy(true, title);

    const r = await starter();
    if (!r || r.ok === false) {
      setBusy(false);
      UI.toast((r && r.error) || '启动失败', 'err');
      return;
    }
    const before = await Bridge.call('memory_snapshot');

    tracker = Bridge.track(r.job_id, async (s) => {
      (s.logs || []).forEach((line) => UI.logAppend('#mem-log', line));
      if (s.state === 'running') {
        if (s.progress) UI.$('#mem-log-progress').textContent = s.progress;
        return;
      }

      tracker = null;
      setBusy(false);
      UI.$('#mem-log-progress').textContent = `耗时 ${UI.duration(s.elapsed)}`;
      const badge = UI.$('#mem-log-state');
      if (s.state === 'done') {
        badge.className = 'badge badge-ok';
        badge.textContent = '已完成';
        await showResult(before, s.result || {});
      } else if (s.state === 'cancelled') {
        badge.className = 'badge badge-mute';
        badge.textContent = '已取消';
      } else {
        badge.className = 'badge badge-danger';
        badge.textContent = '出错';
        UI.logAppend('#mem-log', s.error || '未知错误', true);
      }
      // 动作会改变进程列表，重新拉一次
      await load(true);
      UI.$('#mem-log-card').classList.remove('hide');
    });
  }

  async function showResult(before, result) {
    const after = await Bridge.call('memory_snapshot');
    const b = (before && before.ok !== false) ? before.avail : 0;
    const a = (after && after.ok !== false) ? after.avail : 0;
    const delta = a - b;

    const items = [];
    if (result.trimmed !== undefined) {
      items.push(['整理的进程', `${result.trimmed}`, '个']);
      if (result.skipped) items.push(['跳过（不满足条件）', `${result.skipped}`, '个']);
      // 工作集释放量与系统可用内存变化是两个不同的量，必须分开显示
      items.push(['工作集释放', UI.bytes(result.ws_freed || 0)]);
    }
    if (result.closed !== undefined) {
      items.push(['已关闭', `${result.closed}`, '个']);
      if (result.failed) items.push(['关闭失败', `${result.failed}`, '个']);
    }
    if (result.opts) {
      items.push(['执行项', Object.entries(result.opts)
        .filter(([, v]) => v).map(([k]) => ({
          kill_safe: '关安全级', kill_optional: '关可选级', trim: '整理工作集',
          standby: '清待机', gamedvr: 'GameDVR', power: '电源计划',
        }[k] || k)).join(' · ') || '（全部关闭）']);
    }
    items.push(['系统可用内存', `${UI.bytes(b)} → ${UI.bytes(a)}`]);
    items.push(['实际变化', `${delta >= 0 ? '+' : ''}${UI.bytes(Math.abs(delta))}`]);

    const card = UI.$('#mem-result');
    card.classList.remove('hide');
    card.innerHTML = `
      <div class="row-between" style="margin-bottom:12px">
        <h2 class="section-h">最近一次结果</h2>
      </div>
      <div class="result-grid">
        ${items.map(([k, v, unit], i) => `
          <div class="result-item">
            <div class="k">${UI.esc(k)}</div>
            <div class="v${i === items.length - 1 ? ' good' : ''}">
              ${UI.esc(v)}${unit ? ` <small>${UI.esc(unit)}</small>` : ''}
            </div>
          </div>`).join('')}
      </div>
      <div class="stat-foot" style="margin-top:14px">
        「工作集释放」是把闲置内存从进程里换出的量；
        「实际变化」是系统可用内存的真实增减 —— 前者通常明显大于后者，
        因为换出的页进了待机列表，仍被系统算作可用缓存。两者都正常。
      </div>`;
  }

  /* ------------------------------------------------------------ 游戏优先级 */
  let games = [];

  async function loadGames() {
    const d = await Bridge.call('list_games');
    if (!d || d.ok === false) return;
    games = d.games || [];
    const sel = UI.$('#prio-target');
    const keep = sel.value;

    sel.innerHTML = games.length
      ? games.map((g) => {
        const saved = g.saved ? ` · 记住:${g.saved}` : '';
        return `<option value="${g.pid}">${UI.esc(g.name)} — `
             + `${UI.esc(g.title)}（当前 ${UI.esc(g.priority)}${saved}）</option>`;
      }).join('')
      : '<option value="">（没有检测到有窗口的程序）</option>';
    if (keep && games.some((g) => String(g.pid) === keep)) sel.value = keep;

    UI.$('#prio-count').textContent =
      `${games.length} 个有窗口的程序`;
    UI.$('#prio-apply').disabled = games.length === 0;
    renderSaved(d.saved || {});
  }

  function renderSaved(saved) {
    const keys = Object.keys(saved);
    const box = UI.$('#prio-saved-box');
    box.classList.toggle('hide', keys.length === 0);
    UI.$('#prio-saved-list').innerHTML = keys.map((k) => `
      <span class="saved-chip">${UI.esc(k)} → ${UI.esc(saved[k])}
        <button class="chip-x" data-forget="${UI.esc(k)}" title="取消记忆">×</button>
      </span>`).join('');
  }

  async function applyPriority() {
    const sel = UI.$('#prio-target');
    const pid = Number(sel.value);
    if (!pid) { UI.toast('请先选一个程序', 'warn'); return; }
    const level = UI.$('#prio-level').value;
    const g = games.find((x) => x.pid === pid);

    const r = await Bridge.call('set_priority', pid, level);
    if (!r || r.ok === false) {
      UI.toast((r && (r.error || r.message)) || '设置失败', 'err');
      return;
    }
    UI.toast(`${g ? g.name : 'PID ' + pid} 优先级已设为「${r.level}」`);

    if (UI.$('#prio-remember').checked && g) {
      await Bridge.call('remember_priority', g.exe, level);
      UI.toast(`已记住：${g.name} → ${r.level}`);
    }
    await loadGames();
  }

  async function applySaved() {
    const r = await Bridge.call('apply_saved_priorities_quick');
    if (!r || r.ok === false) {
      UI.toast((r && r.error) || '没有可应用的', 'warn');
      return;
    }
    const parts = [];
    if (r.applied.length) parts.push(`成功 ${r.applied.length}`);
    if (r.failed.length) parts.push(`失败 ${r.failed.length}`);
    if (r.not_running.length) parts.push(`未运行 ${r.not_running.length}`);
    UI.toast(`已应用记住的优先级：${parts.join(' · ') || '无匹配'}`,
      r.failed.length ? 'warn' : 'ok');
    await loadGames();
  }

  /* ------------------------------------------------------------ 深度优化 */
  let deepOps = [];

  async function loadDeepOps() {
    const d = await Bridge.call('deep_ops_info');
    if (!d || d.ok === false) return;
    deepOps = d.ops || [];
    UI.$('#mem-deep-count').textContent = `${deepOps.length} 项内核接口`;
    UI.$('#mem-deep-opts').innerHTML = deepOps.map((o) => `
      <label class="opt${o.blocked ? ' is-locked' : ''}">
        <input type="checkbox" class="switch" data-deep="${o.key}"
               ${o.default ? 'checked' : ''}>
        <span>
          <b>${UI.esc(o.name)}
            ${o.needs_admin
              ? `<span class="badge ${o.blocked ? 'badge-warn' : 'badge-mute'}">`
                + `${o.blocked ? '当前会失败 · 需管理员' : '需管理员'}</span>`
              : '<span class="badge badge-ok">免管理员</span>'}
          </b>
          <i>${UI.esc(o.desc || '')}</i>
          ${o.warning ? `<i class="warn-note">⚠ ${UI.esc(o.warning)}</i>` : ''}
        </span>
      </label>`).join('');
  }

  function readDeepOpts() {
    const o = {};
    UI.$$('#mem-deep-opts input[data-deep]').forEach((el) => {
      o[el.dataset.deep] = el.checked;
    });
    return o;
  }

  function setDeepOpts(pred) {
    UI.$$('#mem-deep-opts input[data-deep]').forEach((el) => {
      const meta = deepOps.find((o) => o.key === el.dataset.deep);
      el.checked = pred(meta || {});
    });
  }

  /* ------------------------------------------------------------ 事件 */
  function bind() {
    const list = UI.$('#mem-list');

    list.addEventListener('change', (e) => {
      const cb = e.target.closest('.tick');
      if (!cb) return;
      const pid = Number(cb.dataset.pid);
      if (cb.checked) S().selected.add(pid); else S().selected.delete(pid);
      render();
    });

    list.addEventListener('click', (e) => {
      if (e.target.closest('.tick')) return;
      const row = e.target.closest('.prow');
      if (!row || row.classList.contains('is-protected')) return;
      const pid = Number(row.dataset.pid);
      if (S().selected.has(pid)) S().selected.delete(pid); else S().selected.add(pid);
      render();
    });

    UI.$('#mem-all').addEventListener('change', (e) => {
      const ids = visibleRows().filter((p) => !p.protected).map((p) => p.pid);
      if (e.target.checked) ids.forEach((i) => S().selected.add(i));
      else ids.forEach((i) => S().selected.delete(i));
      render();
    });

    UI.$('#mem-only-closable').addEventListener('change', (e) => {
      S().onlyClosable = e.target.checked;
      render();
    });

    UI.$('#mem-search').addEventListener('input', (e) => {
      searchTerm = e.target.value.trim();
      render();
    });

    /* --- 游戏优先级 --- */
    UI.$('#prio-refresh').addEventListener('click', loadGames);
    UI.$('#prio-apply').addEventListener('click', applyPriority);
    UI.$('#prio-apply-saved').addEventListener('click', applySaved);
    UI.$('#prio-saved-list').addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-forget]');
      if (!btn) return;
      await Bridge.call('remember_priority', btn.dataset.forget, '');
      UI.toast('已取消记忆');
      await loadGames();
    });

    UI.$('#mem-apply').addEventListener('click', () => runJob(
      () => Bridge.call('start_trim', Array.from(S().selected)),
      '整理工作集'));

    UI.$('#mem-close').addEventListener('click', () => runJob(
      () => Bridge.call('start_close', Array.from(S().selected), true),
      '关闭进程'));

    const boost = () => runJob(() => Bridge.call('start_boost', readOpts()),
                               '一键加速');
    UI.$('#mem-boost').addEventListener('click', boost);
    UI.$('#action-primary').addEventListener('click', boost);

    UI.$('#mem-relaunch').addEventListener('click', () => Pages.settings.relaunch());

    UI.$('#mem-relaunch-closed').addEventListener('click', () =>
      runJob(() => Bridge.call('relaunch_closed'), '重启已关闭的应用'));

    UI.$('#mem-revert').addEventListener('click', () =>
      runJob(() => Bridge.call('revert_system'), '还原系统设置'));

    UI.$('#mem-log-cancel').addEventListener('click', async () => {
      if (!tracker) return;
      // 任务 id 存在 tracker 里不好取，这里靠后端取消全部在跑的
      const r = await Bridge.call('running_jobs');
      (r.jobs || []).forEach((id) => Bridge.call('cancel', id));
    });

    /* --- 深度优化 --- */
    UI.$('#mem-deep-run').addEventListener('click', () => {
      const opts = readDeepOpts();
      const picked = Object.values(opts).filter(Boolean).length;
      if (!picked) { UI.toast('一项都没勾选', 'warn'); return; }

      // 有风险的项要二次确认，并把风险原样念一遍
      const risky = deepOps.filter((o) => opts[o.key] && o.warning);
      if (risky.length) {
        const msg = `将执行 ${picked} 项深度优化。\n\n`
          + risky.map((o) => `【${o.name}】\n${o.warning}`).join('\n\n')
          + '\n\n继续吗？';
        if (!window.confirm(msg)) return;
      }
      runJob(() => Bridge.call('start_deep_optimize', opts), '深度内存优化');
    });

    UI.$('#mem-deep-safe').addEventListener('click', () => {
      setDeepOpts((o) => !o.needs_admin);
      UI.toast('已勾选免管理员的项');
    });
    UI.$('#mem-deep-all').addEventListener('click', () => {
      setDeepOpts(() => true);
    });
  }

  async function enter() {
    await load(false);
    await loadGames();
    if (!deepOps.length) await loadDeepOps();
  }

  function init() { bind(); }

  return { init, enter, load,
           get running() { return busy(); } };
})();
