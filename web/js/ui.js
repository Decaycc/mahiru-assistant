/* ===========================================================================
   通用工具：格式化、DOM 构造、提示条。
   刻意不引任何框架 —— 页面就 5 个，原生足够，还省掉打包体积。
   =========================================================================== */

const UI = (() => {

  /* ------------------------------------------------------------ 格式化 */
  function bytes(n) {
    if (!n || n < 0) return '0 B';
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(i >= 3 ? 2 : (i === 0 ? 0 : 1))} ${u[i]}`;
  }

  const pct = (v) => `${(v || 0).toFixed(0)}%`;

  /** 占用率 -> 进度条配色类 */
  function barClass(p) {
    if (p >= 90) return 'bar danger';
    if (p >= 75) return 'bar warn';
    return 'bar';
  }

  /** 2026-10-06 15:28 -> 15:28 */
  function hhmm(s) {
    return (s || '').slice(-5) || '—';
  }

  /* ------------------------------------------------------------ DOM */
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  const $  = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  /** 用 HTML 字符串造元素（内部调用方负责已转义） */
  function h(html) {
    const t = document.createElement('template');
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  }

  /* ------------------------------------------------------------ 提示条 */
  let toastTimer = null;
  function toast(msg, kind) {
    let el = $('#toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'toast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.className = 'toast show' + (kind ? ` toast-${kind}` : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.className = 'toast'; }, 2800);
  }

  /* ------------------------------------------------------------ 日志面板 */
  function logAppend(sel, text, isErr) {
    const box = $(sel);
    if (!box) return;
    const d = document.createElement('div');
    if (isErr) d.className = 'ln-err';
    d.textContent = text;
    box.appendChild(d);
    box.scrollTop = box.scrollHeight;
  }
  function logClear(sel) { const b = $(sel); if (b) b.innerHTML = ''; }

  /* ------------------------------------------------------------ 其它 */
  /** 把耗时秒数变成人话 */
  function duration(sec) {
    if (sec < 1) return `${(sec * 1000).toFixed(0)} ms`;
    if (sec < 60) return `${sec.toFixed(sec < 10 ? 1 : 0)} 秒`;
    const m = Math.floor(sec / 60);
    return `${m} 分 ${(sec % 60).toFixed(0)} 秒`;
  }

  /** 让长路径中间省略，保留头尾（比直接截断可读） */
  function shortPath(p, max = 62) {
    p = String(p || '');
    if (p.length <= max) return p;
    const keep = Math.floor((max - 3) / 2);
    return p.slice(0, keep) + '...' + p.slice(-keep);
  }

  return { bytes, pct, barClass, hhmm, esc, $, $$, h, toast,
           logAppend, logClear, duration, shortPath };
})();
