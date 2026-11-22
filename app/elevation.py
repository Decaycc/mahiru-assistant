# -*- coding: utf-8 -*-
"""UAC 检测与自我提权重启。

对应原 .bat 启动器里的第 1 组功能（`net session` 探测 + `Start-Process -Verb RunAs`）。
改为进程内实现后，不再需要中间那个控制台窗口闪一下。

要点：提权会**重启进程**，内存里的状态全部丢失。所以调用方必须先把当前配置
落盘，再调 relaunch()。
"""
import ctypes
import os
import sys

from .core import mem

# 用户点了「否」时 ShellExecuteW 返回的码（ERROR_CANCELLED）
ERROR_CANCELLED = 1223


def is_admin() -> bool:
    """是否已提权。直接复用核心里的实现，避免两处判定不一致。"""
    return mem.is_admin()


def _frozen() -> bool:
    """是否运行在 PyInstaller 打包出来的 EXE 里。"""
    return bool(getattr(sys, "frozen", False))


def relaunch(argv: list[str] | None = None) -> tuple[bool, str]:
    """以管理员身份重启自己。

    返回 (是否成功发起, 说明)。成功发起后调用方**必须让本进程退出**，
    否则会留下两个窗口。

    这里会额外传一个 `--wait-pid=<本进程 PID>` 给新进程，让它先等本进程
    彻底退出再初始化界面。两个原因：

    1. 不这样做会同时存在两个窗口 —— 旧的普通权限、新的管理员权限
    2. 更要命的是两者**共用同一个 WebView2 用户数据目录**
       （config/webview），而 WebView2 不允许两个进程同时打开它。
       旧进程还没释放，新进程会起不来或者起得残缺（白屏）。
    """
    if is_admin():
        return False, "已经是管理员权限，无需提权"

    args = [a for a in (sys.argv[1:] if argv is None else argv)
            if not a.startswith("--wait-pid")]
    # 链式提权时旧的 --wait-pid 要丢掉，只保留本进程自己的
    args.append(f"--wait-pid={os.getpid()}")

    if _frozen():
        exe = sys.executable
        params = " ".join(f'"{a}"' for a in args)
    else:
        # 源码运行：用 pythonw.exe（无控制台窗口）拉起同一个脚本
        exe = sys.executable
        if exe.lower().endswith("python.exe"):
            cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if os.path.exists(cand):
                exe = cand
        script = os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))
        params = " ".join([f'"{script}"'] + [f'"{a}"' for a in args])

    try:
        shell32 = ctypes.windll.shell32
        # ShellExecuteW 返回 >32 表示成功；<=32 是错误码
        rc = shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        if rc <= 32:
            if rc == 0:
                # 0 通常是 UAC 被用户拒绝
                return False, "已取消提权（或系统拒绝了 UAC 请求）"
            return False, f"启动失败，ShellExecuteW 返回 {rc}"
        return True, "已发起提权启动，本进程即将退出"
    except Exception as e:                                  # noqa: BLE001
        return False, f"提权异常：{type(e).__name__}: {e}"


def requested_wait_pid() -> int:
    """取出命令行里的 --wait-pid=N（没有则返回 0）。"""
    for a in sys.argv[1:]:
        if a.startswith("--wait-pid="):
            try:
                return int(a.split("=", 1)[1])
            except ValueError:
                return 0
    return 0


def wait_for_pid_exit(pid: int, timeout: float = 20.0,
                      grace: float = 0.8) -> str:
    """等指定进程退出（最多 timeout 秒）。

    grace 是额外多等的时间：进程对象退出后，它持有的文件句柄
    （WebView2 的用户数据目录）可能还没完全释放，留一点缓冲更稳。

    返回一句说明，用于日志。
    """
    if pid <= 0:
        return "未指定"
    import time as _time
    SYNCHRONIZE = 0x00100000
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(SYNCHRONIZE, False, pid)
    except Exception as e:                                  # noqa: BLE001
        return f"打开进程失败：{e}"
    if not h:
        return f"进程 {pid} 已经不在了"
    try:
        rc = k32.WaitForSingleObject(h, int(timeout * 1000))
        if rc == 0:
            _time.sleep(grace)
            return f"已等待进程 {pid} 退出"
        return f"等待进程 {pid} 超时（{timeout:.0f}s），继续启动"
    finally:
        k32.CloseHandle(h)
