# -*- coding: utf-8 -*-
r"""文件链夹具：证明 editor_backup 的文件分支不会再删到已安装软件内部的文件。

用真实规则 + 真实 _in_types_deny，只把 expand_paths 指到夹具根。
夹具放在 D:\ 下 —— 不能放 %TEMP%，因为那是在 \AppData\ 底下，
而 \appdata\ 本身就是黑名单串，会让所有路径都被拒（那样测不出东西）。
"""
import os
import shutil
import sys

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 夹具根放在**用户主目录**下，不放仓库、也不放 %TEMP%：
#   · 仓库在「文档」底下，而「文档」是受保护目录 —— 放仓库里的话，
#     每个夹具路径都会被 _safe_target 判成受保护，测出来全是假结论。
#   · %TEMP% 在 \AppData\ 底下，而 \appdata\ 是 _TYPES_DENY_SUBSTR 里的串，
#     会让 scan_types 把所有路径都跳过（filechain 会因此假失败）。
# 主目录根这两条都不沾。设 MAHIRU_FIXTURE_ROOT 可以覆盖。
FIXTURE_ROOT = (os.environ.get("MAHIRU_FIXTURE_ROOT")
                or os.path.join(os.path.expanduser("~"), ".mahiru_fixture"))
sys.path.insert(0, SRC)
from app.core import junk   # noqa: E402

ROOT = FIXTURE_ROOT

# (相对路径, 字节数, 是否应当被扫到)
CASES = [
    ("proj\\keep.BAK",                    100, True),
    ("proj\\deep\\also.BAK",              200, True),
    ("proj\\node_modules\\pkg\\nm.BAK",   300, False),
    ("proj\\app.asar.unpacked\\x\\a.BAK", 400, False),
    ("proj\\resources\\app\\r.BAK",       500, False),
    ("proj\\Lib\\site-packages\\s.BAK",   600, False),
]

if os.path.isdir(ROOT):
    shutil.rmtree(ROOT, ignore_errors=True)
for rel, size, _ in CASES:
    p = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(b"x" * size)

rule = next((r for r in junk.RULES if r.get("key") == "editor_backup"), None)
if rule is None:
    print("!! 找不到 editor_backup 规则")
    sys.exit(1)

print("=" * 68)
print("editor_backup 文件链夹具")
print("=" * 68)
print(f"  types = {rule.get('types')}")
print(f"  kind  = {rule['kind']}   level = {rule['level']}   "
      f"default = {rule['default']}")
print()

# 只把扫描根指到夹具
_real_expand = junk.expand_paths
junk.expand_paths = lambda r: [ROOT]
try:
    out = junk.scan_types(rule)
finally:
    junk.expand_paths = _real_expand

want_files = sum(1 for _, _, ok in CASES if ok)
want_size = sum(sz for _, sz, ok in CASES if ok)

print(f"  应当扫到 {want_files} 个文件 / {want_size} 字节")
print(f"  实际扫到 {out['files']} 个文件 / {out['size']} 字节")
print()

# 逐个文件复核：把「_in_types_deny 判定」和「夹具期望」对齐
print("  逐个文件：")
bad = 0
for rel, size, should_hit in CASES:
    p = os.path.join(ROOT, rel)
    denied = junk._in_types_deny(p)
    matched = junk._match_type(os.path.basename(p), rule.get("types") or [], p)
    would_hit = matched and not denied
    mark = "OK " if would_hit == should_hit else "!! "
    if would_hit != should_hit:
        bad += 1
    why = "黑名单" if denied else ("规则匹配" if matched else "不匹配规则")
    print(f"    [{mark}] {'扫到' if would_hit else '跳过'}  "
          f"期望{'扫到' if should_hit else '跳过'}  ({why})  {rel}")

print()
fail = 0
def check(label, got, want):
    global fail
    ok = got == want
    if not ok:
        fail += 1
    print(f"  [{'ok' if ok else '!!'}] {label}: {got!r}"
          + ("" if ok else f"  (期望 {want!r})"))

check("扫描到的文件数", out["files"], want_files)
check("扫描到的字节数", out["size"], want_size)
check("逐文件判定全部符合预期", bad, 0)
check("规则认为存在命中", out["exists"], True)

shutil.rmtree(ROOT, ignore_errors=True)
print()
print("全部通过" if fail == 0 else f"{fail} 项失败")
sys.exit(1 if fail else 0)
