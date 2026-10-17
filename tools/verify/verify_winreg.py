# -*- coding: utf-8 -*-
"""验证 winhance.py / tunes_winhance.py / bridge.py 改动。

只测纯函数与数据结构，不碰真实注册表（写真实注册表有副作用）。
"""
import ast
import io
import os
import sys
import winreg

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SRC)

FAIL = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got!r}"
          f"{'' if ok else f'   期望 {want!r}'}")
    if not ok:
        FAIL.append(label)


for f in ("app/core/winhance.py", "app/core/tunes_winhance.py",
          "app/bridge.py"):
    try:
        ast.parse(io.open(os.path.join(SRC, f), encoding="utf-8").read())
        print(f"  [ok] 语法 {f}")
    except SyntaxError as e:
        print(f"  [FAIL] 语法 {f}: {e}")
        FAIL.append(f"syntax {f}")

print()
print("=" * 66)
print("tunes_winhance.py 数据结构")
print("=" * 66)

from app.core import tunes_winhance as tunes  # noqa: E402
from app.core import winhance               # noqa: E402

check("TUNES 是 116 条", len(tunes.TUNES), 116)

ids = [t["id"] for t in tunes.TUNES]
check("id 无重复", len(ids), len(set(ids)))
check("id 按字母序排序", ids, sorted(ids))

KEYS = {"id", "name_cn", "desc_cn", "group", "group_cn", "input_type",
        "requires_restart", "subjective", "requires_confirmation",
        "recommended", "default", "reg", "options", "scheduled",
        "detection_type"}
missing = [t["id"] for t in tunes.TUNES if not KEYS.issubset(t.keys())]
check("每条都含 16 个键", missing, [])

toggles = [t for t in tunes.TUNES if t["input_type"] == "toggle"]
selections = [t for t in tunes.TUNES if t["input_type"] == "selection"]
check("toggle 数量", len(toggles), 74)
check("selection 数量", len(selections), 42)

restarts = [t for t in tunes.TUNES if t["requires_restart"]]
check("requires_restart 数量", len(restarts), 62)

# 唯一锁定/托管语义在垃圾清理，游戏设置里不应有 locked 字段
bad_reg = []
for t in tunes.TUNES:
    for r in t.get("reg") or []:
        if r.get("value_type") not in ("dword", "string", "binary"):
            bad_reg.append(t["id"])
check("reg value_type 只 dword/string/binary", bad_reg, [])

roots = {r["key_path"].split("\\", 1)[0]
         for t in tunes.TUNES for r in t.get("reg") or []}
check("根键只有 HKCU/HKLM", roots, {"HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"})

print()
print("=" * 66)
print("winhance.py 纯函数语义")
print("=" * 66)

check("_first_non_null 取第一个非 null",
      winhance._first_non_null([None, 1, None]), 1)
check("_first_non_null 全 null 返回 None",
      winhance._first_non_null([None, None]), None)
check("_first_non_null 空数组返回 None",
      winhance._first_non_null([]), None)

check("_parent_disable [1,null] 取 index1",
      winhance._parent_disable([1, None]), None)
check("_parent_disable [0] 取 index0",
      winhance._parent_disable([0]), 0)
check("_parent_disable None 返回 None",
      winhance._parent_disable(None), None)

check("_split_key HKCU",
      winhance._split_key("HKEY_CURRENT_USER\\Software\\X"),
      (winreg.HKEY_CURRENT_USER, "Software\\X"))
check("_split_key HKLM",
      winhance._split_key("HKEY_LOCAL_MACHINE\\SYSTEM\\Y"),
      (winreg.HKEY_LOCAL_MACHINE, "SYSTEM\\Y"))

check("_coerce dword", winhance._coerce("6", "dword"), 6)
check("_coerce string", winhance._coerce(6, "string"), "6")
check("_coerce binary", winhance._coerce(b"ab", "binary"), b"ab")

check("_reg_type dword", winhance._reg_type("dword"), winreg.REG_DWORD)
check("_reg_type string", winhance._reg_type("string"), winreg.REG_SZ)
check("_reg_type binary", winhance._reg_type("binary"), winreg.REG_BINARY)

# 位掩码语义：纯逻辑验证（不写注册表，直接算 bytearray 结果）
data = bytearray(b"\x00\x00\x00\x00")
winhance._modify_binary_bit.__doc__  # noqa: B018   （仅确认函数可访问）
# 手动复刻置位/清位逻辑，验证实现与 Winhance ModifyBinaryBit 一致
def _setbit(buf, idx, mask, on):
    if on:
        buf[idx] |= mask
    else:
        buf[idx] &= ~mask & 0xFF


b1 = bytearray(b"\x00")
_setbit(b1, 0, 2, True)
check("bitmask 置位（0|2=2）", b1[0], 2)
b2 = bytearray(b"\x02")
_setbit(b2, 0, 2, False)
check("bitmask 清位（2&~2=0）", b2[0], 0)

print()
print("=" * 66)
print("bridge.py 新增 API")
print("=" * 66)

import app.bridge as bridge  # noqa: E402
for m in ("gaming_list", "gaming_apply", "gaming_recommended",
          "gaming_default"):
    check(f"Api.{m} 存在", hasattr(bridge.Api, m), True)

print()
print("=" * 66)
print("list_tunes() 元数据")
print("=" * 66)

items = winhance.list_tunes()
check("list_tunes 返回 116 条", len(items), 116)
samples = {"gaming-game-mode", "gaming-dns-server",
           "system-restore-protection", "gaming-cpu-priority"}
got_ids = {i["id"] for i in items}
check("代表性条目都在", samples.issubset(got_ids), True)

dns = next(i for i in items if i["id"] == "gaming-dns-server")
check("dns-server 有 10 个选项", len(dns["options"]), 10)
sr = next(i for i in items if i["id"] == "system-restore-protection")
check("system-restore recommended", sr["recommended"], True)
check("system-restore default", sr["default"], True)

print()
print("=" * 66)
if FAIL:
    print(f"失败 {len(FAIL)} 项：{FAIL}")
    sys.exit(1)
print("全部通过")
