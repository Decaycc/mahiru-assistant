# -*- coding: utf-8 -*-
"""更新第三方清理规则的命令行入口。

真正的实现在 app/core/rule_update.py —— 软件里的「更新规则」按钮
调的是同一个函数，保证只有一份实现。

用法（在 GameBoostNext 目录下）：
    python tools\\update_rules.py               联网抓最新并重新生成
    python tools\\update_rules.py --check       只看上游状态，不写文件
    python tools\\update_rules.py --offline     只用缓存（断网也能重跑）
    python tools\\update_rules.py --no-winapp3  不含 Winapp3（见下）

生成的规则写到 app/core/third_party_rules.py（源码运行时用），
并同步一份给旧版 tkinter 工具。

关于许可：Winapp3.ini 的许可要求「若要修改/分发/托管，请先联系作者」。
纯自用没问题；要公开发布请先跟对方打招呼，或用 --no-winapp3。
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import rule_update  # noqa: E402

OUT = os.path.join(ROOT, "app", "core", "third_party_rules.py")
# 旧版 tkinter 工具也读这份，默认一起更新
LEGACY_OUT = os.path.join(os.path.dirname(ROOT), "GameBoost",
                          "third_party_rules.py")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="只用本地缓存")
    ap.add_argument("--check", action="store_true", help="只报状态，不写文件")
    ap.add_argument("--no-winapp3", action="store_true",
                    help="不含 Winapp3（不打算公开发布则无需在意）")
    ap.add_argument("--no-legacy", action="store_true",
                    help="不更新旧版 tkinter 工具的规则文件")
    args = ap.parse_args()

    for s in ("stdout", "stderr"):
        try:
            getattr(sys, s).reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                   # noqa: BLE001
            pass

    print("更新第三方清理规则")
    print("=" * 64)
    print(f"缓存目录 {rule_update.cache_dir()}")
    moved = rule_update.migrate_legacy_cache()
    if moved:
        print(f"  已从旧位置迁移 {moved} 个缓存文件")
    print()

    if args.check:
        for k, v in rule_update.check_available().items():
            if v.get("ok"):
                print(f"  {k:<10} 上游 {v['size'] // 1024} KB  sha {v['sha']}")
            else:
                print(f"  {k:<10} !! {v['error']}")
        print()
        print("--check：未写入文件")
        return 0

    try:
        stats = rule_update.update(
            OUT, offline=args.offline,
            include_winapp3=not args.no_winapp3,
            log=lambda m: print("  " + m))
    except Exception as e:                                  # noqa: BLE001
        print(f"\n!! 失败：{e}")
        return 1

    print()
    print("-" * 64)
    print(f"安全级目录 {stats['safe']}   谨慎级目录 {stats['caution']}"
          f"   按模式清理 {stats['files']}")
    print("解析明细：")
    for k, v in sorted(stats["counters"].items(), key=lambda x: -x[1]):
        print(f"    {k:<22} {v}")
    print()
    print(f"已写入 {os.path.relpath(OUT, ROOT)}  ({stats['size'] // 1024} KB)")

    if not args.no_legacy and os.path.isdir(os.path.dirname(LEGACY_OUT)):
        try:
            with open(OUT, encoding="utf-8") as src, \
                    open(LEGACY_OUT, "w", encoding="utf-8", newline="\n") as dst:
                dst.write(src.read())
            print(f"已同步到旧版 {os.path.relpath(LEGACY_OUT, os.path.dirname(ROOT))}")
        except Exception as e:                              # noqa: BLE001
            print(f"!! 同步旧版失败：{e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
