/* 垃圾清理页：规则清单 + 真实扫描 + 真实清理。
 *
 * 关键设计：**扫描与清理是分开的两步**。
 *   · 扫描只统计，不删任何东西 —— 你可以先看清楚能释放多少再决定
 *   · 清理只处理你勾选的规则
 * 所有安全判断都在后端（保护清单、隐私数据、个人目录、reparse 跳过、
 * 占用文件不强删），前端不做也不该做这类判断。
 */

Pages.junk = (() => {
  const S = () => Store.state.junk;
  let tracker = null;
  let searchTerm = '';

  const LEVEL = {
    safe:    { text: '安全', cls: 'badge-ok' },
    caution: { text: '谨慎', cls: 'badge-warn' },
    risky:   { text: '风险', cls: 'badge-danger' },
  };

  /* ------------------------------------------------------------ 列表 */
  function rowHtml(r) {
    const lv = LEVEL[r.level] || LEVEL.safe;
    const checked = S().selected.has(r.key) ? 'checked' : '';
    const hit = S().results[r.key];
    const pat = r.patterns.length
      ? `<span class="pat" title="${UI.esc(r.patterns.join('  '))}">按模式</span>` : '';

    // 未扫描时显示目标数；扫描后显示可释放空间
    let right;
    if (hit) {
      right = hit.size > 0
        ? `<span class="jsize">${UI.bytes(hit.size)}</span>
           <span class="jfiles">${hit.files} 文件</span>`
        : '<span class="jfiles">未发现</span>';
    } else {
      right = `<span class="jfiles">${r.targets} 个目标</span>`;
    }

    return `
      <label class="jrow lv-${r.level}" data-key="${UI.esc(r.key)}">
        <span class="jcell-tick"><input type="checkbox" class="jtick"
              data-key="${UI.esc(r.key)}" ${checked}></span>
        <span class="jcell-name">
          <span class="jname">${UI.esc(r.name)}</span>
          <span class="jmeta">${UI.esc(r.category)}${pat}</span>
        </span>
        <span class="jcell-lv"><span class="badge ${lv.cls}">${lv.text}</span></span>
        <span class="jcell-right">${right}
          <button class="linkbtn" data-detail="${UI.esc(r.key)}"
                  title="查看具体路径">详情</button></span>
      </label>`;
  }

  function render() {
    const j = S();
    const list = searchTerm
      ? j.rules.filter((r) => (r.name + r.category).toLowerCase()
          .includes(searchTerm))
      : j.rules;

    UI.$('#junk-list').innerHTML = list.length
      ? list.map(rowHtml).join('')
      : '<div class="empty">没有匹配的规则</div>';

    const lv = j.byLevel || {};
    UI.$('#junk-stat').textContent =
      `${j.rules.length} 条 · 安全 ${lv.safe || 0} · 谨慎 ${lv.caution || 0}`
      + ` · 风险 ${lv.risky || 0}`;

    const n = j.selected.size;
    UI.$('#junk-sel').textContent = j.scanned
      ? `已选 ${n} 项 · 预计释放 ${UI.bytes(selectedSize())}`
      : `已选 ${n} 项`;
    UI.$('#junk-apply').disabled = n === 0 || busy();
    // 清理按钮只在扫描之后出现 —— 没扫过就不知道会释放多少
    UI.$('#junk-clean').classList.toggle('hide', !j.scanned);
    UI.$('#junk-clean').disabled = n === 0 || busy();
  }

  function selectedSize() {
    const j = S();
    let sum = 0;
    j.selected.forEach((k) => { sum += (j.results[k] || {}).size || 0; });
    return sum;
  }

  /* ------------------------------------------------------------ 扫描结果 */
  function showScanResult(result) {
    const j = S();
    const rows = (result.rules || []).filter((r) => r.size > 0)
      .sort((a, b) => b.size - a.size);

    // 分开统计安全项与谨慎项，让"默认可清"和"需要你确认"一目了然
    let safeSum = 0, cautionSum = 0;
    rows.forEach((r) => {
      if (r.level === 'safe') safeSum += r.size; else cautionSum += r.size;
    });
    let selSum = 0;
    j.selected.forEach((k) => { selSum += (j.results[k] || {}).size || 0; });

    const card = UI.$('#junk-result');
    card.classList.remove('hide');
    card.innerHTML = `
      <div class="row-between" style="margin-bottom:12px">
        <h2 class="section-h">扫描结果</h2>
        <span class="muted" style="font-size:var(--fs-small)">
          共 ${rows.length} 条规则命中，合计 ${UI.bytes(result.total)}</span>
      </div>
      <div class="result-grid">
        <div class="result-item"><div class="k">安全项</div>
          <div class="v good">${UI.bytes(safeSum)}</div></div>
        <div class="result-item"><div class="k">谨慎项</div>
          <div class="v">${UI.bytes(cautionSum)}</div></div>
        <div class="result-item"><div class="k">当前勾选</div>
          <div class="v">${UI.bytes(selSum)}</div></div>
        <div class="result-item"><div class="k">文件数</div>
          <div class="v">${result.files || 0} <small>个</small></div></div>
      </div>
      ${rows.length ? `
      <div class="stat-foot" style="margin-top:12px">占用最大的几条：</div>
      <div class="scan-top">
        ${rows.slice(0, 6).map((r) => `
          <div class="scan-row">
            <span>${UI.esc(r.name)}</span>
            <b>${UI.bytes(r.size)}</b>
            <i>${r.files} 文件</i>
          </div>`).join('')}
      </div>` : ''}`;
  }

  /* ------------------------------------------------------------ 清理结果 */
  function showCleanResult(result) {
    const card = UI.$('#junk-result');
    card.classList.remove('hide');
    card.innerHTML = `
      <div class="row-between" style="margin-bottom:12px">
        <h2 class="section-h">清理结果</h2>
        <span class="muted" style="font-size:var(--fs-small)">
          操作已完成</span>
      </div>
      <div class="result-grid">
        <div class="result-item"><div class="k">删除项</div>
          <div class="v">${result.deleted || 0} <small>项</small></div></div>
        <div class="result-item"><div class="k">释放空间</div>
          <div class="v good">${UI.bytes(result.freed || 0)}</div></div>
        <div class="result-item"><div class="k">跳过</div>
          <div class="v">${result.failed_count || 0} <small>项</small></div></div>
      </div>
      ${(result.failed || []).length ? `
      <div class="stat-foot" style="margin-top:12px">
        被跳过的（占用中 / 受保护 / 是链接）：</div>
      <div class="fail-list">
        ${result.failed.slice(0, 8).map(([p, why]) => `
          <div class="fail-row">
            <span title="${UI.esc(p)}">${UI.esc(UI.shortPath(p, 58))}</span>
            <i>${UI.esc(why)}</i>
          </div>`).join('')}
        ${result.failed_count > 8
          ? `<div class="fail-row"><span>…另有 ${result.failed_count - 8} 项</span></div>` : ''}
      </div>` : ''}`;
  }

  /* ------------------------------------------------------------ 详情 */
  async function showDetail(key) {
    const d = await Bridge.call('junk_detail', key);
    const card = UI.$('#junk-detail-card');
    card.classList.remove('hide');
    if (!d || d.ok === false) {
      UI.$('#junk-detail-title').textContent = '规则详情';
      UI.$('#junk-detail-body').innerHTML =
        `<div class="empty err">${UI.esc((d && d.error) || '读取失败')}</div>`;
      return;
    }
    UI.$('#junk-detail-title').textContent = d.name;
    const exists = new Set(d.exists || []);
    UI.$('#junk-detail-body').innerHTML = `
      <div class="stat-foot" style="margin:0 0 12px">${UI.esc(d.desc || '')}</div>
      <dl class="kv" style="margin-bottom:12px">
        <dt>安全等级</dt><dd>${(LEVEL[d.level] || {}).text || d.level}</dd>
        <dt>清理方式</dt><dd>${d.kind === 'contents' ? '清空目录内容（保留目录本身）'
          : d.kind === 'files' ? '只删除匹配的文件（保留目录内容）' : d.kind}</dd>
        ${d.patterns.length
          ? `<dt>文件模式</dt><dd>${UI.esc(d.patterns.join('  '))}</dd>` : ''}
        <dt>目标路径</dt><dd>${(d.exists || []).length} / ${d.paths.length} 个存在</dd>
      </dl>
      <div class="path-list">
        ${d.paths.map((p) => `
          <div class="path-row${exists.has(p) ? '' : ' gone'}">
            <span title="${UI.esc(p)}">${UI.esc(UI.shortPath(p, 76))}</span>
          </div>`).join('')}
      </div>`;
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  /* ------------------------------------------------------------ 任务 */
  const busy = () => !!tracker;

  function setBusy(on, title) {
    UI.$('#junk-log-card').classList.toggle('hide', !on);
    UI.$('#junk-apply').disabled = on || S().selected.size === 0;
    UI.$('#junk-clean').disabled = on || S().selected.size === 0;
    if (on) {
      UI.$('#junk-log-title').textContent = title || '执行中';
      UI.$('#junk-log-state').className = 'badge badge-warn';
      UI.$('#junk-log-state').textContent = '运行中';
      UI.$('#junk-log-progress').textContent = '—';
      UI.logClear('#junk-log');
      UI.$('#junk-log-card').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  async function runJob(starter, title, onDone) {
    if (busy()) { UI.toast('已有任务在运行', 'warn'); return; }
    setBusy(true, title);

    const r = await starter();
    if (!r || r.ok === false) {
      setBusy(false);
      UI.toast((r && r.error) || '启动失败', 'err');
      return;
    }

    tracker = Bridge.track(r.job_id, async (s) => {
      (s.logs || []).forEach((line) => UI.logAppend('#junk-log', line));
      if (s.state === 'running') {
        if (s.progress) UI.$('#junk-log-progress').textContent = s.progress;
        return;
      }
      tracker = null;
      setBusy(false);
      UI.$('#junk-log-progress').textContent = `耗时 ${UI.duration(s.elapsed)}`;
      const badge = UI.$('#junk-log-state');
      if (s.state === 'done') {
        badge.className = 'badge badge-ok';
        badge.textContent = '已完成';
        if (onDone) onDone(s.result || {});
      } else if (s.state === 'cancelled') {
        badge.className = 'badge badge-mute';
        badge.textContent = '已取消';
      } else {
        badge.className = 'badge badge-danger';
        badge.textContent = '出错';
        UI.logAppend('#junk-log', s.error || '未知错误', true);
      }
      render();
    });
  }

  function scan() {
    const keys = Array.from(S().selected);
    runJob(() => Bridge.call('start_scan', keys), '扫描中…', (res) => {
      const j = S();
      j.results = {};
      (res.rules || []).forEach((r) => { j.results[r.key] = r; });
      j.scanned = true;
      j.lastTotal = res.total;
      showScanResult(res);
      UI.toast(`扫描完成：可释放 ${UI.bytes(res.total)}`);
    });
  }

  function clean() {
    const keys = Array.from(S().selected);
    const size = selectedSize();
    // 谨慎项要二次确认 —— 它们能重建但有可见副作用
    const caution = S().rules.filter((r) => keys.includes(r.key)
      && r.level !== 'safe');
    let msg = `将清理 ${keys.length} 条规则，预计释放 ${UI.bytes(size)}。`;
    if (caution.length) {
      msg += `\n\n其中 ${caution.length} 条是「谨慎」级，清理后会有可见副作用`
        + `（例如离线应用需重新注册、受保护视频需重新下载组件）。`;
    }
    msg += '\n\n继续吗？';
    if (!window.confirm(msg)) return;

    runJob(() => Bridge.call('start_clean', keys), '清理中…', (res) => {
      showCleanResult(res);
      // 清理后旧的扫描数据已失效，标记为未扫描
      S().scanned = false;
      S().results = {};
      UI.toast(`清理完成：释放 ${UI.bytes(res.freed)}，跳过 ${res.failed_count || 0} 项`);
    });
  }

  /* ------------------------------------------------------------ 系统级清理 */
  async function refreshRecycleBin() {
    const d = await Bridge.call('get_overview');
    const rb = (d && d.recycle_bin) || {};
    UI.$('#junk-rb-info').textContent = rb.accessible
      ? `${rb.items || 0} 项 · ${UI.bytes(rb.size || 0)}`
      : '回收站不可访问';
    UI.$('#junk-rb-empty').disabled = !rb.items || busy();
  }

  function emptyRecycleBin() {
    if (!window.confirm('清空回收站？里面的文件将无法恢复。')) return;
    runJob(() => Bridge.call('empty_recycle_bin'), '清空回收站', (res) => {
      UI.toast(res.emptied
        ? `已清空回收站，释放 ${UI.bytes(res.freed || 0)}`
        : '回收站本来就是空的');
      refreshRecycleBin();
    });
  }

  function runDism() {
    const msg = 'DISM 组件清理会移除 WinSxS 中被取代的旧组件。\n\n'
      + '· 耗时可能十几分钟，期间可以取消\n'
      + '· 清理后无法卸载已安装的更新\n'
      + '· 这是微软官方工具，不是本程序自己删文件\n\n继续吗？';
    if (!window.confirm(msg)) return;
    runJob(() => Bridge.call('start_dism', false), 'DISM 组件清理', () => {
      UI.toast('DISM 完成，详见下方日志');
    });
  }

  /* ------------------------------------------------------------ 事件 */
  function bind() {
    UI.$('#junk-list').addEventListener('change', (e) => {
      const cb = e.target.closest('.jtick');
      if (!cb) return;
      const key = cb.dataset.key;
      if (cb.checked) S().selected.add(key); else S().selected.delete(key);
      render();
    });

    // 点「详情」不要触发行的勾选
    UI.$('#junk-list').addEventListener('click', (e) => {
      const btn = e.target.closest('[data-detail]');
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      showDetail(btn.dataset.detail);
    });

    UI.$$('[data-pick]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const mode = btn.dataset.pick;
        S().selected.clear();
        S().rules.forEach((r) => {
          if (mode === 'safe' && r.level === 'safe') S().selected.add(r.key);
          if (mode === 'default' && r.default) S().selected.add(r.key);
        });
        render();
      });
    });

    UI.$('#junk-search').addEventListener('input', (e) => {
      searchTerm = e.target.value.trim().toLowerCase();
      render();
    });

    UI.$('#junk-apply').addEventListener('click', scan);
    UI.$('#junk-clean').addEventListener('click', clean);
    UI.$('#junk-detail-close').addEventListener('click', () =>
      UI.$('#junk-detail-card').classList.add('hide'));

    UI.$('#junk-log-cancel').addEventListener('click', async () => {
      if (!tracker) return;
      const r = await Bridge.call('running_jobs');
      (r.jobs || []).forEach((id) => Bridge.call('cancel', id));
    });

    UI.$('#junk-rb-empty').addEventListener('click', emptyRecycleBin);
    UI.$('#junk-dism').addEventListener('click', runDism);
  }

  async function load(force) {
    const j = S();
    if (j.loaded && !force) return;
    UI.$('#junk-list').innerHTML = '<div class="empty">正在解析规则…</div>';
    const d = await Bridge.call('list_rules');
    if (!d || d.ok === false) {
      UI.$('#junk-list').innerHTML =
        `<div class="empty err">${UI.esc((d && d.error) || '读取失败')}</div>`;
      return;
    }
    j.rules = d.rules || [];
    j.byLevel = d.by_level || {};
    j.loaded = true;
    if (!j.selected.size) {
      j.rules.forEach((r) => { if (r.default) j.selected.add(r.key); });
    }
    render();
  }

  async function enter() {
    await load(false);
    await refreshRecycleBin();
  }

  function init() { bind(); }

  return { init, enter, load, scan, clean,
           get running() { return busy(); } };
})();
