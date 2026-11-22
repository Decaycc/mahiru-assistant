# -*- coding: utf-8 -*-
"""对真实的 MultronWcleaner 数据库跑一遍，看实际能收多少。"""
import os
import sys
from collections import Counter

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SRC)
from app.core import rule_update as ru   # noqa: E402

text, note = ru.fetch_multron(force=False, log=lambda m: print("  " + m))
print(f"  说明：{note}")
if not text:
    print("!! 没拿到，退出")
    sys.exit(1)

lines = text.splitlines()
print(f"  行数 {len(lines)} / 字符 {len(text)}")
print()

counters = Counter()
caution = {}
ru.parse_multron(text, counters, caution)

print("=" * 70)
print("真实数据解析结果")
print("=" * 70)
total = counters["Multron 条目总数"]
for k, v in counters.most_common():
    pct = f"  ({v * 100 // total}%)" if total and "总数" not in k else ""
    print(f"    {k:<30} {v:>5}{pct}")

print()
print(f"  收录进谨慎档的目录模板：{len(caution)} 条")
print()
print("  前 25 条：")
for t in sorted(caution)[:25]:
    print(f"    {t}")
print()
print("  末 10 条：")
for t in sorted(caution)[-10:]:
    print(f"    {t}")

# 本机实际存在的
import os                                            # noqa: E402
from app.core.junk import _expand_template           # noqa: E402
real = []
for t in caution:
    r = _expand_template(t)
    if r and "{" not in r and "*" not in r and os.path.isdir(r):
        real.append(r)
print()
print(f"  其中在本机真实存在的目录：{len(real)} 个")
for r in real[:20]:
    print(f"    {r}")
