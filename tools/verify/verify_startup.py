# -*- coding: utf-8 -*-
"""验证启动前的 WebView2 检查，以及启动期崩溃的兜底报告。

要守的事：Win10 上没装 WebView2 运行时的机器，pywebview 会**静默降级到
MSHTML（IE 内核）**，而前端是 ES6 —— 用户看到一片白，什么提示都没有。
所以必须在开窗之前查出来、明确告诉用户，并且**绝不能让那个白窗开出去**。

这个脚本不会真的开窗，也不会弹对话框：`create_window` 被打桩成抛哨兵异常，
`_fatal` 被打桩成只记录。
"""
import os
import sys
import tempfile
import traceback

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SRC)

from app import main as M                              # noqa: E402

fail = 0


def check(label, got, want):
    global fail
    ok = got == want
    if not ok:
        fail += 1
    print(f"  [{'ok' if ok else '!!'}] {label}: {got!r}"
          + ("" if ok else f"  (期望 {want!r})"))


class _ReachedWindow(Exception):
    """create_window 被打桩到这里，说明真的走到了开窗那一步。"""


fatal_calls = []

_real_create = M.webview.create_window
_real_fatal = M._fatal
_real_status = M._webview2_version
_real_argv = list(sys.argv)

M.webview.create_window = lambda *a, **k: (_ for _ in ()).throw(_ReachedWindow())
M._fatal = lambda title, message: fatal_calls.append((title, message))
# 单实例锁与提权等待都跟本测试无关，打掉以免干扰（也避免真去抢锁）
M._acquire_single_instance = lambda: ""
M.elevation.requested_wait_pid = lambda: None
M.elevation.wait_for_pid_exit = lambda pid: ""
# 冒烟用的命令行参数会改变行为，跑之前先清干净
sys.argv = ["mahiru"]


def run_main(version):
    """把 _webview2_version 换成给定值，跑一次 main()，返回 (返回值, 是否开到了窗)。"""
    fatal_calls.clear()
    M._webview2_version = version
    try:
        rc = M.main()
        return rc, False
    except _ReachedWindow:
        return None, True


print("=" * 66)
print("A. 版本判定")
print("=" * 66)

real_ver = _real_status.__wrapped__ if hasattr(_real_status, "__wrapped__") else None
M._webview2_version = _real_status
host_ver = M._webview2_version()
print(f"  本机 WebView2 = {host_ver!r}")
print(f"  webview2_status() = {M.webview2_status()}")
check("本机能查到运行时", host_ver is not None, True)

for s, want in (("86.0.622.0", True), ("86.0.621.0", False), ("85.0.1.1", False),
                ("155.0.4283.45", True), ("86.0.622.0.1", True), ("garbage", False)):
    check(f"版本 {s} 够用", M._ver_tuple(s) >= M._WEBVIEW2_MIN, want)

check("够用时说明里带版本号", M.webview2_status()[1].startswith("Edge WebView2"), True)

print()
print("=" * 66)
print("B. 没有运行时：必须拦住，不能开窗")
print("=" * 66)

rc, reached = run_main(lambda: None)
check("main() 返回码", rc, 4)
check("  没有走到开窗", reached, False)
check("  弹了错", len(fatal_calls), 1)
if fatal_calls:
    title, msg = fatal_calls[0]
    check("  标题提到缺少组件", "缺少" in title, True)
    check("  正文说明缺的是 WebView2", "WebView2" in msg, True)
    check("  正文给了下载办法", "下载" in msg, True)
    check("  正文提了逃生参数", "--ignore-webview2" in msg, True)
    check("  正文点出检测结果", "没有检测到" in msg, True)

print()
print("=" * 66)
print("C. 版本过低：同样拦住")
print("=" * 66)

rc, reached = run_main(lambda: "80.0.1.1")
check("main() 返回码", rc, 4)
check("  没有走到开窗", reached, False)
check("  报的是版本过低", "过低" in (fatal_calls[0][1] if fatal_calls else ""), True)
check("  报出了实际版本", "80.0.1.1" in (fatal_calls[0][1] if fatal_calls else ""), True)

print()
print("=" * 66)
print("D. --ignore-webview2 是逃生口")
print("=" * 66)

sys.argv = ["mahiru", "--ignore-webview2"]
rc, reached = run_main(lambda: None)
check("跳过检查后走到了开窗", reached, True)
check("  没有弹错", len(fatal_calls), 0)
sys.argv = ["mahiru"]

print()
print("=" * 66)
print("E. 有运行时：正常放行")
print("=" * 66)

rc, reached = run_main(_real_status)
check("走到了开窗", reached, True)
check("  没有弹错", len(fatal_calls), 0)

print()
print("=" * 66)
print("F. 启动期崩溃的兜底报告")
print("=" * 66)

tmp = tempfile.mkdtemp(prefix="mahiru_startup_")
log = os.path.join(tmp, "boom.log")
_real_log = M.LOG_PATH
M.LOG_PATH = log

# 有控制台时不该弹窗，只写日志
shown = []
import ctypes                                          # noqa: E402
_real_mb = ctypes.windll.user32.MessageBoxW
ctypes.windll.user32.MessageBoxW = lambda *a: shown.append(a) or 0
_real_stderr = sys.stderr
try:
    M._install_crash_handler()
    sys.stderr = _real_stderr                            # 有控制台
    try:
        raise RuntimeError("测试用的假崩溃")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    check("有控制台时不弹窗", len(shown), 0)
    check("崩溃写进了日志", os.path.exists(log), True)
    body = open(log, encoding="utf-8").read() if os.path.exists(log) else ""
    check("  日志里有异常文本", "测试用的假崩溃" in body, True)

    # 模拟 --windowed：stderr 是 None
    shown.clear()
    sys.stderr = None
    try:
        raise RuntimeError("windowed 下的假崩溃")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    check("stderr 为 None 时弹窗", len(shown), 1)
    if shown:
        check("  弹窗里带异常", "windowed 下的假崩溃" in str(shown[0]), True)
        check("  弹窗里带日志路径", os.path.basename(log) in str(shown[0]), True)
finally:
    sys.stderr = _real_stderr
    ctypes.windll.user32.MessageBoxW = _real_mb
    M.LOG_PATH = _real_log

print()
print("=" * 66)
print("G. run.py 的入口兜底")
print("=" * 66)

run_py = os.path.join(SRC, "run.py")
src = open(run_py, encoding="utf-8").read()
check("run.py 包住了导入", "except BaseException" in src, True)
check("  run.py 有报告函数", "def _report(" in src, True)
check("  run.py 会弹窗", "MessageBoxW" in src, True)
check("  run.py 不吞掉 SystemExit", "except SystemExit:" in src, True)

# 当模块导入 run.py（__name__ != "__main__"，不会真的去跑 main），
# 然后直接调它的 _report —— 这才是「导入 app.main 就炸」时走的那条路。
import importlib.util                                  # noqa: E402

spec = importlib.util.spec_from_file_location("mahiru_runpy", run_py)
run_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_mod)
check("run.py 能被当模块导入", callable(getattr(run_mod, "_report", None)), True)

_popup = []
run_mod._log_path = lambda: log
ctypes.windll.user32.MessageBoxW = lambda *a: _popup.append(a) or 0
try:
    run_mod._report(traceback.format_exc() + "\nRuntimeError: 导入期探针")
    check("报告时弹了窗", len(_popup), 1)
    check("  弹窗里带异常", "导入期探针" in str(_popup[0]), True)
    check("  弹窗里带日志路径", os.path.basename(log) in str(_popup[0]), True)
    body2 = open(log, encoding="utf-8").read()
    check("  日志里写了「启动失败」", "启动失败" in body2, True)
finally:
    ctypes.windll.user32.MessageBoxW = _real_mb

print()
print("=" * 66)
print("全部通过" if fail == 0 else f"{fail} 项失败")
sys.exit(1 if fail else 0)
