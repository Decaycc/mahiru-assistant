/* ===========================================================================
   pywebview 桥接层。

   两件事必须处理对，否则界面会随机白屏：
   1. window.pywebview.api 不是页面一加载就有 —— 要等 pywebviewready 事件。
      而且事件有可能早于 api 挂载，所以事件之后还要再探一次。
      **光探到 api 对象还不够**：冷启动（WebView2 缓存为空）时对象会先出现、
      消息通道后接好，此时第一次调用直接被丢掉 —— 既不 resolve 也不 reject。
      所以 waitReady 必须真跑一次 ping()，往返通了才算就绪。
   2. 后端所有方法都可能返回 {ok:false, error}，统一在这里抛成异常或者
      返回给调用方判断，不要让静默失败扩散到 UI。
   =========================================================================== */

const Bridge = (() => {
  let readyPromise = null;

  /* 单次调用的兜底超时。后端所有方法都在 12 秒内返回过，这里放宽到 20 秒。
     存在的意义：RPC 被丢掉时既不 resolve 也不 reject，整个 boot() 会挂在
     第一个 await 上 —— 界面停在占位符、控制台一片安静、没有任何报错。
     宁可见到一条明确的错误，也不要一个永远不动的界面。 */
  const CALL_TIMEOUT_MS = 20000;

  function withTimeout(promise, method) {
    return new Promise((resolve) => {
      let done = false;
      const timer = setTimeout(() => {
        if (done) return;
        done = true;
        resolve({ ok: false, error: `调用 ${method}() 超时（${CALL_TIMEOUT_MS / 1000} 秒没有响应）` });
      }, CALL_TIMEOUT_MS);
      Promise.resolve(promise).then(
        (v) => { if (!done) { done = true; clearTimeout(timer); resolve(v); } },
        (e) => { if (!done) { done = true; clearTimeout(timer); resolve({ ok: false, error: String(e && e.message ? e.message : e) }); } },
      );
    });
  }

  /* 就绪判定必须是一次**真实往返**，不能只看 window.pywebview.api 在不在：
     冷启动时这个对象可能先于消息通道出现，此时第一次调用会被丢掉。
     所以拿到对象之后再 ping 一次，ping 通了才算真的能用。 */
  function waitReady(timeoutMs = 30000) {
    if (readyPromise) return readyPromise;
    readyPromise = new Promise((resolve, reject) => {
      const t0 = Date.now();
      const give = (why) => reject(new Error(why));
      const ping = () => {
        if (Date.now() - t0 > timeoutMs) {
          return give('后端未就绪（pywebview api 超时）');
        }
        const api = window.pywebview && window.pywebview.api;
        if (!api) return setTimeout(ping, 40);
        // api 对象是分两步挂满的：先出现、再补上方法。此刻还没有 ping
        // 只说明「还没轮到它」，不是「后端不支持」—— 早先这里直接判死，
        // 而 readyPromise 是记忆化的，于是整个会话再也起不来。
        if (typeof api.ping !== 'function') return setTimeout(ping, 40);
        let settled = false;
        // ping 自己也要有短超时，否则通道半通时这里会卡死
        const timer = setTimeout(() => {
          if (settled) return;
          settled = true;
          setTimeout(ping, 60);          // 通道还没接好，再试
        }, 400);
        api.ping().then(
          () => { if (!settled) { settled = true; clearTimeout(timer); resolve(); } },
          () => { if (!settled) { settled = true; clearTimeout(timer); setTimeout(ping, 60); } },
        );
      };
      window.addEventListener('pywebviewready', () => setTimeout(ping, 0));
      ping();
    });
    return readyPromise;
  }

  /** 调用后端方法。后端抛出的异常已被转成 {ok:false,error}，这里原样返回。 */
  async function call(method, ...args) {
    try {
      await waitReady();
    } catch (e) {
      return { ok: false, error: String(e && e.message ? e.message : e) };
    }
    const fn = window.pywebview.api[method];
    if (typeof fn !== 'function') {
      return { ok: false, error: `后端没有实现 ${method}()` };
    }
    try {
      const res = await withTimeout(fn(...args), method);
      return res === undefined ? { ok: true } : res;
    } catch (e) {
      return { ok: false, error: String(e && e.message ? e.message : e) };
    }
  }

  /** 调用并断言成功，失败就抛 —— 适合「必须成功」的场景。 */
  async function must(method, ...args) {
    const r = await call(method, ...args);
    if (!r || r.ok === false) throw new Error((r && r.error) || `${method} 失败`);
    return r;
  }

  const isReady = () => !!(window.pywebview && window.pywebview.api);

  /* ---------------------------------------------------------------- 轮询 */
  /**
   * 跟踪一个后台任务，直到它结束。
   * onUpdate 每次收到新的日志增量；返回 {stop()} 可随时停止跟踪。
   */
  function track(jobId, onUpdate, intervalMs = 200) {
    let stopped = false;
    let since = 0;
    const t0 = Date.now();

    async function tick() {
      if (stopped) return;
      const r = await call('poll', jobId, since);
      if (stopped) return;
      if (!r || r.ok === false) {
        onUpdate({ state: 'error', error: (r && r.error) || '轮询失败' });
        return;
      }
      since = r.log_total;
      onUpdate(r);
      if (r.state === 'running') {
        setTimeout(tick, intervalMs);
      }
    }
    tick();

    return {
      stop() { stopped = true; },
      get elapsed() { return (Date.now() - t0) / 1000; },
    };
  }

  return { waitReady, call, must, isReady, track };
})();
