# -*- coding: utf-8 -*-
"""回收站功能的端到端验证：走真实的 _clean_worker → clean_rules → delete_path 链。"""
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

FIX = os.path.join(FIXTURE_ROOT, "e2e")
ok_all = True


def chk(label, cond, extra=""):
    global ok_all
    print(("  [OK]   " if cond else "  [FAIL] ") + label + (("  " + extra) if extra else ""))
    if not cond:
        ok_all = False


class FakeJob:
    def __init__(self):
        self.cancel = threading.Event()
        self.lines = []

    def log(self, m):
        self.lines.append(m)

    def set_progress(self, m):
        pass


def make_fixture():
    shutil.rmtree(FIX, ignore_errors=True)
    os.makedirs(os.path.join(FIX, "sub"))
    sizes = {}
    for name, n in (("a.tmp", 1024), ("b.tmp", 2048), ("c.tmp", 4096)):
        p = os.path.join(FIX, name)
        with open(p, "wb") as fh:
            fh.write(b"x" * n)
        sizes[name] = n
    for name, n in (("d.tmp", 10), ("e.tmp", 20)):
        p = os.path.join(FIX, "sub", name)
        with open(p, "wb") as fh:
            fh.write(b"y" * n)
        sizes["sub\\" + name] = n
    return sizes


RULE = {"key": "__e2e__", "name": "e2e 夹具", "kind": "contents",
        "level": "safe", "paths": [FIX], "default": False}

# 用临时配置，别动用户真实配置
real_cfg = junk.CONFIG_PATH
tmpdir = tempfile.mkdtemp(prefix="mahiru_e2e_")
junk.CONFIG_PATH = os.path.join(tmpdir, "cfg.json")

real_rules_by_keys = bridge._rules_by_keys
bridge._rules_by_keys = lambda keys: [RULE]

bin_before = junk.recycle_bin_info()
chk("回收站可访问", bin_before.get("ok") is True, str(bin_before))
print(f"  （回收站起始：{bin_before['items']} 项 / {bin_before['size']} 字节）")

try:
    # ---------------- 1) 直接删除（默认） ----------------
    print()
    print("=" * 68)
    print("1) recycle=False —— 直接删除，必须真的释放空间")
    print("=" * 68)
    make_fixture()
    chk("夹具就位", os.path.isdir(FIX) and len(os.listdir(FIX)) == 4)
    json.dump({}, open(junk.CONFIG_PATH, "w", encoding="utf-8"))
    job = FakeJob()
    res = bridge._clean_worker(job, ["__e2e__"])
    total = 1024 + 2048 + 4096 + 10 + 20
    chk("释放字节数 == 夹具总大小", res.get("freed") == total,
        f"{res.get('freed')} vs {total}")
    chk("没有 recycled", res.get("recycled") == 0, str(res.get("recycled")))
    chk("recycled_bytes 为 0", res.get("recycled_bytes") == 0)
    chk("目录还在但空了", os.path.isdir(FIX) and os.listdir(FIX) == [],
        str(os.listdir(FIX) if os.path.isdir(FIX) else "目录没了"))
    bin_mid = junk.recycle_bin_info()
    chk("回收站条目数没变", bin_mid["items"] == bin_before["items"],
        f"{bin_before['items']} → {bin_mid['items']}")
    chk("日志没有提回收站", not any("回收站" in s and "移入" in s for s in job.lines))

    # ---------------- 2) 移入回收站 ----------------
    print()
    print("=" * 68)
    print("2) recycle=True —— 移入回收站，释放量必须为 0，条目要真进回收站")
    print("=" * 68)
    make_fixture()
    chk("夹具重新就位", len(os.listdir(FIX)) == 4)
    json.dump({"recycle_bin": True}, open(junk.CONFIG_PATH, "w", encoding="utf-8"))
    job2 = FakeJob()
    res2 = bridge._clean_worker(job2, ["__e2e__"])
    chk("释放字节数 == 0（东西还在盘上）", res2.get("freed") == 0,
        str(res2.get("freed")))
    chk("recycled 记下了条目数", res2.get("recycled") == 4,
        str(res2.get("recycled")))
    chk("recycled_bytes 是夹具大小（不是 0）",
        res2.get("recycled_bytes") == total,
        f"{res2.get('recycled_bytes')} vs {total}")
    chk("目录还在但空了", os.path.isdir(FIX) and os.listdir(FIX) == [],
        str(os.listdir(FIX) if os.path.isdir(FIX) else "目录没了"))
    chk("开头的日志说明了不释放空间",
        any("移入回收站" in s and "不会" in s for s in job2.lines))
    chk("结尾的日志点明还没释放",
        any("还没有释放" in s for s in job2.lines))
    bin_after = junk.recycle_bin_info()
    chk("回收站条目数增加了 4", bin_after["items"] == bin_before["items"] + 4,
        f"{bin_before['items']} → {bin_after['items']}")
    chk("回收站字节数增加了夹具大小",
        bin_after["size"] == bin_before["size"] + total,
        f"{bin_before['size']} → {bin_after['size']}（期望 +{total}）")

    # ---------------- 3) 受保护路径绝不能进回收站 ----------------
    print()
    print("=" * 68)
    print("3) 保护路径在 recycle=True 下仍然必须被拒（不能绕开保护）")
    print("=" * 68)
    # 注意：move_to_recycle_bin 自己是**不做**保护检查的（它只是 SHFileOperation
    # 的一层薄封装）。保护校验在 delete_path 里 —— 也正因为它在 delete_path 里，
    # 这里才敢拿系统路径来测：函数会在算体积、调 SHFileOperation **之前**就返回。
    # （以前它不在 delete_path 里，这个测试其实真的把 kernel32.dll 递给了
    #   SHFileOperation，只是 Windows 自己拒绝了才「通过」——
    #   那不是被我们自己的保护挡住的，换台机器就可能真删掉。）
    cases = [
        (r"C:\Windows", "系统目录本身"),
        (r"C:\Windows\System32", "System32 本身"),
        (r"C:\Windows\System32\kernel32.dll", "System32 **里面**的文件"),
        (r"c:\windows\system32\cmd.exe", "换大小写写的同一个文件"),
        (os.path.join(os.environ.get("USERPROFILE", r"C:\Users\me"),
                      "Documents", "重要.docx"), "「文档」里的文件"),
        (os.path.join(os.environ.get("USERPROFILE", r"C:\Users\me"),
                      ".ssh", "id_rsa"), "私钥"),
    ]
    for target, what in cases:
        errs, rec = [], []
        got_ok, got = junk.delete_path(target, errs, recycle=True, recycled=rec)
        chk(f"{what} 被拒（也没进回收站）",
            got_ok is False and got == 0 and rec == [] and bool(errs),
            f"{target} → {errs[:1]}")
        if os.path.exists(target):
            chk(f"{what}：还好好地在磁盘上", True, target)

    # 夹具里不存在的路径：要失败，且不能退化成永久删除
    errors3, rec3 = [], []
    ghost = os.path.join(FIXTURE_ROOT, "never_existed_12345")
    got_ok, got = junk.delete_path(ghost, errors3, recycle=True, recycled=rec3)
    chk("不存在的路径会失败而不是假装成功", got_ok is False, str(got_ok))
    chk("失败时 freed 是 0", got == 0, str(got))
    chk("失败时没记入 recycled", rec3 == [], str(rec3))
    print("  （失败原因：" + (errors3[0][1] if errors3 else "无") + "）")

finally:
    bridge._rules_by_keys = real_rules_by_keys
    junk.CONFIG_PATH = real_cfg
    shutil.rmtree(tmpdir, ignore_errors=True)
    shutil.rmtree(FIXTURE_ROOT, ignore_errors=True)

print()
print("=" * 68)
print("结果：" + ("全部通过" if ok_all else "有失败项，见上面的 [FAIL]"))
print("=" * 68)
print()
print(f"注意：本次测试往回收站里放了 4 项（{total} 字节，都在 D 盘），")
print("      要清掉它们请用程序里的「清空回收站」，或手动还原后删除。")
sys.exit(0 if ok_all else 1)
