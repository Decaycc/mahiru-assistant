# -*- coding: utf-8 -*-
"""一次跑完 tools/verify/ 下的全部验证脚本，并汇总结果。

用法：

    <venv>\\Scripts\\python.exe tools\\run_checks.py
    ... run_checks.py --list          # 只列出会跑哪些，不执行
    ... run_checks.py --only recycle  # 只跑名字里含 recycle 的

为什么要有这个：这些脚本以前都散在 %TEMP% 里，重启一次就没了 —— 也就等于
「安全保证」没有留下任何可复现的证据。现在它们进了仓库，这个脚本把
「跑一遍」压缩成一条命令，`tools/build.py` 出包之前会先调它。

退出码：全部通过 0，有任何一项失败 1，一个脚本都没找到 2。
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# 与 tools/verify/*.py 里的定义保持一致
FIXTURE_ROOT = (os.environ.get("MAHIRU_FIXTURE_ROOT")
                or os.path.join(os.path.expanduser("~"), ".mahiru_fixture"))
VERIFY_DIR = os.path.join(HERE, "verify")


def find_scripts(only: str = "") -> list[str]:
    pat = os.path.join(VERIFY_DIR, "verify_*.py")
    found = sorted(glob.glob(pat))
    if only:
        found = [f for f in found if only.lower() in os.path.basename(f).lower()]
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="",
                    help="只跑文件名里含这个字串的脚本")
    ap.add_argument("--list", action="store_true", help="只列出，不执行")
    ap.add_argument("--quiet", action="store_true",
                    help="只打失败脚本的输出（出包时用）")
    args = ap.parse_args()

    scripts = find_scripts(args.only)
    if not scripts:
        print(f"!! 在 {VERIFY_DIR} 里没找到 verify_*.py")
        return 2

    if args.list:
        for s in scripts:
            print("  " + os.path.relpath(s, ROOT))
        print(f"\n共 {len(scripts)} 个")
        return 0

    print("跑验证脚本")
    print("=" * 68)
    print(f"脚本目录  {VERIFY_DIR}")
    print(f"夹具目录  {FIXTURE_ROOT}（跑之前会清空一次）")
    print(f"解释器    {sys.executable}")
    print("=" * 68)

    # 夹具放在 %USERPROFILE%\.mahiru_fixture（可用 MAHIRU_FIXTURE_ROOT 覆盖）。
    # 不能放仓库里：仓库在「文档」底下，而 Documents 是 junk 的保护目录，
    # 前缀判定会把整棵树都判成受保护，测出来全是假结论。
    # 也不能放 %TEMP%：那在 \AppData\ 下，而 \appdata\ 是 junk 的
    # 文件类型黑名单串，会让 scan_types 跳过一切路径。
    # 开跑前清一次，免得上次崩在中途留下脏数据。
    shutil.rmtree(FIXTURE_ROOT, ignore_errors=True)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    results = []
    t_all = time.time()
    for s in scripts:
        name = os.path.basename(s)
        t0 = time.time()
        proc = subprocess.run([sys.executable, s], cwd=ROOT, env=env,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        dt = time.time() - t0
        out = ((proc.stdout or "") + (proc.stderr or "")).rstrip()
        ok = proc.returncode == 0
        results.append((name, ok, dt, out))

        if ok and args.quiet:
            print(f"  [OK]   {name}  ({dt:.1f}s)")
            continue
        print()
        print("-" * 68)
        print(f"{'[OK]  ' if ok else '[FAIL]'} {name}   ({dt:.1f}s, 退出码 {proc.returncode})")
        print("-" * 68)
        if out:
            print(out)
        elif not ok:
            print("  （脚本没有输出任何东西就失败了）")

    shutil.rmtree(FIXTURE_ROOT, ignore_errors=True)

    bad = [r for r in results if not r[1]]
    print()
    print("=" * 68)
    print(f"共 {len(results)} 个脚本，通过 {len(results) - len(bad)}，"
          f"失败 {len(bad)}，总耗时 {time.time() - t_all:.1f} 秒")
    if bad:
        print("失败的：")
        for name, _ok, _dt, _out in bad:
            print("  · " + name)
    print("=" * 68)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
