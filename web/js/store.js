/* ===========================================================================
   全局状态。

   三层各管各的：
     Store.mem    内存页（进程列表、选择、优先级）
     Store.junk   垃圾页（规则、扫描结果、勾选）
     Store.ui     界面（主题、当前页）
   只有 ui 那层的主题会写 localStorage；其余都是会话内的。
   =========================================================================== */

const Store = (() => {
  const listeners = {};

  const state = {
    ui: {
      theme: 'light',
      page: 'overview',
      admin: false,
      ready: false,
    },
    overview: null,
    mem: {
      loaded: false,
      processes: [],
      total: 0,
      closable: 0,
      trimmable: 0,
      reclaimable: 0,
      selected: new Set(),
      onlyClosable: false,
    },
    junk: {
      loaded: false,
      rules: [],
      byLevel: {},
      selected: new Set(),
      scanned: false,
      // 必须初始化成对象而不是 null：渲染时会按 key 取用（results[key]），
      // 用 null 会直接抛 TypeError 中断整个列表渲染。
      results: {},
      lastTotal: 0,
    },
    tools: {
      startup: null,
      hardware: null,
      // 扫描根的多选状态；两处独立，因为「大文件」和「重复文件」
      // 常用的范围不一样（前者常只看 D 盘，后者常全盘）
      largeRoots: null,
      dupRoots: null,
    },
  };

  function on(evt, fn) {
    (listeners[evt] = listeners[evt] || []).push(fn);
    return () => {
      listeners[evt] = (listeners[evt] || []).filter((f) => f !== fn);
    };
  }

  function emit(evt, payload) {
    (listeners[evt] || []).forEach((fn) => {
      try { fn(payload); } catch (e) { console.error(evt, e); }
    });
  }

  /* ------------------------------------------------------------ 主题 */
  function initTheme() {
    let t = 'light';
    try {
      // 默认浅色。只有在用户**明确选过**深色时才用深色 ——
      // 之前是跟随系统，但深色下部分文字对比度不够，看着累，
      // 所以改成默认浅色，深色仍然可以手动切。
      t = localStorage.getItem('gb-theme') || 'light';
    } catch (e) { /* 无存储时忽略 */ }
    setTheme(t, false);
    return t;
  }

  function setTheme(t, persist = true) {
    state.ui.theme = t;
    document.documentElement.setAttribute('data-theme', t);
    if (persist) {
      try { localStorage.setItem('gb-theme', t); } catch (e) { /* 忽略 */ }
      // 同时落到 Python 侧配置：webview 存储被清掉时还能恢复
      Bridge.call('save_config', { theme: t });
    }
    emit('theme', t);
  }

  const toggleTheme = () =>
    setTheme(state.ui.theme === 'dark' ? 'light' : 'dark');

  return { state, on, emit, initTheme, setTheme, toggleTheme };
})();
