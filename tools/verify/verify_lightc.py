# -*- coding: utf-8 -*-
"""验证 LightC 规则移植：18 条规则、档位映射、locked 语义、覆盖去重、白名单。"""
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


for f in ("app/core/rules_lightc.py", "app/core/junk.py", "app/bridge.py"):
    try:
        ast.parse(io.open(os.path.join(SRC, f), encoding="utf-8").read())
        print(f"  [ok] 语法 {f}")
    except SyntaxError as e:
        print(f"  [FAIL] 语法 {f}: {e}")
        FAIL.append(f"syntax {f}")

print()
print("=" * 66)
print("LightC 规则：数量与 key 前缀")
print("=" * 66)

from app.core import junk          # noqa: E402
from app.core import rules_lightc  # noqa: E402

check("LIGHTC_RULES 共 18 条", len(rules_lightc.LIGHTC_RULES), 18)
check("lightc_keys() 共 18 条", len(rules_lightc.lightc_keys()), 18)
check("全部 key 带 lightc_ 前缀",
      all(k.startswith("lightc_") for k in rules_lightc.lightc_keys()), True)
check("key 无重复",
      len(set(rules_lightc.lightc_keys())),
      len(rules_lightc.lightc_keys()))

print()
print("=" * 66)
print("档位映射（risk 1/2/3 → safe/caution/risky）")
print("=" * 66)

_risk_map = {
    "lightc_windows_temp": "safe",
    "lightc_thumbnail_cache": "safe",
    "lightc_font_cache": "safe",
    "lightc_clipboard_cache": "safe",
    "lightc_shader_cache": "safe",
    "lightc_browser_cache": "caution",
    "lightc_windows_update": "caution",
    "lightc_delivery_optimization": "caution",
    "lightc_windows_defender_cache": "caution",
    "lightc_log_files": "caution",
    "lightc_windows_error_reports": "caution",
    "lightc_installer_temp": "caution",
    "lightc_third_party_app_cache": "caution",
    "lightc_recycle_bin": "risky",
    "lightc_system_cache": "risky",
    "lightc_app_cache": "risky",
    "lightc_memory_dump": "risky",
    "lightc_old_windows_installation": "risky",
}
for key, want in _risk_map.items():
    r = next((x for x in rules_lightc.LIGHTC_RULES if x["key"] == key), None)
    check(f"{key} level", r["level"] if r else None, want)

print()
print("=" * 66)
print("default 勾选（risk<=2 勾、risk3 不勾）")
print("=" * 66)

for key, want in _risk_map.items():
    r = next((x for x in rules_lightc.LIGHTC_RULES if x["key"] == key), None)
    expect_default = want in ("safe", "caution")
    check(f"{key} default", r["default"] if r else None, expect_default)

print()
print("=" * 66)
print("locked 语义（仅 OldWindowsInstallation）")
print("=" * 66)

for key in rules_lightc.lightc_keys():
    r = next((x for x in rules_lightc.LIGHTC_RULES if x["key"] == key), None)
    is_old = key == "lightc_old_windows_installation"
    check(f"{key} locked", bool(r.get("locked")), is_old)
    check(f"{key} system_managed", bool(r.get("system_managed")), is_old)

print()
print("=" * 66)
print("特殊 kind 与 patterns")
print("=" * 66)

r = next(x for x in rules_lightc.LIGHTC_RULES
         if x["key"] == "lightc_recycle_bin")
check("recycle_bin kind", r["kind"], "recyclebin")

r = next(x for x in rules_lightc.LIGHTC_RULES
         if x["key"] == "lightc_memory_dump")
check("memory_dump kind", r["kind"], "files")
check("memory_dump patterns", list(r["patterns"]), ["*.dmp"])
check("memory_dump 不含 MEMORY.DMP（委托内置）",
      "MEMORY.DMP" in list(r["patterns"]), False)

print()
print("=" * 66)
print("覆盖去重：内置 18 key 已移除、保留项仍在")
print("=" * 66)

REPLACED = {
    "user_temp", "win_temp", "prefetch", "font_cache",
    "edge_cache", "chrome_cache", "inetcache", "d3d_cache",
    "thumb_cache", "crash_dumps", "wer_reports", "minidump",
    "cbs_logs", "wu_download", "delivery_opt", "recyclebin",
    "esd_files", "windows_old",
}
PRESERVED = {
    "memory_dmp", "search_index", "edge_tmp", "webview_cache",
    "ie_legacy", "app_caches", "installer_logs",
}

junk_keys = {x.get("key") for x in junk.RULES}
for key in REPLACED:
    check(f"内置 {key} 已移除", key in junk_keys, False)
for key in PRESERVED:
    check(f"内置 {key} 保留", key in junk_keys, True)
for key in rules_lightc.lightc_keys():
    check(f"LightC {key} 已注册进 RULES", key in junk_keys, True)

print()
print("=" * 66)
print("System32\\d3d_cache 白名单（_safe_target 放行）")
print("=" * 66)

d3d = os.path.normcase(os.path.abspath(
    junk._join(junk.WINDIR, "System32", "d3d_cache")))
check("_safe_target(d3d_cache 本身)", junk._safe_target(d3d), True)
check("_safe_target(d3d_cache 子项)", junk._safe_target(os.path.join(d3d, "x")), True)
# System32 其它路径仍应被保护
sys32 = os.path.normcase(os.path.abspath(
    junk._join(junk.WINDIR, "System32")))
check("_safe_target(System32 其它) 仍拒删",
      junk._safe_target(os.path.join(sys32, "config")), False)
# 仿冒目录（不在 System32 下）不应放行
fake = os.path.normcase(os.path.abspath(
    junk._join(junk.WINDIR, "System32", "d3d_cache_evil")))
check("仿冒 d3d_cache_evil 不放行", junk._safe_target(fake), False)

print()
print("=" * 66)
if FAIL:
    print(f"失败 {len(FAIL)} 项：{FAIL}")
    sys.exit(1)
print("全部通过")
