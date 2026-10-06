/* ===========================================================================
   pywebview 桥接层。

   两件事必须处理对，否则界面会随机白屏：
   1. window.pywebview.api 不是页面一加载就有 —— 要等 pywebviewready 事件。
      而且事件有可能早于 api 挂载，所以事件之后还要再探一次。
   2. 后端所有方法都可能返回 {ok:false, error}，统一在这里抛成异常或者
      返回给调用方判断，不要让静默失败扩散到 UI。
   =========================================================================== */

const Bridge = (() => {
  let readyPromise = null;

  function waitReady(timeoutMs = 12000) {
    if (readyPromise) return readyPromise;
    readyPromise = new Promise((resolve, reject) => {
      const t0 = Date.now();
      const probe = () => {
        if (window.pywebview && window.pywebview.api) return resolve();
        if (Date.now() - t0 > timeoutMs) {
          return reject(new Error('后端未就绪（pywebview api 超时）'));
        }
        setTimeout(probe, 40);
      };
      window.addEventListener('pywebviewready', () => setTimeout(probe, 0));
      probe();
    });
    return readyPromise;
  }

  /** 调用后端方法。后端抛出的异常已被转成 {ok:false,error}，这里原样返回。 */
  async function call(method, ...args) {
    await waitReady();
    const fn = window.pywebview.api[method];
    if (typeof fn !== 'function') {
      return { ok: false, error: `后端没有实现 ${method}()` };
    }
    try {
      const res = await fn(...args);
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
