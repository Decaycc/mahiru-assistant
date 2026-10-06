# -*- coding: utf-8 -*-
"""程序入口：创建窗口、注册 JS 桥、异常兜底。

对应原 .bat 启动器里被删掉的那 3 组功能（定位 Python / 工具选择 / 启动），
现在都变成进程内的事：
    · 定位 Python  -> 不需要，EXE 自带解释器
    · 工具选择     -> 改成侧栏切换页面
    · 启动         -> 本文件
保留的只有 UAC 提权（见 elevation.py）。
"""
import os
import shutil
import sys
import time
import traceback

import webview

from . import elevation
from .bridge import APP_TITLE, APP_VERSION, Api
from .core import mem
from .jobs import JobManager
from .paths import config_dir, is_frozen, resource_root

# 只读资源与可写数据必须分开：
#   onefile 打包后 __file__ 在每次启动都变的临时目录里，
#   资源在那里没问题，但配置写在那里会在下次启动时消失。
WEB_INDEX = os.path.join(resource_root(), "web", "index.html")
LOG_PATH = os.path.join(config_dir(), "gameboostnext_error.log")

# 设计稿的窗口尺寸；实际会按屏幕可用区域收缩，避免小屏被裁
WANT_W, WANT_H = 1120, 780
MIN_W, MIN_H = 940, 640


def _geometry() -> tuple[int, int, int, int]:
    """算窗口尺寸与位置，返回 (宽, 高, x, y)。

    坑：pywebview 的 width/height/x/y 用的是**逻辑 (DPI 无关) 坐标**，
    而进程设了 DPI 感知后 SystemParametersInfo 返回的是**物理像素**。
    本机 125% 缩放下不换算的话，请求 780 高会被放大成 975 物理像素，
    窗口底部就压到任务栏底下了。
    """
    try:
        left, top, right, bottom = mem.work_area()
    except Exception:                                       # noqa: BLE001
        return WANT_W, WANT_H, 0, 0

    try:
        scale = (mem.system_dpi() or 96) / 96.0
    except Exception:                                       # noqa: BLE001
        scale = 1.0
    scale = scale or 1.0

    aw = (right - left) / scale
    ah = (bottom - top) / scale

    w = int(min(WANT_W, max(MIN_W, aw - 70)))
    h = int(min(WANT_H, max(MIN_H, ah - 70)))
    x = int(left / scale + max(0, (aw - w) / 2))
    y = int(top / scale + max(0, (ah - h) / 2))
    return w, h, x, y


def _install_crash_handler() -> None:
    """未捕获异常写日志。pythonw 启动时否则完全看不到报错。"""
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                        f"{APP_TITLE} v{APP_VERSION} / "
                        f"Python {sys.version.split()[0]}\n")
                f.write(text)
        except Exception:                                   # noqa: BLE001
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def _on_start(window, page: str | None = None, theme: str | None = None,
              click: str | None = None, scroll: str | None = None,
              evals: str | None = None) -> None:
    """窗口起来后的收尾：同步后端状态，必要时切页 / 换主题 / 点按钮 / 跑 JS。

    --page / --theme / --click / --scroll / --eval 都是给截图与手工验证用的
    （正常启动停在概览、跟随系统主题、不做任何操作）。
    `--eval` 是本地调试口子：需要展开折叠面板、滚动到某个元素这类操作时，
    没有它就只能靠猜选择器。它只在显式传参时才生效。

    两个坑：
      · router.js 里是 `const Router`，那创建的是**词法绑定而非 window 属性**，
        所以必须用裸标识符 Router，写 window.Router 会取到 undefined
      · 主题要传 persist=false，否则截图会把用户自己的偏好改掉
    """
    try:
        window.evaluate_js("window.__dshReady && window.__dshReady();")
        if theme in ("light", "dark"):
            window.evaluate_js(
                "setTimeout(function () {"
                f"  if (typeof Store !== 'undefined') Store.setTheme({theme!r}, false);"
                "}, 150);")
        if page:
            window.evaluate_js(
                "setTimeout(function () {"
                f"  if (typeof Router !== 'undefined') Router.go({page!r});"
                "}, 400);")
        if click:
            # 等页面与数据都就绪再点，否则可能点到还没渲染出来的按钮
            window.evaluate_js(
                "setTimeout(function () {"
                f"  var el = document.querySelector({click!r});"
                "  if (el) el.click();"
                "}, 1800);")
        if scroll:
            window.evaluate_js(
                "setTimeout(function () {"
                "  var v = document.getElementById('viewport');"
                "  if (!v) return;"
                f"  v.scrollTop = ({scroll!r} === 'bottom') ? v.scrollHeight"
                f"    : (parseInt({scroll!r}, 10) || 0);"
                "}, 2600);")
        if evals:
            window.evaluate_js(f"setTimeout(function () {{ {evals} }}, 2200);")
    except Exception:                                       # noqa: BLE001
        pass


def _arg_value(flag: str, default=None):
    """取 `--flag value` 形式的值。"""
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if len(sys.argv) > i + 1:
            return sys.argv[i + 1]
    return default


# 冒烟模式要检查的 DOM 项 —— GUI 没法靠人眼在自动化里验证，所以把关键状态
# 读回来打印。每个里程碑都可以用它做回归。
_SMOKE_CHECKS = [
    ("标题",        "document.title"),
    ("版本",        "document.getElementById('ver').textContent"),
    ("环境说明",    "document.getElementById('env-note').textContent"),
    ("启动遮罩",    "document.getElementById('boot').style.display"),
    ("内存",        "document.getElementById('ov-mem').textContent"),
    ("磁盘条数",    "document.querySelectorAll('#ov-disks > div').length"),
    ("权限",        "document.getElementById('admin-badge').textContent"),
    ("规则数",      "document.getElementById('ov-rules').textContent"),
    ("社区规则",    "document.getElementById('ov-tp').textContent"),
    ("回收站",      "document.getElementById('ov-rb').textContent"),
    ("桥接对象",    "typeof Bridge"),
    ("后端api",     "typeof (window.pywebview && window.pywebview.api)"),
    ("页面数",      "document.querySelectorAll('.page').length"),
    ("导航项数",    "document.querySelectorAll('.nav-item[data-page]').length"),
]

# 每个页面进入后要确认的东西
_PAGE_PROBES = [
    ("概览",     "overview", "#page-overview.active",       None),
    ("内存优化", "memory",   "#page-memory.active",         "#mem-list .prow"),
    ("垃圾清理", "junk",     "#page-junk.active",           "#junk-list .jrow"),
    # 小功能默认停在「启动项管理」，用它里面的条目数当加载完成的信号
    ("小功能",   "tools",    "#page-tools.active",          "#startup-list .entry"),
    ("设置",     "settings", "#page-settings.active",       "#set-env dd"),
]


def _js(window, expr, default=None):
    try:
        return window.evaluate_js(expr)
    except Exception as e:                                  # noqa: BLE001
        return f"<读取失败: {e}>" if default is None else default


def _smoke(window, seconds: float) -> None:
    """自动冒烟：分三阶段验证，然后把结果打印出来。

    阶段 1  界面加载后，同步接口的数据是否真的渲染进了 DOM
    阶段 2  点「环境自检」，验证 线程 → 轮询 → DOM 实时更新 这条异步链路
    阶段 3  逐个切换页面，验证路由 + 每页的真实列表是否渲染出来
    """
    import json
    for s in ("stdout", "stderr"):
        try:
            getattr(sys, s).reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                   # noqa: BLE001
            pass

    time.sleep(seconds)

    # 尽早装上错误收集器：界面里的异常如果没人接，就只会表现为
    # 「某个列表是空的」，从外部完全看不出原因。
    window.evaluate_js("""
      window.__errs = [];
      if (!window.__errHooked) {
        window.__errHooked = true;
        window.addEventListener('error', function (e) {
          window.__errs.push('Error: ' + e.message + ' @' +
            String(e.filename || '').split('/').pop() + ':' + e.lineno);
        });
        window.addEventListener('unhandledrejection', function (e) {
          window.__errs.push('Promise: ' + String(e.reason &&
            (e.reason.stack || e.reason.message || e.reason)));
        });
      }
    """)

    # ---------------- 阶段 1 ----------------
    out = {}
    for label, js in _SMOKE_CHECKS:
        out[label] = _js(window, js)

    # ---------------- 阶段 2 ----------------
    diag = {}
    try:
        window.evaluate_js(
            "Router.go('overview').then(() => "
            "document.getElementById('ov-to-memory'))")
        time.sleep(0.3)
        # 自检入口在设置页，直接调后端更稳
        window.evaluate_js(
            "Bridge.call('start_diag').then(r => window.__smokeJob = r.job_id)")
        time.sleep(1.0)
        diag["任务ID"] = _js(window, "window.__smokeJob || ''")
        jid = diag["任务ID"]
        if jid:
            for _ in range(24):
                st = _js(window, f"(window.__smokeSnap && window.__smokeSnap.state)")
                window.evaluate_js(
                    f"Bridge.call('poll', {json.dumps(jid)}, 0)"
                    f".then(s => window.__smokeSnap = s)")
                time.sleep(0.4)
                snap = _js(window, "window.__smokeSnap && window.__smokeSnap.state")
                if snap in ("done", "error", "cancelled"):
                    diag["最终状态"] = snap
                    diag["日志行数"] = _js(
                        window, "(window.__smokeSnap.logs || []).length")
                    diag["末行"] = (_js(
                        window,
                        "(() => { const l = (window.__smokeSnap.logs||[]);"
                        " return l.length ? l[l.length-1] : ''; })()") or "")[:80]
                    diag["结果"] = _js(
                        window, "JSON.stringify(window.__smokeSnap.result || {})")
                    break
            else:
                diag["最终状态"] = "超时"
    except Exception as e:                                  # noqa: BLE001
        diag["异常"] = f"{type(e).__name__}: {e}"

    # ---------------- 阶段 3 ----------------
    #
    # 用「轮询等到列表出现行」而不是固定 sleep：各页的加载耗时不一样
    # （垃圾页要对 50 条规则逐个展开路径，含 glob，明显慢于其他页），
    # 固定等待会随机失败，还会让人误以为是渲染坏了。
    pages = {}
    for label, page, activeSel, itemSel in _PAGE_PROBES:
        try:
            t0 = time.time()
            window.evaluate_js(f"Router.go({json.dumps(page)}, {{force:true}})")

            # 先等页面容器激活
            for _ in range(30):
                time.sleep(0.2)
                if _js(window, f"!!document.querySelector({json.dumps(activeSel)})"):
                    break

            rows = None
            if itemSel:
                # 再等列表真正出现内容
                for _ in range(40):
                    rows = _js(window,
                               f"document.querySelectorAll({json.dumps(itemSel)}).length")
                    if isinstance(rows, int) and rows > 0:
                        break
                    time.sleep(0.25)

            entry = {
                "active": _js(window,
                              f"!!document.querySelector({json.dumps(activeSel)})"),
                "crumb": _js(window, "document.getElementById('crumb').textContent"),
                "耗时": f"{time.time() - t0:.1f}s",
            }
            if itemSel:
                entry["列表条数"] = rows
            pages[label] = entry
        except Exception as e:                              # noqa: BLE001
            pages[label] = {"异常": f"{type(e).__name__}: {e}"}

    # ---------------- 阶段 4：内存动作（真实执行，但只做无损的那部分） ----------------
    #
    # 这里只跑「整理工作集」——它把闲置内存换出，进程照常运行，是**无损**的，
    # 也正是本工具的核心用途。**不会**跑关闭进程：那会真的关掉用户的应用，
    # 自动化测试里做这种事不合适。
    # 另外刻意避开浏览器：用户可能正用它和我对话，整理会造成可感知的卡顿。
    memres = {}

    def _await(expr, key, timeout=6.0):
        """触发一个 Promise 并等它的结果落到 window[key] 上。"""
        window.evaluate_js(f"Bridge.call({expr}).then(r => window.{key} = r)")
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(0.25)
            got = _js(window, f"window.{key} ? JSON.stringify(window.{key}) : ''")
            if got:
                return json.loads(got)
        return None

    try:
        caps = _await("'get_capabilities'", "__caps")
        memres["权限"] = (f"admin={caps.get('admin')} "
                          f"can_standby={caps.get('can_standby')}") if caps else "<失败>"

        # 契约检查：空列表必须被拒
        empty = _await("'start_trim', []", "__empty")
        memres["空列表应被拒"] = (empty or {}).get("ok") is False

        # 挑目标。优先选「满足整理条件」的；若全都不满足（例如刚整理过，
        # 工作集都掉到 50 MB 阈值以下），退而选一个非受保护进程 ——
        # 这样至少能验证 启动→线程→轮询→结果 这条链路，
        # 而不是依赖「恰好存在一个大进程」这种不确定条件。
        target = _js(window, """
        (() => {
          const skip = ['msedge', 'chrome', 'firefox', 'brave', 'opera', 'iexplore'];
          const ok = p => !p.protected &&
            !skip.some(s => p.name.toLowerCase().includes(s));
          const all = Store.state.mem.processes.filter(ok);
          const trimmable = all.filter(p => p.trimmable);
          const pick = trimmable.length ? trimmable[0] : all[0];
          if (!pick) return '';
          return JSON.stringify({ pid: pick.pid, name: pick.name, mem: pick.mem,
                                  trimmable: !!pick.trimmable,
                                  candidates: trimmable.length });
        })()""")
        if target:
            t = json.loads(target)
            memres["目标进程"] = (f"{t['name']} (PID {t['pid']}, "
                                  f"{t['mem'] // 1048576} MB, "
                                  f"满足整理条件={t['trimmable']})")
            memres["可整理候选数"] = t["candidates"]
            before = _await("'memory_snapshot'", "__mb")
            job = _await(f"'start_trim', [{t['pid']}]", "__trimjob")
            memres["任务"] = (job or {}).get("job_id", "<失败>")
            for _ in range(40):
                window.evaluate_js(
                    f"Bridge.call('poll', {json.dumps((job or {}).get('job_id',''))}, 0)"
                    f".then(s => window.__trimsnap = s)")
                time.sleep(0.3)
                st = _js(window, "window.__trimsnap && window.__trimsnap.state")
                if st in ("done", "error", "cancelled"):
                    memres["最终状态"] = st
                    memres["整理成功数"] = _js(
                        window, "window.__trimsnap.result && "
                                "window.__trimsnap.result.trimmed")
                    memres["工作集释放"] = _js(
                        window, "window.__trimsnap.result && "
                                "window.__trimsnap.result.ws_freed")
                    memres["系统可用变化"] = _js(
                        window, "window.__trimsnap.result && "
                                "window.__trimsnap.result.avail_delta")
                    lines = _js(window, "(window.__trimsnap.logs || []).slice(-1)")
                    memres["日志末行"] = (lines or [""])[-1][:90]
                    break
            after = _await("'memory_snapshot'", "__ma")
            if before and after:
                memres["可用内存"] = (f"{before['avail'] / 2**30:.2f} GB → "
                                      f"{after['avail'] / 2**30:.2f} GB")
        else:
            memres["目标进程"] = "<没有可整理的进程>"
    except Exception as e:                                  # noqa: BLE001
        memres["异常"] = f"{type(e).__name__}: {e}"

    # ---------------- 阶段 5：垃圾扫描（只读） ----------------
    #
    # 只做扫描，**不做清理**：清理会真的删掉用户机器上的文件，
    # 自动化测试里不合适。删除这条路径由 app/core/selftest.py 里的
    # 受控夹具（临时目录）验证 —— 那才是验证删除的正确方式。
    junkres = {}
    try:
        window.evaluate_js("Router.go('junk', {force:true})")
        time.sleep(1.0)

        contract = _await("'start_scan', []", "__jempty")
        junkres["空列表应被拒"] = (contract or {}).get("ok") is False

        # 挑两条「目标数少」的安全规则，保证扫描快
        picked = _js(window, """
        (() => {
          const rs = Store.state.junk.rules.filter(r =>
            r.level === 'safe' && r.targets > 0 && r.targets <= 40);
          const sel = rs.slice(0, 2).map(r => r.key);
          return JSON.stringify(sel);
        })()""")
        keys = json.loads(picked) if picked else []
        junkres["选中规则"] = keys
        if keys:
            job = _await(f"'start_scan', {json.dumps(keys)}", "__jscan")
            junkres["任务"] = (job or {}).get("job_id", "<失败>")
            for _ in range(50):
                window.evaluate_js(
                    f"Bridge.call('poll', {json.dumps((job or {}).get('job_id',''))}, 0)"
                    f".then(s => window.__jsnap = s)")
                time.sleep(0.4)
                st = _js(window, "window.__jsnap && window.__jsnap.state")
                if st in ("done", "error", "cancelled"):
                    junkres["最终状态"] = st
                    junkres["可释放总量"] = _js(
                        window, "window.__jsnap.result && window.__jsnap.result.total")
                    junkres["命中文件数"] = _js(
                        window, "window.__jsnap.result && window.__jsnap.result.files")
                    junkres["逐条结果"] = _js(window, """
                    (() => {
                      const rs = (window.__jsnap.result || {}).rules || [];
                      return rs.map(r => r.name + '=' + Math.round(r.size/1024) + 'KB')
                               .join(', ');
                    })()""")
                    lines = _js(window, "(window.__jsnap.logs || []).slice(-1)")
                    junkres["日志末行"] = (lines or [""])[-1][:90]
                    break

            # 顺带验证「详情」接口能返回真实路径
            det = _await(f"'junk_detail', {json.dumps(keys[0])}", "__jdet")
            if det:
                junkres["详情路径数"] = (f"{len(det.get('exists', []))} / "
                                        f"{len(det.get('paths', []))} 存在")
    except Exception as e:                                  # noqa: BLE001
        junkres["异常"] = f"{type(e).__name__}: {e}"

    # ---------------- 阶段 6：深度优化（只读校验，不执行） ----------------
    #
    # 深度优化会清空全系统工作集 / 待机列表，影响面比逐进程整理大得多，
    # 而且当前不是管理员，执行了也大多失败。所以这里**只校验接口契约**：
    # 元信息是否完整、权限标注是否正确、空选项是否被拒。
    # 真正执行交给用户在界面上按需触发 —— 那才是它该被使用的方式。
    deepres = {}
    try:
        window.evaluate_js("Router.go('memory', {force:true})")
        time.sleep(1.2)
        info = _await("'deep_ops_info'", "__deep")
        if info:
            ops = info.get("ops", [])
            deepres["项数"] = len(ops)
            deepres["权限"] = f"admin={info.get('admin')}"
            deepres["需管理员"] = sum(1 for o in ops if o.get("needs_admin"))
            deepres["免管理员"] = sum(1 for o in ops if not o.get("needs_admin"))
            deepres["有风险提示"] = sum(1 for o in ops if o.get("warning"))
            deepres["字段齐全"] = all(
                {"key", "name", "desc", "needs_admin", "warning", "default"}
                <= set(o) for o in ops)
        empty = _await(
            "'start_deep_optimize', "
            "{empty_working_sets:false,purge_standby:false,"
            "purge_low_standby:false,flush_modified:false,file_cache:false,"
            "registry:false,combine:false}", "__de")
        deepres["全不勾选应被拒"] = (empty or {}).get("ok") is False

        # 界面是否真的渲染出了 7 项
        window.evaluate_js("document.getElementById('mem-deep').open = true")
        time.sleep(0.4)
        deepres["界面渲染项数"] = _js(
            window, "document.querySelectorAll('#mem-deep-opts .opt').length")
        deepres["界面标注需管理员"] = _js(
            window, "document.querySelectorAll('#mem-deep-opts .badge-warn,"
                    " #mem-deep-opts .badge-mute').length")

        # 顺带验证「游戏优先级」面板：这是用户反馈「功能不见了」的那一项
        prio = {}
        try:
            window.evaluate_js("Router.go('memory', {force:true})")
            time.sleep(2.0)
            prio["面板存在"] = _js(window, "!!document.getElementById('mem-prio')")
            prio["有窗口程序数"] = _js(
                window, "document.querySelectorAll('#prio-target option').length")
            prio["下拉可用"] = _js(
                window, "!document.getElementById('prio-apply').disabled")
            # 真设一次自己的优先级（无损、立刻可验证）
            import os as _os
            prio["接口可用"] = _js(
                window, "(typeof Bridge !== 'undefined')")
            r = _await(f"'set_priority', {_os.getpid()}, 'normal'", "__prio")
            prio["设置自己优先级"] = (r or {}).get("ok")
            prio["归一化"] = (r or {}).get("level")
            bad = _await("'set_priority', 0, '乱写'", "__priobad")
            prio["非法级别应被拒"] = (bad or {}).get("ok") is False
        except Exception as e:                              # noqa: BLE001
            prio["异常"] = f"{type(e).__name__}: {e}"
        deepres["游戏优先级"] = prio

        # 规则库卡片：只验证渲染与信息读取，不触发真实联网更新
        rules = {}
        try:
            window.evaluate_js("Router.go('settings', {force:true})")
            time.sleep(1.6)
            rules["卡片存在"] = _js(window, "!!document.getElementById('rules-src')")
            rules["来源行数"] = _js(
                window, "document.querySelectorAll('#rules-src .src-row').length")
            rules["状态文案"] = _js(
                window, "document.getElementById('rules-status').textContent.trim()")
            rules["按钮可点"] = _js(
                window, "!document.getElementById('rules-update').disabled")
            info = _await("'rules_info'", "__rules")
            rules["命中总数"] = (info or {}).get("matched_total")
            rules["用的是更新版"] = (info or {}).get("using_override")
        except Exception as e:                              # noqa: BLE001
            rules["异常"] = f"{type(e).__name__}: {e}"
        deepres["规则库"] = rules

        # 小功能四项：只验证「能读出来 + 界面渲染」，不触发全盘扫描
        # （全盘找重复文件要几分钟，冒烟里不能干这个）
        tls = {}
        try:
            window.evaluate_js("Router.go('tools', {force:true})")
            time.sleep(2.0)
            tls["选项卡数"] = _js(
                window, "document.querySelectorAll('#tools-tabs .tab').length")
            # 这两个标记用来分辨「页面是新的」还是「WebView2 供了旧缓存」
            tls["有新标记"] = _js(
                window, "!!document.getElementById('tools-tabs')")
            tls["有旧标记"] = _js(
                window, "!!document.getElementById('tools-grid')")
            tls["页面HTML长度"] = _js(
                window, "document.getElementById('page-tools').innerHTML.length")
            tls["HTML片段"] = _js(
                window,
                "document.getElementById('page-tools').innerHTML"
                ".replace(/\\s+/g,' ').slice(0,220)")
            tls["所有id"] = _js(
                window,
                "Array.from(document.getElementById('page-tools')"
                ".querySelectorAll('[id]')).map(e=>e.id).join(',')")
            tls["location"] = _js(window, "location.href")
            tls["文档长度"] = _js(
                window, "document.documentElement.outerHTML.length")
            tls["启动项条数"] = _js(
                window, "document.querySelectorAll('#startup-list .entry').length")

            # 启动项：列表非空，且每条都有可用的 id 和启用状态
            st = _await("'startup_items'", "__startup")
            items = (st or {}).get("items") or []
            tls["启动项接口"] = len(items)
            tls["启动项字段齐全"] = all(
                i.get("id") and "enabled" in i and i.get("name") for i in items)

            # 硬件：CPU 必须读得出来，否则说明 WMI 通路断了
            hw = _await("'hardware'", "__hw")
            tls["CPU"] = bool((hw or {}).get("cpu", {}).get("Name"))

            # 磁盘：至少一块物理盘 + 一个分区
            dk = _await("'disk_health'", "__dk")
            tls["物理盘数"] = len((dk or {}).get("physical") or [])
            tls["分区数"] = len((dk or {}).get("volumes") or [])

            # 扫描根白名单：非法路径必须被剔除
            bad = _await("'start_large_files', ['Z:\\\\\\\\', '..\\\\\\\\..\\\\\\\\Windows']",
                         "__badroots")
            tls["非法根应被拒"] = (bad or {}).get("ok") is not False

            # 切到另外三个选项卡，确认面板能切且不报错
            for name in ("hardware", "large", "dup"):
                window.evaluate_js(f"Pages.tools && document.querySelector"
                                   f"('#tools-tabs [data-tool=\"{name}\"]').click()")
                time.sleep(0.8)
            tls["切换后无异常"] = _js(
                window, "(window.__errs||[]).length")
            tls["扫描根芯片数"] = _js(
                window, "document.querySelectorAll('#dup-roots .root-chip').length")
        except Exception as e:                              # noqa: BLE001
            tls["异常"] = f"{type(e).__name__}: {e}"
        deepres["小功能"] = tls
    except Exception as e:                                  # noqa: BLE001
        deepres["异常"] = f"{type(e).__name__}: {e}"

    # 回到概览
    _js(window, "Router.go('overview')")

    # ---------------- 输出 ----------------
    print("=" * 62)
    print("冒烟检查")
    print("=" * 62)
    print("[阶段 1] 同步接口 → DOM")
    for k, v in out.items():
        print(f"  {k:<10} {v!r}")
    print()
    print("[阶段 2] 后台任务 → 轮询")
    for k, v in diag.items():
        print(f"  {k:<10} {v!r}")
    print()
    print("[阶段 3] 页面路由 → 列表渲染")
    for k, v in pages.items():
        print(f"  {k:<8} {v}")
    print()
    print("[阶段 4] 内存动作（真实执行 · 仅无损操作）")
    for k, v in memres.items():
        print(f"  {k:<12} {v!r}")
    print()
    print("[阶段 5] 垃圾扫描（只读 · 不执行清理）")
    for k, v in junkres.items():
        print(f"  {k:<12} {v!r}")
    print()

    print("[阶段 6] 深度优化（只校验契约 · 不执行）")
    for k, v in deepres.items():
        print(f"  {k:<14} {v!r}")
    print()

    errs = _js(window, "JSON.stringify(window.__errs || [])")
    parsed_errs = json.loads(errs) if errs else []
    print("[界面异常]")
    if parsed_errs:
        for e in parsed_errs[:8]:
            print(f"  !! {e}")
    else:
        print("  无")
    print()

    # 标题断言用常量而不是硬编码字符串：改名时不该把回归测试弄断
    # （硬编码在这里断过一次 —— 改名后阶段 1 直接失败）
    ok1 = (out.get("标题") == APP_TITLE
           and isinstance(out.get("磁盘条数"), int) and out["磁盘条数"] > 0
           and out.get("启动遮罩") == "none"
           and out.get("页面数") == 5
           and out.get("导航项数") == 5)

    # 页面归属自检：DOM 必须和磁盘上的 web/index.html 一致。
    #
    # 为什么需要：pywebview 用内置 HTTP 服务器供页面，而 Windows 的
    # SO_REUSEADDR 允许两个进程绑同一个端口 —— 残留的旧实例会把连接
    # 接走，于是新进程加载到**旧版本的界面**，且完全不报错。
    # 实测因此白查了很久：改了界面「怎么都不生效」。
    # 这里拿磁盘上的标记和 DOM 对一下，不一致就明确失败。
    try:
        with open(WEB_INDEX, "rb") as f:
            disk_html = f.read()
        markers = [b'tools-tabs', b'tool-startup', b'startup-list',
                   b'rules-update', b'mem-prio']
        stale = []
        for m in markers:
            want = m in disk_html
            got = bool(_js(window,
                           f"!!document.getElementById("
                           f"{json.dumps(m.decode())})"))
            if want != got:
                stale.append(m.decode())
        out["页面归属"] = "一致" if not stale else f"不一致:{stale}"
        if stale:
            print(f"  [页面不是本进程提供的] 磁盘上有 {stale}，DOM 里却没有。")
            print(f"  很可能有旧实例占着页面端口 —— 关掉它再跑。")
            ok1 = False
    except Exception as e:                                  # noqa: BLE001
        out["页面归属"] = f"检查失败 {e}"
    ok2 = diag.get("最终状态") == "done"
    ok3 = all(v.get("active") for v in pages.values()) and all(
        (v.get("列表条数", 1) or 0) > 0 for v in pages.values())
    ok4 = (memres.get("空列表应被拒") is True
           and memres.get("最终状态") == "done")
    # 单独说明本轮是否真的整理了东西：候选数为 0 时链路仍然验证了，
    # 只是没有可整理的目标 —— 这属于正常情况（例如刚整理过）
    real_trim = (memres.get("整理成功数") or 0) > 0
    ok5 = (junkres.get("空列表应被拒") is True
           and junkres.get("最终状态") == "done")
    ok6 = (deepres.get("项数") == 7
           and deepres.get("字段齐全") is True
           and deepres.get("全不勾选应被拒") is True
           and deepres.get("界面渲染项数") == 7)
    print(f"  阶段 1 {'通过' if ok1 else '失败'}"
          f"    阶段 2 {'通过' if ok2 else '失败'}"
          f"    阶段 3 {'通过' if ok3 else '失败'}"
          f"    阶段 4 {'通过' if ok4 else '失败'}"
          f"    阶段 5 {'通过' if ok5 else '失败'}"
          f"    阶段 6 {'通过' if ok6 else '失败'}")
    print(f"  阶段 4 明细："
          f"{'真实整理了进程' if real_trim else '无满足条件的目标，仅验证了任务链路'}")
    total = (junkres.get("可释放总量") or 0) / 1048576
    print(f"  阶段 5 明细：扫描到 {total:.1f} MB 可清理"
          f"（仅扫描，未删除任何文件）")
    print(f"  阶段 6 明细：{deepres.get('项数')} 项元信息，其中 "
          f"{deepres.get('需管理员')} 项需管理员、"
          f"{deepres.get('有风险提示')} 项带风险提示")
    print(f"  合并结果："
          f"{'全部通过' if (ok1 and ok2 and ok3 and ok4 and ok5 and ok6) else '存在失败'}")
    print()
    print("  JSON:", json.dumps(
        {"p1": out, "p2": diag, "p3": pages, "p4": memres, "p5": junkres,
         "p6": deepres},
        ensure_ascii=False))

    # 报告同时落盘：打包后是 --windowed 的，没有控制台可看。
    # 这也让「在别人机器上跑一遍冒烟」成为可能。
    try:
        report = os.path.join(config_dir(), "smoke_report.txt")
        with open(report, "w", encoding="utf-8") as f:
            f.write(f"{APP_TITLE} v{APP_VERSION}  冻结={is_frozen()}\n")
            f.write(f"资源目录 {resource_root()}\n")
            f.write(f"配置目录 {config_dir()}\n")
            f.write("=" * 62 + "\n")
            for name, blob in (("阶段1 同步接口", out), ("阶段2 后台任务", diag),
                               ("阶段3 页面路由", pages), ("阶段4 内存动作", memres),
                               ("阶段5 垃圾扫描", junkres), ("阶段6 深度优化", deepres)):
                f.write(f"\n[{name}]\n")
                for k, v in blob.items():
                    f.write(f"  {k}: {v!r}\n")
            f.write(f"\n[界面异常]\n  {parsed_errs}\n")
            f.write(f"\n结论：{'全部通过' if (ok1 and ok2 and ok3 and ok4 and ok5 and ok6) else '存在失败'}\n")
        print(f"  报告已写入 {report}")
    except Exception as e:                                  # noqa: BLE001
        print(f"  !! 报告写入失败: {e}")

    window.destroy()


def _prepare_webview_storage(storage: str, force: bool = False) -> str:
    """按版本号让 WebView2 的资源缓存失效。

    为什么必须做：WebView2 会把 js/css 一并缓存。程序更新后如果命中旧缓存，
    界面会继续跑**旧代码** —— 表现就是「文件明明改了却不生效」，
    而且完全没有任何报错，极难排查（这次就踩了：改了 store.js 却发现行为没变）。

    只清 Cache / Code Cache / GPUCache，**不动 Local Storage**，
    所以主题等界面设置不会丢。
    """
    marker = os.path.join(os.path.dirname(storage), "webview_assets.version")
    try:
        with open(marker, encoding="utf-8") as f:
            seen = f.read().strip()
    except Exception:                                       # noqa: BLE001
        seen = ""

    if not force and seen == APP_VERSION:
        return "命中"

    base = os.path.join(storage, "EBWebView", "Default")
    cleared = []
    for name in ("Cache", "Code Cache", "GPUCache"):
        p = os.path.join(base, name)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
            cleared.append(name)

    try:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(APP_VERSION)
    except Exception:                                       # noqa: BLE001
        pass
    return ("清空 " + "、".join(cleared)) if cleared else "无缓存可清"


_SINGLE_INSTANCE_HANDLE = None


def _acquire_single_instance() -> str:
    """确保只有一个实例在跑。返回 "" 表示拿到；否则返回占用者的说明。

    **为什么必须做**：pywebview 通过内置 HTTP 服务器把页面发给窗口。
    pywebview 选端口用的是随机空闲端口，逻辑本身没问题，但 Windows 的
    SO_REUSEADDR 语义和 Linux 不同 —— **它允许两个进程绑定同一个端口**。
    于是第二个实例也能绑成功，可新连接会被先绑的那个进程接走，
    结果新窗口加载的是**旧实例的页面**（也就是旧版本的界面），
    而且不报任何错。

    实测踩过：一个提权残留的旧 EXE 占着端口，之后所有源码模式的界面
    改动「怎么改都不生效」，排查了很久才发现页面根本不是自己的。

    所以这里宁可明确失败，也不静默加载别人的页面。
    """
    global _SINGLE_INSTANCE_HANDLE
    if os.name != "nt":
        return ""
    import ctypes
    ERROR_ALREADY_EXISTS = 183
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        # Local\ 而不是 Global\：不同用户会话各跑一个互不影响
        handle = k32.CreateMutexW(None, False,
                                  "Local\\mahiru-assistant-single-instance")
        if not handle:
            return ""                       # 拿不到锁就算了，不要拦住用户
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            k32.CloseHandle(ctypes.c_void_p(handle))
            return "已有另一个 mahiru小助手 在运行"
        _SINGLE_INSTANCE_HANDLE = handle    # 必须留着，否则锁会被释放
        return ""
    except Exception:                                       # noqa: BLE001
        return ""


def _is_running_exe() -> bool:
    """当前进程可执行文件是不是本程序（而不是 python.exe）。"""
    return os.path.basename(sys.executable).lower().startswith("mahiru")


def main() -> int:
    _install_crash_handler()

    # --selftest 复用核心的自检，方便打包后做冒烟验证
    if "--selftest" in sys.argv:
        from .core import junk
        rc1 = mem.selftest()
        rc2 = junk.cli_selftest()
        return 0 if rc1 == 0 and rc2 == 0 else 1

    # --update-rules [--offline]：不开界面直接更新清理规则。
    # 打包后没有终端，这是唯一能在命令行里更新规则的方式；
    # 也用来验证「打包版能不能更新规则并跨重启保留」。
    if "--update-rules" in sys.argv:
        # 注意：这里的导入必须用别名。函数内写 `from .paths import config_dir`
        # 会让 config_dir 在整个 main() 里变成局部变量，导致下面
        # storage = os.path.join(config_dir(), ...) 抛 UnboundLocalError。
        # 这个坑只在打包版冒烟时才暴露（新入口在那一行之前就 return 了）。
        from .core import rule_update
        from .paths import config_dir as _cfg_dir
        offline = "--offline" in sys.argv
        target = os.path.join(_cfg_dir(), "third_party_rules.py")
        print(f"{APP_TITLE} 规则更新")
        print(f"  目标 {target}")
        moved = rule_update.migrate_legacy_cache()
        if moved:
            print(f"  迁移旧缓存 {moved} 个文件")
        try:
            st = rule_update.update(target, offline=offline,
                                    log=lambda m: print("  " + m))
        except Exception as e:                              # noqa: BLE001
            print(f"!! 失败：{e}")
            with open(os.path.join(_cfg_dir(), "rule_update_result.txt"),
                      "w", encoding="utf-8") as f:
                f.write(f"FAIL {type(e).__name__}: {e}\n")
            return 1
        msg = (f"OK safe={st['safe']} caution={st['caution']} "
               f"files={st['files']} size={st['size']} path={target}\n")
        print(f"  完成：{msg.strip()}")
        with open(os.path.join(_cfg_dir(), "rule_update_result.txt"),
                  "w", encoding="utf-8") as f:
            f.write(msg)
        return 0

    if not os.path.exists(WEB_INDEX):
        print(f"错误：找不到界面文件 {WEB_INDEX}", file=sys.stderr)
        return 2

    # 提权重启时旧进程会传 --wait-pid 过来：必须等它退出再初始化界面。
    # 两个进程共用同一个 WebView2 用户数据目录，那个目录不允许同时被
    # 两个进程打开 —— 不等的话新窗口会起不来或白屏。
    wait_pid = elevation.requested_wait_pid()
    if wait_pid:
        note = elevation.wait_for_pid_exit(wait_pid)
        if "--smoke" not in sys.argv:
            print(f"[elevate] {note}", file=sys.stderr)
    else:
        # 提权重启时旧进程还活着，这里本来就该等它，不能算「重复启动」。
        # 其余情况一律拦住：见 _acquire_single_instance 的说明。
        busy = _acquire_single_instance()
        if busy:
            msg = (f"{busy}。\n"
                   f"同时开两个会互相抢页面端口，新窗口可能显示旧版本的界面"
                   f"（而且不报错），所以这里直接停下。")
            print(f"[single-instance] {msg}", file=sys.stderr)
            try:
                with open(os.path.join(config_dir(), "single_instance.txt"),
                          "w", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:                               # noqa: BLE001
                pass
            return 3

    # 与旧版保持一致：先开特权（工作集/待机列表等操作需要），再设 DPI 感知
    try:
        mem.enable_all_privileges()
    except Exception:                                       # noqa: BLE001
        pass
    try:
        mem.enable_dpi_awareness()
    except Exception:                                       # noqa: BLE001
        pass

    jobs = JobManager()
    api = Api(jobs)
    w, h, x, y = _geometry()

    window = webview.create_window(
        f"{APP_TITLE} v{APP_VERSION}",
        WEB_INDEX,
        js_api=api,
        width=w,
        height=h,
        x=x,
        y=y,
        min_size=(MIN_W, MIN_H),
        background_color="#F6F7F9",
        text_select=False,
    )

    # 界面点「以管理员重启」成功后要真的关掉本进程，
    # 否则会留下两个窗口（旧的非管理员 + 新的管理员）。
    # 必须在 create_window 之后才能拿到 window。
    api.set_quit_hook(window.destroy)

    # 开发时用 --debug 打开右键菜单与开发者工具
    debug = "--debug" in sys.argv

    # private_mode 默认是 True —— 那样 localStorage 不落盘，主题设置每次启动
    # 都会丢。这里关掉它，并把存储放到**可写目录**下：
    # onefile 打包后 __file__ 在临时解压目录里，放那里每次启动都会重置。
    storage = os.path.join(config_dir(), "webview")
    os.makedirs(storage, exist_ok=True)
    cache_note = _prepare_webview_storage(storage, force="--nocache" in sys.argv)
    if "--smoke" not in sys.argv:
        print(f"[webview] 资源缓存：{cache_note}", file=sys.stderr)

    # --quit-test：验证「界面调 quit_app 能真的结束进程」。
    # 提权重启靠它关掉旧窗口，不验证的话很容易变成两个窗口。
    # 做法：开窗 → 等几秒 → 从 JS 里调 quit_app → 若进程没退出就写失败标记。
    if "--quit-test" in sys.argv:
        def _quit_probe(win):
            time.sleep(3.0)
            try:
                win.evaluate_js("Bridge.call('quit_app')")
            except Exception as e:                          # noqa: BLE001
                print(f"evaluate 失败: {e}", file=sys.stderr)
            # quit_app 有效的话窗口会被销毁、webview.start 返回、进程退出，
            # 根本走不到这里。走到了就说明没关掉。
            time.sleep(8.0)
            with open(os.path.join(config_dir(), "quit_test.txt"),
                      "w", encoding="utf-8") as f:
                f.write("FAIL 调了 quit_app 但进程没退出\n")

        webview.start(_quit_probe, (window,),
                      private_mode=False, storage_path=storage)
        with open(os.path.join(config_dir(), "quit_test.txt"),
                  "w", encoding="utf-8") as f:
            f.write("OK 进程已退出\n")
        return 0

    # --smoke N：自动冒烟（开窗 → 等 N 秒 → 读回 DOM 状态 → 关窗）
    # 注意 pywebview 的 func 是 func(*args) 调用，不会自动收到窗口，要显式传
    if "--smoke" in sys.argv:
        i = sys.argv.index("--smoke")
        secs = float(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 4.0
        webview.start(_smoke, (window, secs),
                      private_mode=False, storage_path=storage)
        return 0

    webview.start(_on_start,
                  (window, _arg_value("--page"), _arg_value("--theme"),
                   _arg_value("--click"), _arg_value("--scroll"),
                   _arg_value("--eval")),
                  debug=debug, private_mode=False, storage_path=storage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
