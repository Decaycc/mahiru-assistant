/* ===========================================================================
   全局状态。

   三层各管各的：
     Store.mem    内存页（进程列表、选择、优先级）
     Store.junk   垃圾页（规则、扫描结果、勾选）
     Store.ui     界面（当前页、管理员状态）
   会话内状态，不写 localStorage（Zapier 重皮肤已移除深色模式）。
   =========================================================================== */

const Store = (() => {
  const listeners = {};

  const state = {
    ui: {
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
    gaming: {
      loaded: false,
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

  return { state, on, emit };
})();
