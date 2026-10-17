# -*- coding: utf-8 -*-
"""回收站可用性预检的验证。

重点验的不是「能不能移进去」，而是**该卷回收站不可用时绝不能静默永久删除** ——
FOF_ALLOWUNDO 在这种情况下会直接永久删掉而且返回成功，用户的文件就没了。
"""
import json
import os
import shutil
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 夹具根放在**用户主目录**下，不放仓库、也不放 %TEMP%：
#   · 仓库在「文档」底下，而「文档」是受保护目录 —— 放仓库里的话，
#     每个夹具路径都会被 _safe_target 判成受保护，测出来全是假结论。
#   · %TEMP% 在 \AppData\ 底下，而 \appdata\ 是 _TYPES_DENY_SUBSTR 里的串，
#     会让 scan_types 把所有路径都跳过（filechain 会因此假失败）。
# 主目录根这两条都不沾。设 MAHIRU_FIXTURE_ROOT 可以覆盖。
FIXTURE_ROOT = (os.environ.get("MAHIRU_FIXTURE_ROOT")
                or os.path.join(os.path.expanduser("~"), ".mahiru_fixture"))
sys.path.insert(0, ROOT)

from app.core import junk                                    # noqa: E402
from app import bridge                                        # noqa: E402

FIX = os.path.join(FIXTURE_ROOT, "guard")
# 夹具在哪个盘，就查哪个盘 —— 不写死盘符，否则换台机器夹具落在别的盘上，
# 冒充「这个盘的回收站被关掉」就冒充错了对象。
MOUNT = os.path.splitdrive(os.path.abspath(FIX))[0] + "\\"
ok_all = True


def chk(label, cond, extra=""):
    global ok_all
    print(("  [OK]   " if cond else "  [FAIL] ") + label + (("  " + extra) if extra else ""))
    if not cond:
        ok_all = False


def reset_cache():
    junk._RECYCLE_VOL_CACHE.clear()


# ---------------------------------------------------------------- 假注册表
class _Key:
    def __init__(self, vals):
        self.vals = vals

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"

    def __init__(self, vals):
        self.vals = vals          # {子键: {值名: 值}}

    def OpenKey(self, root, sub):
        if sub in self.vals:
            return _Key(self.vals[sub])
        raise OSError(2, "系统找不到指定的文件")

    def QueryValueEx(self, key, name):
        if name in key.vals:
            return key.vals[name], 4          # REG_DWORD
        raise OSError(2, "系统找不到指定的值")


BASE = r"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket"
VOL = BASE + r"\Volume\{FAKE-GUID}"

real_winreg_fn = junk._winreg
real_guid = junk._volume_guid
fake = {"current": None}


def use_reg(vals):
    """把 junk 的注册表读取换成假实现。"""
    fw = FakeWinreg(vals)
    fake["current"] = fw
    junk._winreg = lambda: fw

try:
    print("=" * 68)
    print("1) 本机真实情况：夹具所在盘应当可用")
    print("=" * 68)
    reset_cache()
    usable, cap, why = junk._volume_recycle_status(MOUNT)
    chk(f"{MOUNT} 回收站可用", usable is True, f"cap={cap} MB, why={why!r}")
    chk("容量上限是个正数", cap > 0, str(cap))
    chk("普通路径检查通过", junk.recycle_bin_check(FIX, 1024) == "",
        repr(junk.recycle_bin_check(FIX, 1024)))

    print()
    print("=" * 68)
    print("2) 各种「回收站不可用」的设置都必须被识破")
    print("=" * 68)
    junk._volume_guid = lambda m: "{FAKE-GUID}"

    cases = [
        ("该卷单独设了 NukeOnDelete=1", {VOL: {"NukeOnDelete": 1}}, False, 0, "关掉"),
        ("该卷 MaxCapacity=0（禁用）",
         {VOL: {"NukeOnDelete": 0, "MaxCapacity": 0}}, False, 0, "容量是 0"),
        ("该卷没设、全局 NukeOnDelete=1",
         {BASE: {"NukeOnDelete": 1}}, False, 0, "关掉"),
        ("该卷可用，上限 1000MB",
         {VOL: {"NukeOnDelete": 0, "MaxCapacity": 1000}}, True, 1000, ""),
        ("该卷允许、但 MaxCapacity=10MB 装不下 20MB",
         {VOL: {"NukeOnDelete": 0, "MaxCapacity": 10}}, True, 10, "超过"),
    ]
    for label, vals, want_usable, want_cap, want_word in cases:
        reset_cache()
        use_reg(vals)
        u, c, w = junk._volume_recycle_status(MOUNT)
        msg = junk.recycle_bin_check(FIX, 20 * 1048576)
        ok = (u is want_usable) and (c == want_cap) and (want_word in (w or msg))
        chk(label, ok, f"usable={u} cap={c} why={w!r} check={msg!r}")

    # 什么都没设 → 跟随默认（启用），容量按卷容量 5% 估算
    reset_cache()
    use_reg({})
    u, c, w = junk._volume_recycle_status(MOUNT)
    chk("什么都没设 → 默认启用，容量按 5% 估算", u is True and c > 0,
        f"usable={u} cap={c} MB")

    # 没有 $Recycle.Bin 的卷
    free = [f"{ch}:\\" for ch in "ZYXWVU" if not os.path.exists(f"{ch}:\\")]
    if free:
        reset_cache()
        use_reg({})
        u, c, w = junk._volume_recycle_status(free[0])
        chk(f"没有 $Recycle.Bin 的卷（{free[0]}）被拒", u is False and "没有回收站" in w,
            repr(w))
    else:
        print("  （找不到空闲盘符，跳过这一项）")

    print()
    print("=" * 68)
    print("3) 关键：预检不过时**原文件必须还在**（不能静默永久删除）")
    print("=" * 68)
    junk._winreg = real_winreg_fn
    junk._volume_guid = real_guid
    reset_cache()

    shutil.rmtree(FIX, ignore_errors=True)
    os.makedirs(os.path.join(FIX, "sub"))
    for n, sz in (("a.tmp", 111), ("b.tmp", 222)):
        with open(os.path.join(FIX, n), "wb") as fh:
            fh.write(b"x" * sz)
    with open(os.path.join(FIX, "sub", "c.tmp"), "wb") as fh:
        fh.write(b"y" * 333)
    before = sorted(os.listdir(FIX))
    chk("夹具就位", before == ["a.tmp", "b.tmp", "sub"], str(before))

    # 冒充「夹具所在盘的回收站被关掉」
    real_status = junk._volume_recycle_status
    junk._RECYCLE_VOL_CACHE[MOUNT] = (
        False, 0, "测试冒充：系统设置里关掉了回收站（删除即永久删除）")

    errors, rec = [], []
    got_ok, got = junk.delete_path(os.path.join(FIX, "a.tmp"), errors,
                                   recycle=True, recycled=rec)
    chk("delete_path 返回失败", got_ok is False, str(got_ok))
    chk("释放量是 0", got == 0, str(got))
    chk("没记入 recycled", rec == [], str(rec))
    chk("错误消息说明不会改成永久删除",
        bool(errors) and "不会改成永久删除" in errors[0][1], str(errors[:1]))
    chk("★ a.tmp 还在磁盘上★", os.path.isfile(os.path.join(FIX, "a.tmp")))

    # 走完整的 clean_rule：一个文件都不许少
    rule = {"key": "__g__", "name": "guard", "kind": "contents",
            "level": "safe", "paths": [FIX], "default": False}
    rep = junk.clean_rule(rule, recycle=True)
    chk("clean_rule：freed 为 0", rep["freed"] == 0, str(rep["freed"]))
    chk("clean_rule：recycled 为 0", rep["recycled"] == 0, str(rep["recycled"]))
    chk("clean_rule：deleted 为 0", rep["deleted"] == 0, str(rep["deleted"]))
    after = sorted(os.listdir(FIX))
    chk("★ 整个夹具一个文件都没少★", after == before, str(after))
    chk("★ 子目录里的文件也在★", os.path.isfile(os.path.join(FIX, "sub", "c.tmp")))
    chk("失败原因被记下来了", len(rep["failed"]) >= 1, str(rep["failed"][:1]))

    # 恢复之后应当又能正常移入回收站
    junk._RECYCLE_VOL_CACHE.clear()
    errors2, rec2 = [], []
    got_ok, got = junk.delete_path(os.path.join(FIX, "b.tmp"), errors2,
                                   recycle=True, recycled=rec2)
    chk("恢复设置后又能移入回收站", got_ok is True, str(errors2[:1]))
    chk("释放量仍是 0", got == 0)
    chk("recycled 记了 1 项", len(rec2) == 1, str(rec2))
    chk("b.tmp 已从原处消失", not os.path.exists(os.path.join(FIX, "b.tmp")))

finally:
    junk._winreg = real_winreg_fn
    junk._volume_guid = real_guid
    junk._RECYCLE_VOL_CACHE.clear()
    shutil.rmtree(FIXTURE_ROOT, ignore_errors=True)

print()
print("=" * 68)
print("结果：" + ("全部通过" if ok_all else "有失败项，见上面的 [FAIL]"))
print("=" * 68)
sys.exit(0 if ok_all else 1)
