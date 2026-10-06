# -*- coding: utf-8 -*-
"""把 mahiru小助手 打成**单文件 EXE**。

用法（建议用干净的 venv，别用装了 numpy/pandas 那种大环境，
否则即使排除了这些包，扫描阶段也会明显变慢）：

    <你的venv>\\Scripts\\python.exe tools\\build.py
    ... build.py --onedir      # 想对比启动速度时用
    ... build.py --keep        # 保留 build/ 中间产物便于排查
    ... build.py --console     # 保留控制台窗口，排查启动问题时用
    ... build.py --name X      # 换产物名（旧版本正开着时 EXE 会被锁住）

几个关键取舍，都不是随手写的：

· --onefile 会解压到 %TEMP%\\_MEIxxxx，**每次启动都要解压**，冷启动会慢 2~4 秒。
  这是选单文件形态必须接受的代价；界面侧已经在启动时先渲染骨架来弱化等待感。

· --noupx：UPX 能压小体积，但会明显拖慢启动，而且**可能损坏 pythonnet 的
  原生依赖**。稳定性优先，不用。

· 必须显式收集 clr / clr_loader / webview：PyInstaller 的静态分析看不穿
  pythonnet 的运行时加载，漏了就会「打包成功但一启动就崩」。

· 排除 tkinter / numpy / pandas / PIL 等：本项目不用它们，
  不排除的话体积会从几十 MB 涨到两三百 MB。特别注意 **不能排除 PIL** ——
  pywebview 的某些路径会用到它。
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

APP_NAME = "mahiru小助手"
# 入口必须是**包外**的脚本：PyInstaller 把入口当顶层模块执行，
# 包内的 app/__main__.py 含相对导入，会直接报
# "attempted relative import with no known parent package"。
ENTRY = os.path.join(ROOT, "run.py")
ICON = os.path.join(ROOT, "design", "icon.ico")

# 这些要么用不到，要么体积巨大。
# 注意：**不能排除 distutils** —— PyInstaller 自己的 pre_safe_import hook 会去
# alias 它，排掉会直接报 "Target module distutils already imported as
# ExcludedModule"，打包当场失败（踩过一次）。
EXCLUDES = [
    "tkinter", "numpy", "pandas", "matplotlib", "scipy", "PyQt5", "PySide2",
    "PySide6", "wx", "IPython", "jupyter", "notebook", "pytest",
    "pip", "lib2to3", "unittest", "pydoc_data",
    "sqlite3", "xmlrpc", "pdb", "doctest", "curses",
]

# pythonnet / pywebview 必须显式收集，否则运行时才炸
HIDDEN = ["clr", "clr_loader", "webview", "webview.platforms.edgechromium"]
COLLECT_ALL = ["clr_loader", "webview", "pythonnet"]


def run(cmd, **kw):
    print("  $ " + " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd))
    return subprocess.call(cmd, **kw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onedir", action="store_true",
                    help="打成目录形态（启动快，但不是单文件）")
    ap.add_argument("--keep", action="store_true", help="保留 build/ 中间产物")
    ap.add_argument("--console", action="store_true",
                    help="保留控制台窗口（排查启动问题时用）")
    ap.add_argument("--name", default=APP_NAME,
                    help="产物名（默认 GameBoostNext）。"
                         "旧版本正在运行时 EXE 会被锁住，换个名字就能先出一版")
    args = ap.parse_args()

    app_name = args.name

    if not os.path.exists(ICON):
        print(f"!! 找不到图标 {ICON}，请先跑 design/make_icon.py")
        return 2

    dist = os.path.join(ROOT, "dist")
    build = os.path.join(ROOT, "build")
    spec = os.path.join(ROOT, f"{app_name}.spec")

    mode = "--onedir" if args.onedir else "--onefile"
    print(f"打包 {app_name}  ({mode})")
    print("=" * 62)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        mode,
        "--noupx",                       # UPX 会拖慢启动并可能损坏 pythonnet
        "--name", app_name,
        "--icon", ICON,
        "--distpath", dist,
        "--workpath", build,
        "--specpath", ROOT,
        # 界面资源：整个 web 目录带进去，运行时按 resource_root()/web 找
        "--add-data", f"{os.path.join(ROOT, 'web')}{os.pathsep}web",
        # 规则数据：核心用相对导入，必须跟着进包
        "--add-data",
        f"{os.path.join(ROOT, 'app', 'core', 'third_party_rules.py')}"
        f"{os.pathsep}app/core",
    ]
    if not args.console:
        cmd.append("--windowed")         # 不弹控制台窗口

    for h in HIDDEN:
        cmd += ["--hidden-import", h]
    for c in COLLECT_ALL:
        cmd += ["--collect-all", c]
    for e in EXCLUDES:
        cmd += ["--exclude-module", e]

    cmd.append(ENTRY)

    t0 = time.time()
    rc = run(cmd, cwd=ROOT)
    if rc != 0:
        print(f"\n!! 打包失败，退出码 {rc}")
        return rc

    exe = os.path.join(dist, f"{app_name}.exe" if not args.onedir
                       else os.path.join(app_name, f"{app_name}.exe"))
    if not os.path.exists(exe):
        print(f"\n!! 打包命令成功但找不到产物：{exe}")
        return 3

    size = os.path.getsize(exe)
    print()
    print("=" * 62)
    print(f"产物   {exe}")
    print(f"体积   {size / 1048576:.1f} MB")
    print(f"耗时   {time.time() - t0:.0f} 秒")

    if not args.keep:
        shutil.rmtree(build, ignore_errors=True)
        try:
            os.remove(spec)
        except OSError:
            pass
        print("       （已清理 build/ 与 .spec，用 --keep 可保留）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
