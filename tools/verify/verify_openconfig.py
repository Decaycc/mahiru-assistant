# -*- coding: utf-8 -*-
"""验证 open_in_explorer 的代号解析（不真的开资源管理器）。"""
import os
import sys

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SRC)

opened = []
_real = os.startfile
os.startfile = lambda p: opened.append(p)          # noqa: A001

from app.bridge import Api                          # noqa: E402
from app.paths import config_dir                    # noqa: E402

api = Api(None)      # open_in_explorer 不用 jobs
fail = 0
def check(label, got, want):
    global fail
    ok = got == want
    if not ok:
        fail += 1
    print(f"  [{'ok' if ok else '!!'}] {label}: {got!r}"
          + ("" if ok else f"  (期望 {want!r})"))

print("=" * 66)
print("open_in_explorer")
print("=" * 66)
print(f"  config_dir() = {config_dir()}")

r = api.open_in_explorer("config")
check("代号 config 成功", r.get("ok"), True)
check("  解析到配置目录", os.path.normcase(r.get("path", "")),
      os.path.normcase(config_dir()))
check("  真的调用了 startfile", opened[-1:] and
      os.path.normcase(opened[-1]) == os.path.normcase(config_dir()), True)

r2 = api.open_in_explorer("CONFIG")
check("代号大小写不敏感", r2.get("ok"), True)

r3 = api.open_in_explorer("绝对路径不存在")
check("不存在的路径被拒", r3.get("ok"), False)
check("  报错里带上了实际路径", "绝对路径不存在" in r3.get("error", "")
      or "不存在" in r3.get("error", ""), True)

r4 = api.open_in_explorer(str(SRC))
check("绝对路径仍然可用", r4.get("ok"), True)

os.startfile = _real
print()
print("全部通过" if fail == 0 else f"{fail} 项失败")
sys.exit(1 if fail else 0)
