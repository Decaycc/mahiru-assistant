/* 小功能页：启动项管理 / 硬件与磁盘 / 大文件查找 / 重复文件查找。

   四项的安全约定是一致的：只读为主，写操作都可还原。
   两个查找功能全程不删任何东西。 */

Pages.tools = (() => {

  let tab = 'startup';
  let roots = [];
  let tracker = null;

  const S = () => Store.state.tools;

  function fmtSize(n) {
    if (!n) return '0 B';
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(n >= 100 || i === 0 ? 0 : 1)} ${u[i]}`;
  }

  /* ------------------------------------------------------------ 选项卡 */
  function showTab(name) {
    tab = name;
    UI.$$('#tools-tabs .tab').forEach((b) =>
      b.classList.toggle('active', b.dataset.tool === name));
    UI.$$('.tool-panel').forEach((p) =>
      p.classList.toggle('hide', p.id !== `tool-${name}`));
    if (name === 'startup' && !S().startup) loadStartup();
    if (name === 'hardware' && !S().hardware) loadHardware();
    if (name === 'large' || name === 'dup') renderRoots(name);
  }

  /* ------------------------------------------------------------ 扫描根 */
  function renderRoots(which) {
    const box = UI.$(`#${which}-roots`);
    const chosen = S()[`${which}Roots`] || [];
    box.innerHTML = roots.map((r) => `
      <label class="root-chip ${chosen.includes(r) ? 'on' : ''}">
        <input type="checkbox" value="${UI.esc(r)}"
               ${chosen.includes(r) ? 'checked' : ''}>${UI.esc(r)}
      </label>`).join('');
    box.onchange = () => {
      const picked = Array.from(
        box.querySelectorAll('input:checked')).map((i) => i.value);
      S()[`${which}Roots`] = picked;
      box.querySelectorAll('.root-chip').forEach((c) => {
        c.classList.toggle('on', c.querySelector('input').checked);
      });
    };
  }

  async function loadRoots() {
    const d = await Bridge.call('tools_roots');
    roots = (d && d.roots) || ['C:\\'];
    // 默认全选：不选的话用户点「开始」会一脸茫然
    if (!S().largeRoots) S().largeRoots = roots.slice();
    if (!S().dupRoots) S().dupRoots = roots.slice();
  }

  /* ------------------------------------------------------ 启动项管理 */
  async function loadStartup() {
    const box = UI.$('#startup-list');
    box.innerHTML = '<span class="muted">读取中…</span>';
    const d = await Bridge.call('startup_items');
    if (!d || d.ok === false) {
      box.innerHTML = `<span class="muted">读取失败</span>`;
      return;
    }
    S().startup = d.items || [];
    const on = S().startup.filter((i) => i.enabled).length;
    UI.$('#startup-count').textContent =
      `${S().startup.length} 项（启用 ${on}）`;

    if (!S().startup.length) {
      box.innerHTML = '<span class="muted">没有找到启动项</span>';
      return;
    }
    const LV = {
      broken: ['badge-mute', '已失效'],
      optional: ['badge-warn', '可按需关闭'],
      keep: ['badge-ok', '建议保留'],
      unknown: ['badge-mute', '需自行判断'],
    };
    box.innerHTML = S().startup.map((it) => {
      const [cls, text] = LV[it.level] || LV.unknown;
      return `
      <div class="entry ${it.enabled ? '' : 'off'}" data-id="${UI.esc(it.id)}">
        <div class="entry-main">
          <div class="entry-name">
            ${UI.esc(it.name)}
            <span class="badge ${cls}">${text}</span>
          </div>
          <div class="entry-why">${UI.esc(it.reason || '')}</div>
          <div class="entry-cmd" title="${UI.esc(it.path || it.command)}">
            ${UI.esc(it.path || it.command)}
          </div>
        </div>
        <button class="btn btn-sm" data-toggle="${it.enabled ? 'off' : 'on'}">
          ${it.enabled ? '禁用' : '启用'}
        </button>
      </div>`;
    }).join('');

    (d.errors || []).forEach((e) => UI.toast(e, 'warn'));
  }

  async function toggleStartup(btn) {
    const row = btn.closest('.entry');
    const id = row.dataset.id;
    const enable = btn.dataset.toggle === 'on';
    btn.disabled = true;
    const r = await Bridge.call('set_startup', id, enable);
    btn.disabled = false;
    if (!r || r.ok === false) {
      UI.toast((r && (r.error || r.message)) || '操作失败', 'err');
      return;
    }
    UI.toast(r.message || '已修改');
    await loadStartup();
  }

  /* ------------------------------------------------------ 硬件与磁盘 */
  function fmtUptime(boot) {
    if (!boot) return '';
    // WMI 的 LastBootUpTime 形如 /Date(1699999999999)/
    const m = String(boot).match(/(\d{10,})/);
    if (!m) return '';
    const d = new Date(Number(m[1]));
    if (Number.isNaN(d.getTime())) return '';
    const hrs = (Date.now() - d.getTime()) / 3600000;
    return `开机 ${Math.floor(hrs / 24)} 天 ${Math.round(hrs % 24)} 小时`;
  }

  async function loadHardware() {
    UI.$('#hw-body').innerHTML = '<span class="muted">读取中…</span>';
    const h = await Bridge.call('hardware');
    const c = (h && h.cpu) || {};
    const items = [];

    if (c.Name) {
      items.push(['处理器', c.Name.trim(),
        `${c.NumberOfCores || '?'} 核 / ${c.NumberOfLogicalProcessors || '?'} 线程`
        + (c.MaxClockSpeed ? ` · ${(c.MaxClockSpeed / 1000).toFixed(1)} GHz` : '')]);
    }
    (h && h.memory || []).forEach((m, i) => {
      items.push([`内存 ${i + 1}`, `${((m.Capacity || 0) / 1073741824).toFixed(0)} GB`,
        [m.Speed ? `${m.Speed} MHz` : '', m.Manufacturer || '',
         (m.PartNumber || '').trim()].filter(Boolean).join(' · ')]);
    });
    (h && h.gpu || []).forEach((g, i) => {
      items.push([`显卡 ${i + 1}`, (g.Name || '').trim(),
        g.DriverVersion ? `驱动 ${g.DriverVersion}` : '']);
    });
    if (h && h.board) {
      items.push(['主板', `${h.board.Manufacturer || ''} ${h.board.Product || ''}`.trim(), '']);
    }
    if (h && h.os) {
      items.push(['系统', (h.os.Caption || '').replace(/^Microsoft\s*/, ''),
        [h.os.Version, h.os.OSArchitecture, fmtUptime(h.os.LastBootUpTime)]
          .filter(Boolean).join(' · ')]);
    }

    S().hardware = h;
    UI.$('#hw-body').innerHTML = items.length
      ? `<div class="hw-grid">` + items.map(([l, v, s]) => `
          <div class="hw-item">
            <span class="hw-label">${UI.esc(l)}</span>
            <span class="hw-value">${UI.esc(v)}</span>
            ${s ? `<span class="hw-sub">${UI.esc(s)}</span>` : ''}
          </div>`).join('') + `</div>`
      : '<span class="muted">没读到硬件信息</span>';

    await loadDisk();
  }

  async function loadDisk() {
    UI.$('#disk-body').innerHTML = '<span class="muted">读取中…</span>';
    const d = await Bridge.call('disk_health');
    if (!d || d.ok === false) {
      UI.$('#disk-body').innerHTML = '<span class="muted">读取失败</span>';
      return;
    }
    const rows = [];

    (d.physical || []).forEach((p) => {
      const tb = (p.Size || 0) / 1000000000000;
      rows.push(`
        <div class="hw-item">
          <span class="hw-label">磁盘 ${p.Index} · ${UI.esc(p.InterfaceType || '')}</span>
          <span class="hw-value">${UI.esc((p.Model || '').trim())}</span>
          <span class="hw-sub">${tb.toFixed(2)} TB · 状态 ${UI.esc(p.Status || '未知')}</span>
        </div>`);
    });
    (d.volumes || []).forEach((v) => {
      const pct = v.Size ? (1 - v.FreeSpace / v.Size) * 100 : 0;
      rows.push(`
        <div class="hw-item">
          <span class="hw-label">分区 ${UI.esc(v.DeviceID)} · ${UI.esc(v.FileSystem || '')}</span>
          <span class="hw-value">${fmtSize(v.FreeSpace)} 可用 / ${fmtSize(v.Size)}</span>
          <span class="hw-sub">已用 ${pct.toFixed(0)}%${v.VolumeName ? ' · ' + UI.esc(v.VolumeName) : ''}</span>
        </div>`);
    });

    let smart = '';
    if (d.predict_available) {
      const bad = (d.predict || []).filter((p) => p.PredictFailure);
      smart = bad.length
        ? `<div class="alert alert-danger" style="margin-top:12px">
             <b>有磁盘报告即将故障</b>：${bad.map((b) => UI.esc(b.InstanceName)).join('、')}
             —— 请尽快备份重要数据。</div>`
        : `<div class="stat-foot" style="margin-top:12px;color:var(--ok)">
             SMART 失败预测：所有磁盘均正常。</div>`;
    }

    UI.$('#disk-body').innerHTML =
      (rows.length ? `<div class="hw-grid">${rows.join('')}</div>` : '') + smart
      + (d.errors || []).map((e) =>
        `<div class="stat-foot" style="margin-top:8px">${UI.esc(e)}</div>`).join('');
  }

  /* ------------------------------------------------------ 查找任务通用 */
  async function runScan(kind) {
    const minEl = UI.$(`#${kind}-min`);
    const min = Math.max(1, Number(minEl.value) || 1);
    const picked = S()[`${kind}Roots`] || [];
    if (!picked.length) { UI.toast('请至少选一个磁盘', 'warn'); return; }

    const runBtn = UI.$(`#${kind}-run`);
    const cancelBtn = UI.$(`#${kind}-cancel`);
    const log = UI.$(`#${kind}-log`);
    const status = UI.$(`#${kind}-status`);

    const api = kind === 'large' ? 'start_large_files' : 'start_duplicates';
    const r = await Bridge.call(api, picked, min, kind === 'large' ? 300 : 200);
    if (!r || r.ok === false) {
      UI.toast((r && r.error) || '启动失败', 'err');
      return;
    }

    runBtn.disabled = true;
    cancelBtn.classList.remove('hide');
    log.classList.remove('hide');
    log.textContent = '';
    status.textContent = '扫描中…';
    UI.$(`#${kind}-body`).innerHTML = '';

    if (tracker) tracker.stop();
    tracker = Bridge.track(r.job_id, async (s) => {
      (s.logs || []).forEach((line) => UI.logAppend(`#${kind}-log`, line));
      if (s.state === 'running') return;

      tracker = null;
      runBtn.disabled = false;
      cancelBtn.classList.add('hide');
      const res = s.result || {};
      if (s.state !== 'done') {
        status.textContent = s.state === 'cancelled' ? '已取消' : '出错';
        if (s.state === 'error') UI.toast(s.error || '扫描出错', 'err');
        return;
      }
      if (kind === 'large') renderLarge(res); else renderDup(res);
    });

    cancelBtn.onclick = () => Bridge.call('cancel', r.job_id);
  }

  function renderLarge(res) {
    const n = res.count || 0;
    UI.$('#large-status').textContent =
      `找到 ${n} 个文件，合计 ${fmtSize(res.total)}`
      + (res.truncated ? `（只显示最大的 ${(res.files || []).length} 个）` : '');
    const files = res.files || [];
    UI.$('#large-body').innerHTML = files.length
      ? files.map((f) => `
          <div class="file-row">
            <span class="file-size">${fmtSize(f.size)}</span>
            <span class="file-path" title="${UI.esc(f.path)}">${UI.esc(f.path)}</span>
          </div>`).join('')
      : '<div class="stat-foot">没有超过阈值的文件。</div>';
  }

  function renderDup(res) {
    UI.$('#dup-status').textContent =
      `${res.group_count} 组重复，可省 ${fmtSize(res.wasted)}`
      + (res.truncated ? `（只显示最占空间的 ${(res.groups || []).length} 组）` : '');
    const groups = res.groups || [];
    UI.$('#dup-body').innerHTML = groups.length
      ? groups.map((g) => `
          <div class="dup-group">
            <div class="dup-head">
              <b>${fmtSize(g.size)}</b> × ${g.count} 份
              <span class="muted">可省 ${fmtSize(g.wasted)}</span>
            </div>
            ${g.paths.map((p) => `
              <div class="dup-path" title="${UI.esc(p)}">${UI.esc(p)}</div>`).join('')}
          </div>`).join('')
      : '<div class="stat-foot">没有找到重复文件。'
        + '（阈值以下的文件按设计不参与比对）</div>';
  }

  /* ------------------------------------------------------------ 绑定 */
  function bind() {
    UI.$('#tools-tabs').addEventListener('click', (e) => {
      const b = e.target.closest('.tab');
      if (b) showTab(b.dataset.tool);
    });
    UI.$('#startup-refresh').addEventListener('click', loadStartup);
    UI.$('#startup-list').addEventListener('click', (e) => {
      const b = e.target.closest('[data-toggle]');
      if (b) toggleStartup(b);
    });
    UI.$('#hw-refresh').addEventListener('click', loadHardware);
    UI.$('#large-run').addEventListener('click', () => runScan('large'));
    UI.$('#dup-run').addEventListener('click', () => runScan('dup'));
  }

  async function enter() {
    if (!roots.length) await loadRoots();
    showTab(tab);
  }

  function init() { bind(); }

  return { init, enter };
})();
