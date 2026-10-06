/* ===========================================================================
   路由：页面切换 + 过渡动效。

   动效规范（与 design/mockup.html 一致）：
     · 页面整体       220ms
     · 行/卡片交错    260ms，最多错开 5 项（再多就一起出现，否则尾项等太久）
     · 悬浮/按压      140ms
   全部 <= 260ms；prefers-reduced-motion 由 CSS 令牌统一归零。
   =========================================================================== */

const Router = (() => {
  const PAGES = {
    overview: { title: '概览',     bar: false },
    memory:   { title: '内存优化', bar: true,  label: '一键加速' },
    junk:     { title: '垃圾清理', bar: true,  label: null },
    tools:    { title: '小功能',   bar: false },
    settings: { title: '设置',     bar: false },
  };

  let current = null;
  let onEnter = {};       // page -> async fn

  function register(page, fn) { onEnter[page] = fn; }

  /** 交错浮现：给容器的直接子元素依次加延迟 */
  function stagger(container) {
    if (!container) return;
    const kids = Array.from(container.children);
    kids.forEach((el, i) => {
      el.style.animation = 'none';
      void el.offsetWidth;                       // 强制回流，重启动画
      el.style.animation = '';
      el.style.animationDelay = `${Math.min(i, 5) * 35}ms`;
    });
  }

  async function go(page, opts = {}) {
    if (!PAGES[page]) page = 'overview';
    if (current === page && !opts.force) return;
    const prev = current;
    current = page;
    Store.state.ui.page = page;

    // 侧栏高亮
    UI.$$('.nav-item[data-page]').forEach((b) => {
      b.classList.toggle('active', b.dataset.page === page);
    });

    // 顶栏
    UI.$('#crumb').textContent = PAGES[page].title;

    // 底栏：按 data-on 只显示与当前页相关的按钮与计数
    const bar = UI.$('#actionbar');
    const meta = PAGES[page];
    bar.classList.toggle('hidden', !meta.bar);
    UI.$$('#actionbar [data-on]').forEach((el) => {
      const scoped = (el.dataset.on || '').split(/\s+/);
      el.classList.toggle('hidden', !scoped.includes(page));
    });
    const primary = UI.$('#action-primary');
    if (meta.label) {
      primary.textContent = meta.label;
      primary.classList.remove('hidden');
    } else {
      primary.classList.add('hidden');
    }

    // 页面容器
    const from = prev && UI.$(`#page-${prev}`);
    const to = UI.$(`#page-${page}`);
    if (from && from !== to) {
      from.classList.remove('active');
      from.setAttribute('aria-hidden', 'true');
    }
    if (to) {
      to.classList.add('active');
      to.removeAttribute('aria-hidden');
      UI.$('#viewport').scrollTop = 0;
      stagger(UI.$('.stagger', to) || to);
    }

    if (onEnter[page]) {
      try {
        await onEnter[page](opts);
      } catch (e) {
        // 异常不能只弹个 toast 就算了：那样从外部只能看到「页面是空的」，
        // 完全查不出原因。同时记进 __errs，让自动化冒烟能抓到。
        try {
          (window.__errs = window.__errs || []).push(
            `Router[${page}]: ${e && (e.stack || e.message || e)}`);
        } catch (_) { /* 忽略 */ }
        UI.toast(`加载「${PAGES[page].title}」失败：${e.message}`, 'err');
      }
    }
    Store.emit('page', page);
  }

  function init() {
    UI.$$('.nav-item[data-page]').forEach((btn) => {
      btn.addEventListener('click', () => go(btn.dataset.page));
    });
    go('overview');
  }

  return { PAGES, register, go, init, stagger, get current() { return current; } };
})();
