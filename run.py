# -*- coding: utf-8 -*-
"""打包入口。

为什么不直接用 app/__main__.py 当 PyInstaller 的入口：
那时脚本是作为**顶层模块**被执行的，没有包上下文，
里面任何 `from .x import y` 都会报
「attempted relative import with no known parent package」。
所以入口要放在包外，用绝对导入把包引进来。

`python -m app` 仍然走 app/__main__.py，两者互不影响。
"""
import os
import sys
import traceback

# 源码运行时把项目根加入 sys.path；打包后 __file__ 在解压目录，
# 该目录本身已在 sys.path 里，这一步无害。
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _log_path() -> str:
    """日志路径。优先问 app.paths，问不到就按打包后的约定自己拼。"""
    try:
        from app.paths import config_dir           # noqa: PLC0415
        return os.path.join(config_dir(), "gameboostnext_error.log")
    except Exception:                              # noqa: BLE001
        base = os.environ.get("APPDATA") or _HERE
        return os.path.join(base, "mahiru", "gameboostnext_error.log")


def _report(exc_text: str) -> None:
    """把启动期的崩溃写进日志，并弹一个对话框。

    为什么这一层也要兜：`--windowed` 打包后没有控制台，未捕获异常的表现
    就是「双击了，什么都没发生」。而 app/main.py 里的崩溃钩子是在 main()
    内部才装的 —— **导入期**出的错（`from app.main import main` 那一行）
    它盖不到。WebView2 相关的炸点恰好就有在导入期或启动早期的。
    """
    path = _log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 60 + "\n")
            f.write("启动失败\n")
            f.write(exc_text)
    except Exception:                              # noqa: BLE001
        pass

    last = ""
    for line in reversed(exc_text.strip().splitlines()):
        if line.strip():
            last = line.strip()
            break

    try:
        import ctypes                              # noqa: PLC0415
        ctypes.windll.user32.MessageBoxW(
            None,
            "Mahiru 启动失败。\n\n"
            f"{last}\n\n"
            f"详细信息已写入：\n{path}",
            "Mahiru",
            0x10,                                      # MB_ICONERROR
        )
    except Exception:                              # noqa: BLE001
        pass


try:
    from app.main import main  # noqa: E402
except BaseException:  # noqa: BLE001
    _report(traceback.format_exc())
    sys.exit(1)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        _report(traceback.format_exc())
        sys.exit(1)
