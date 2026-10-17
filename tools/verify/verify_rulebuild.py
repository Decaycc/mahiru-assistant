# -*- coding: utf-8 -*-
"""离线跑一遍 build_text，看 ExcludeKey 过滤 + Archived 降档后的实际数字。"""
import io
import os
import sys

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SRC)

from app.core import rule_update as ru   # noqa: E402

print("=" * 62)
print("build_text(offline=True)")
print("=" * 62)
text, stats = ru.build_text(offline=True, log=lambda m: print("   ", m))

print()
print("=" * 62)
print("counters")
print("=" * 62)
for k, v in sorted(stats["counters"].items(), key=lambda x: -x[1]):
    print(f"  {k:<28} {v}")

print()
print("=" * 62)
print("stats")
print("=" * 62)
for k in ("safe", "caution", "files", "caution_files"):
    print(f"  {k:<16} {stats[k]}")
print(f"  MIN_SAFE_DIRS    {ru.MIN_SAFE_DIRS}")
print(f"  安全闸           "
      f"{'通过' if stats['safe'] >= ru.MIN_SAFE_DIRS else '！！不通过'}")

print()
print("provenance:")
for k, v in stats["provenance"].items():
    print(f"  {k:<20} v{v.get('version')} / {v.get('entries')} 条 / "
          f"{v.get('tier', '-')}")

print()
print("=" * 62)
print("生成的 4 个列表（前几项）")
print("=" * 62)
ns = {}
exec(compile(text, "<rules>", "exec"), ns)
for name in ("THIRD_PARTY_SAFE_DIRS", "THIRD_PARTY_CAUTION_DIRS",
             "THIRD_PARTY_FILE_RULES", "THIRD_PARTY_CAUTION_FILE_RULES"):
    lst = ns.get(name)
    if lst is None:
        print(f"  !! 缺少 {name}")
        continue
    print(f"  {name}  -> {len(lst)} 项")
    for item in lst[:3]:
        print(f"        {item}")

# 直接检查文本里 ExcludeKey 的痕迹
print()
print("=" * 62)
print("文本大小")
print("=" * 62)
print(f"  {len(text):,} 字符 / {len(text.encode('utf-8')):,} 字节")
