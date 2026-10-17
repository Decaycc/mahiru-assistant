# -*- coding: utf-8 -*-
"""ExcludeKey 行为验证：合成用例 + 真实文件的账。

注意排错记录：目录规则必须用 FileKey 的 files 段为空或 "*"，
写成 "*.*" 会走「按模式清理」的文件规则分支（THIRD_PARTY_FILE_RULES），
不进 THIRD_PARTY_SAFE_DIRS —— 第一版测试就是这么写错的。
"""
import os
import sys
from collections import Counter

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SRC)

from app.core import rule_update as ru   # noqa: E402

# 真实文件直接走程序自己的取数路径（从 config/rule_cache 的 tarball 里解出来）。
# 以前这里指向 config/rule_cache/wa2/，那是 tools/_probe_unpack.py 造出来的
# 中间目录 —— 探针脚本一删，这段就静默取不到文件了。
INIS, _INI_NOTE = ru.fetch_winapp_ini_files(offline=True)
FILE_LABELS = [
    ("winapp2", "Winapp2.ini"),
    ("winapp3", "Winapp3.ini"),
    ("winapp3_archived", "Archived entries.ini"),
]

FAIL = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got!r}"
          f"{'' if ok else f'   期望 {want!r}'}")
    if not ok:
        FAIL.append(label)


DIR_SECTION = """
[Excluded App*]
FileKey1=%LocalAppData%\\ExApp\\Cache|*
ExcludeKey1=PATH|%LocalAppData%\\ExApp\\Cache\\keep\\*|*

[Kept App*]
FileKey1=%LocalAppData%\\KeepApp\\Cache|*
ExcludeKey1=PATH|%LocalAppData%\\TotallyOther\\*|*
"""

print("=" * 66)
print("A. 合成用例")
print("=" * 66)

c, safe, caut, fr = Counter(), {}, {}, {}
ru.parse_ini(DIR_SECTION, c, safe, caut, fr)
keys = [k.lower() for k in safe]
check("排除项命中 -> 整条丢弃", c["上游写了排除项(丢弃)"], 1)
check("ExcludeKey 读到计数", c["ExcludeKey 读到"], 2)
check("排除项不命中 -> 保留", c["安全-整目录"], 1)
check("留下的是 KeepApp", any("keepapp" in k for k in keys), True)
check("ExApp 已被丢弃", any("exapp" in k for k in keys), False)

# A2: FILE 类型排除，指向模板内的具体文件
c2, s2 = Counter(), {}
ru.parse_ini("""
[FileExcl App*]
FileKey1=%LocalAppData%\\FApp\\Logs|*
ExcludeKey1=FILE|%LocalAppData%\\FApp\\Logs\\important.log|*
""", c2, s2, {}, {})
check("FILE 型排除 -> 丢弃", c2["上游写了排除项(丢弃)"], 1)
check("FILE 型排除后无残留", len(s2), 0)

# A3: REG 类型排除必须被忽略（本项目不碰注册表，不能因它误伤文件规则）
c3, s3 = Counter(), {}
ru.parse_ini("""
[RegExcl App*]
FileKey1=%LocalAppData%\\RApp\\Cache|*
ExcludeKey1=REG|HKCU\\Software\\RApp|*
""", c3, s3, {}, {})
check("REG 型排除被跳过（不误伤）", c3["安全-整目录"], 1)
check("REG 型不计入 读到", c3["ExcludeKey 读到"], 0)

# A4: tier=caution 强制降档（Archived 整份降级的机制）
c4, s4, caut4, fr4, cf4 = Counter(), {}, {}, {}, {}
ru.parse_ini(DIR_SECTION, c4, s4, caut4, fr4, tier="caution",
             caution_files=cf4)
check("tier=caution 不进 safe", len(s4), 0)
check("tier=caution 进 caution", len(caut4), 1)

# A5: 大小写 / 反斜杠归一化 —— 排除项写成正斜杠也要拦住
c5, s5 = Counter(), {}
ru.parse_ini("""
[Slash App*]
FileKey1=%LocalAppData%\\SApp\\Cache|*
ExcludeKey1=PATH|%LocalAppData%/SApp/Cache/sub|*
""", c5, s5, {}, {})
check("正斜杠排除项也拦住", c5["上游写了排除项(丢弃)"], 1)

print()
print("=" * 66)
print("B. 真实文件：ExcludeKey 都去哪了")
print("=" * 66)

tot_all = tot_denied = tot_read = 0
if not INIS:
    print("  !! 没有 tarball 缓存，跳过真实文件的核对。")
    print("     先在设置页点一次「检查并更新」，或跑 "
          "python run.py --update-rules，再来。")
for key, label in FILE_LABELS:
    if key not in INIS:
        continue
    text = INIS[key][0].decode("utf-8", errors="replace")
    total_lines = sum(1 for ln in text.splitlines()
                      if ru._EXCLUDE_RE.match(ln.strip()))
    denied_n = kept_n = 0
    for name, body in ru.iter_sections(text):
        n = len(ru._section_excludes(body))
        if not n:
            continue
        if ru.denied(name):
            denied_n += n
        else:
            kept_n += n
    tot_all += total_lines
    tot_denied += denied_n
    tot_read += kept_n
    print(f"  {label:<24} 总 {total_lines:>5}   隐私跳过 {denied_n:>5}"
          f"   实际读取 {kept_n:>5}")
print(f"  {'合计':<24} 总 {tot_all:>5}   隐私跳过 {tot_denied:>5}"
      f"   实际读取 {tot_read:>5}")

print()
print("=" * 66)
if FAIL:
    print(f"失败 {len(FAIL)} 项：{FAIL}")
    sys.exit(1)
print("全部通过")
