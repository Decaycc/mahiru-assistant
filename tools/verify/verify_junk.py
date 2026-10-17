# -*- coding: utf-8 -*-
"""验证 junk.py / bridge.py 改动：第 4 条规则注册、档位、本机命中数。"""
import ast
import io
import os
import sys

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SRC)

FAIL = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got!r}"
          f"{'' if ok else f'   期望 {want!r}'}")
    if not ok:
        FAIL.append(label)


for f in ("app/core/junk.py", "app/bridge.py",
          "app/core/rule_update.py"):
    try:
        ast.parse(io.open(os.path.join(SRC, f), encoding="utf-8").read())
        print(f"  [ok] 语法 {f}")
    except SyntaxError as e:
        print(f"  [FAIL] 语法 {f}: {e}")
        FAIL.append(f"syntax {f}")

print()
print("=" * 66)
print("第三方规则：注册情况")
print("=" * 66)

from app.core import junk   # noqa: E402

total = junk.register_third_party_rule()
print(f"  纳入目录总数（含重复计数）: {total}")
print()

KEYS = ("third_party_apps", "third_party_caution", "third_party_logs",
        "third_party_caution_logs")
for key in KEYS:
    r = next((x for x in junk.RULES if x.get("key") == key), None)
    if r is None:
        print(f"  {key}")
        print(f"      本机没有命中路径 → 未注册（正常，装了就命中）")
        continue
    n = len(junk.expand_paths(r))
    print(f"  {key}")
    print(f"      level={r['level']:<8} kind={r['kind']:<9} "
          f"default={r['default']}")
    print(f"      本机命中 {n} 个路径")

print()
print("=" * 66)
print("档位断言")
print("=" * 66)

def get(key):
    return next((x for x in junk.RULES if x.get("key") == key), None)


check("third_party_apps 是 safe 且默认勾选",
      (get("third_party_apps")["level"],
       get("third_party_apps")["default"]), ("safe", True))
check("third_party_caution 默认不勾选",
      get("third_party_caution")["default"], False)
check("third_party_logs 是 safe 且默认勾选",
      (get("third_party_logs")["level"],
       get("third_party_logs")["default"]), ("safe", True))

print()
print("=" * 66)
print("第 4 条规则的注册分支（本机没有匹配目录，用桩数据验证）")
print("=" * 66)

_real = junk._load_third_party
try:
    # 用一个真实存在的临时目录当桩，走真实的 expand_paths
    import tempfile
    probe = tempfile.mkdtemp(prefix="mahiru_caution_")
    junk._load_third_party = lambda: {
        "safe": [], "caution": [], "file_dirs": [],
        "caution_file_dirs": [probe],
    }
    junk.RULES[:] = [r for r in junk.RULES
                     if not r.get("key", "").startswith("third_party")]
    junk._THIRD_PARTY_LOADED = False
    n = junk.register_third_party_rule()
    r = get("third_party_caution_logs")
    check("桩数据下第 4 条规则已注册", r is not None, True)
    if r is not None:
        check("  level = caution", r["level"], "caution")
        check("  default = False（默认不勾）", r["default"], False)
        check("  kind = files", r["kind"], "files")
        check("  paths 命中桩目录", r["paths"], [probe])
    check("返回计入该目录", n, 1)
    import shutil
    shutil.rmtree(probe, ignore_errors=True)
finally:
    junk._load_third_party = _real
    junk._THIRD_PARTY_LOADED = False
    junk.RULES[:] = [x for x in junk.RULES
                     if not x.get("key", "").startswith("third_party")]
    junk.register_third_party_rule()

print()
print("=" * 66)
print("_in_types_deny 回归（文件分支补上的那个洞）")
print("=" * 66)

CASES = [
    (r"D:\dsh\resources\app.asar.unpacked\dsh\node_modules\.bin\x.BAK", True),
    (r"C:\app\resources\app\main\foo.swp", True),
    (r"C:\python\Lib\site-packages\pkg\a~", True),
    (r"C:\Users\me\AppData\Roaming\SomeApp\node_modules\pkg\y.BAK", True),
    (r"D:\proj\src\mine\thing.BAK", False),
    (r"D:\proj\src\mine\a~", False),
]
for path, want in CASES:
    check(f"deny({os.path.basename(path)}) @ {path[:46]}",
          junk._in_types_deny(path), want)

print()
print("=" * 66)
if FAIL:
    print(f"失败 {len(FAIL)} 项：{FAIL}")
    sys.exit(1)
print("全部通过")
