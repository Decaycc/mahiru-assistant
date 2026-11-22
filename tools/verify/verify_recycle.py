# -*- coding: utf-8 -*-
"""回收站链路的真实验证：不碰系统盘，只在用户主目录下的 .mahiru_fixture 里造桩。"""
import os
import shutil
import sys
import threading
import ctypes

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

FIX = os.path.join(FIXTURE_ROOT, "rc")
# 夹具在哪个盘，就查哪个盘的回收站 —— 不能写死盘符，
# 否则换台机器夹具落在别的盘上，数出来的是另一个回收站，
# 会得出「条目数没变」这种假结论。
VOL = os.path.splitdrive(os.path.abspath(FIX))[0] + "\\"
ok_all = True


def chk(label, cond, extra=""):
    global ok_all
    print(("  [OK]   " if cond else "  [FAIL] ") + label + (("  " + extra) if extra else ""))
    if not cond:
        ok_all = False


class SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong),
                ("i64Size", ctypes.c_longlong),
                ("i64NumItems", ctypes.c_longlong)]


_junk_shell32 = junk.shell32
_junk_shell32.SHQueryRecycleBinW.argtypes = [ctypes.c_wchar_p,
                                             ctypes.POINTER(SHQUERYRBINFO)]
_junk_shell32.SHQueryRecycleBinW.restype = ctypes.c_long


def bin_count():
    """用 shell 自己的接口数回收站条目。

    不能自己 os.listdir(r"D:\\$Recycle.Bin") —— 那个父目录对普通用户
    不可枚举，listdir 直接 PermissionError，静默返回 0 会得出假结论
    （我第一次就是这么误报的）。
    """
    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
    rc = _junk_shell32.SHQueryRecycleBinW(VOL, ctypes.byref(info))
    if rc != 0:
        return None
    return (info.i64NumItems, info.i64Size)


print("=" * 68)
print("1) move_to_recycle_bin 基本行为")
print("=" * 68)
shutil.rmtree(FIX, ignore_errors=True)
os.makedirs(os.path.join(FIX, "subdir", "nested"), exist_ok=True)
f1 = os.path.join(FIX, "single.txt")
with open(f1, "w", encoding="utf-8") as fh:
    fh.write("x" * 4096)
f2 = os.path.join(FIX, "subdir", "nested", "deep.bin")
with open(f2, "wb") as fh:
    fh.write(b"y" * 2048)

before = bin_count()
errors, recycled = [], []

got = junk.move_to_recycle_bin(f1)
chk("单文件移入回收站返回成功", got[0] is True, str(got))
chk("单文件已从原处消失", not os.path.exists(f1))

ok, freed = junk.delete_path(f2, errors, recycle=True, recycled=recycled)
chk("delete_path(recycle=True) 对文件成功", ok is True)
chk("回收站模式下 freed 必须是 0（没释放空间）", freed == 0, f"got={freed}")
chk("recycled 记录了一条", len(recycled) == 1, str(recycled))
chk("记录的体积正确（2048）", recycled and recycled[0][1] == 2048,
    str(recycled[0][1] if recycled else None))
chk("没有产生错误", not errors, str(errors))

# 整个目录
d = os.path.join(FIX, "subdir")
ok, freed = junk.delete_path(d, errors, recycle=True, recycled=recycled)
chk("delete_path(recycle=True) 对目录成功", ok is True, str(errors))
chk("目录已从原处消失", not os.path.exists(d))
chk("目录也没释放空间", freed == 0)
chk("recycled 累计两条", len(recycled) == 2, str(len(recycled)))

after = bin_count()
chk("回收站条目数确实增加了（shell 接口）",
    before is not None and after is not None and after[0] > before[0],
    f"{before} -> {after}")
chk("回收站占用也涨了（证明确实存了东西）",
    before is not None and after is not None and after[1] > before[1],
    f"{before[1] if before else None} -> {after[1] if after else None}")

print()
print("=" * 68)
print("2) 失败时不偷偷退化成永久删除")
print("=" * 68)
gone = os.path.join(FIX, "does-not-exist.txt")
e2, r2 = [], []
ok, freed = junk.delete_path(gone, e2, recycle=True, recycled=r2)
chk("不存在的路径返回失败", ok is False)
chk("失败被记进 errors", bool(e2), str(e2))
chk("失败的没被记成 recycled", not r2)
chk("释放量 0", freed == 0)

print()
print("=" * 68)
print("3) delete_path 返回类型是元组（旧的 int 用法必须报错）")
print("=" * 68)
probe = os.path.join(FIX, "probe.txt")
os.makedirs(FIX, exist_ok=True)
with open(probe, "w", encoding="utf-8") as fh:
    fh.write("z" * 100)
e3 = []
res = junk.delete_path(probe, e3, recycle=False)
chk("返回二元组", isinstance(res, tuple) and len(res) == 2, repr(res))
chk("真删返回 True", res[0] is True)
chk("真删报出释放 100 字节", res[1] == 100, str(res[1]))
chk("文件确实没了", not os.path.exists(probe))

print()
print("=" * 68)
print("4) clean_rule 端到端（recycle=True，桩目录 + 桩规则）")
print("=" * 68)
stub = os.path.join(FIX, "rule_stub")
os.makedirs(stub, exist_ok=True)
for i in range(3):
    with open(os.path.join(stub, f"a{i}.tmp"), "w", encoding="utf-8") as fh:
        fh.write("q" * 512)

real_expand = junk.expand_paths
junk.expand_paths = lambda rule: [stub]
try:
    rule = {"key": "__stub__", "name": "桩规则", "kind": "contents",
            "level": "safe", "paths": [stub], "default": True}
    cancel = threading.Event()
    rep = junk.clean_rule(rule, cancel, progress=None, recycle=True)
finally:
    junk.expand_paths = real_expand

chk("report 有 recycled 字段", "recycled" in rep, str(sorted(rep)))
chk("report 有 recycled_bytes 字段", "recycled_bytes" in rep)
chk("移入回收站 3 项", rep["recycled"] == 3, str(rep["recycled"]))
chk("recycled_bytes = 1536", rep["recycled_bytes"] == 1536, str(rep["recycled_bytes"]))
chk("freed 保持 0", rep["freed"] == 0, str(rep["freed"]))
chk("deleted 计到 3", rep["deleted"] == 3, str(rep["deleted"]))
chk("桩目录已空/消失", not os.path.isdir(stub) or not os.listdir(stub))
chk("没有失败项", not rep["failed"], str(rep["failed"][:2]))

print()
print("=" * 68)
print("5) clean_rules 透传 recycle")
print("=" * 68)
stub2 = os.path.join(FIX, "rule_stub2")
os.makedirs(stub2, exist_ok=True)
with open(os.path.join(stub2, "b.tmp"), "w", encoding="utf-8") as fh:
    fh.write("w" * 256)

junk.expand_paths = lambda rule: [stub2]
try:
    rule2 = {"key": "__stub2__", "name": "桩规则2", "kind": "contents",
             "level": "safe", "paths": [stub2], "default": True}
    logs = []
    tot = junk.clean_rules([rule2], threading.Event(), log=logs.append,
                           recycle=True)
finally:
    junk.expand_paths = real_expand

chk("total 有 recycled", tot.get("recycled") == 1, str(tot.get("recycled")))
chk("total recycled_bytes = 256", tot.get("recycled_bytes") == 256,
    str(tot.get("recycled_bytes")))
chk("日志说明了没释放空间",
    any("回收站" in s and "未释放" in s for s in logs), "\n     ".join(logs))

print()
shutil.rmtree(FIX, ignore_errors=True)
print("=" * 68)
print("结果：" + ("全部通过" if ok_all else "有失败项，见上面的 [FAIL]"))
print("=" * 68)
sys.exit(0 if ok_all else 1)
