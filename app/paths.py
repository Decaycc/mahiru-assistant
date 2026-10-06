# -*- coding: utf-8 -*-
"""路径解析。

打包成 onefile 之后，`__file__` 指向的是**每次启动都会变的临时解压目录**
（%TEMP%\\_MEIxxxx）。如果配置和日志继续按 `__file__` 推导，就会出现：

    · 每次启动配置都是空的（上一次写的在别的临时目录里，已被删掉）
    · 日志散落在临时目录，用户根本找不到

所以这里把「只读资源」和「可写数据」分开：

    resource_root()  只读：界面文件、内置数据。frozen 下是临时解压目录
    app_root()       可写：配置、日志。永远指向一个持久位置
    config_dir()     上面两者之下的 config/

可写目录的选择顺序：EXE 同级目录（便携） → %APPDATA%\\GameBoostNext（不可写时）
"""
import os
import sys


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包出来的 EXE 里。"""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> str:
    """只读资源根目录（web/、内置数据文件所在处）。"""
    if is_frozen():
        # PyInstaller 的 onefile 会把资源解压到这里
        return getattr(sys, "_MEIPASS", os.path.dirname(
            os.path.abspath(sys.executable)))
    # 源码运行：app/paths.py -> app/ -> 项目根
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _writable(path: str) -> bool:
    """探测目录是否可写。不能只看 os.access —— 在 Program Files 下会误判。"""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".gb_write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("x")
        os.remove(probe)
        return True
    except Exception:                                       # noqa: BLE001
        return False


def app_root() -> str:
    """可写的应用根目录（配置与日志放这里）。"""
    if not is_frozen():
        return resource_root()

    # 便携优先：EXE 同级
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    if _writable(exe_dir):
        return exe_dir

    # 装在 Program Files 之类不可写的位置时，退回用户目录
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    fallback = os.path.join(base, "mahiru")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def config_dir() -> str:
    """配置文件目录，保证存在。"""
    p = os.path.join(app_root(), "config")
    os.makedirs(p, exist_ok=True)
    return p
