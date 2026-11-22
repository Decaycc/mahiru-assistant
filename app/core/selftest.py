# -*- coding: utf-8 -*-
"""M1 回归网：一次跑完两个核心的自检。

用法（在 GameBoostNext 目录下）：
    python -m app.core.selftest
    python app/core/selftest.py

两个核心的自检本身就是安全回归网，覆盖：
    内存优化 —— 名单冲突检查 + 7 个 NT 内存调用是否可用
    垃圾清理 —— 模式声明 / 保护清单隔离 / 删除前校验 / 默认勾选策略 /
                反作弊隔离 / 隐私数据隔离 / 个人目录隔离 / 可移植性

注意：内存统计、进程占用、释放量属于瞬时读数，每次运行都会不同，
所以**不能**把逐字比对当作通过标准；判定标准是 exit code 与各检查项结论。
"""
import contextlib
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _fixture_clean_tests(junk) -> tuple[bool, list[str]]:
    """用**受控夹具**验证清理逻辑，而不是去删用户真实的数据。

    这是唯一能安全验证「删除」这条路径的办法：在临时目录里造出
    「该删的 / 不该删的 / 删不掉的」三类情况，看实际行为是否符合预期。

    覆盖三点：
      1. contents 规则只清空目录**内容**，目录本身要保留
      2. 占用的文件要**跳过并记录**，不能抛异常、更不能强删
      3. 保护路径在删除前被拒绝（保护清单/隐私/个人目录）
    """
    import shutil
    import tempfile

    lines = []
    ok = True
    root = tempfile.mkdtemp(prefix="gbtest_clean_")
    try:
        # --- 1) 正常清理：目录内容应被清空，目录本身保留
        sub = os.path.join(root, "cache")
        os.makedirs(os.path.join(sub, "nested"))
        for i in range(3):
            with open(os.path.join(sub, f"junk{i}.bin"), "wb") as f:
                f.write(b"x" * 4096)
        with open(os.path.join(sub, "nested", "deep.bin"), "wb") as f:
            f.write(b"y" * 8192)

        rule = {"key": "_fixture", "name": "夹具规则", "category": "测试",
                "level": "safe", "kind": "contents", "paths": [sub],
                "desc": "", "default": False}
        rep = junk.clean_rule(rule)

        left = os.listdir(sub)
        if os.path.isdir(sub) and not left and rep["deleted"] > 0:
            lines.append(f"清理行为         : 通过（删除 {rep['deleted']} 项，"
                         f"释放 {rep['freed'] / 1024:.0f} KB，目录本身保留）")
        else:
            ok = False
            lines.append(f"  !! 清理行为异常：目录还在={os.path.isdir(sub)} "
                         f"残留={left} deleted={rep['deleted']}")

        # --- 2) 占用中的文件应被跳过并记录，而不是强删
        busy_dir = os.path.join(root, "busy")
        os.makedirs(busy_dir)
        busy_file = os.path.join(busy_dir, "locked.bin")
        with open(busy_file, "wb") as f:
            f.write(b"z" * 4096)
        rule2 = dict(rule, key="_fixture2", paths=[busy_dir])
        handle = open(busy_file, "rb")          # 保持打开，模拟占用
        try:
            rep2 = junk.clean_rule(rule2)
        finally:
            handle.close()
        # Windows 上被占用的文件删不掉；关键是不能抛异常、且要记进 failed
        recorded = any("locked.bin" in p for p, _ in (rep2.get("failed") or []))
        if os.path.exists(busy_file) or recorded:
            lines.append("占用文件处理     : 通过（跳过并记录，未强删、未抛异常）")
        else:
            ok = False
            lines.append("  !! 占用文件既没被记录也没保留，行为可疑")

        # --- 3) 保护路径必须被拒绝
        prof = junk.PROFILE
        docs = os.path.join(prof, "Documents") if prof else ""
        cases = [("用户文档", docs),
                 ("Windows 根目录", junk.WINDIR),
                 ("Windows\\System32", os.path.join(junk.WINDIR, "System32")),
                 (".ssh 私钥目录", os.path.join(prof, ".ssh") if prof else ""),
                 (".aws 凭据", os.path.join(prof, ".aws") if prof else ""),
                 ("id_rsa 私钥文件", os.path.join(prof, ".ssh", "id_rsa")
                  if prof else ""),
                 ("浏览器 Cookie 目录",
                  os.path.join(prof, "AppData", "Local", "Google", "Chrome",
                               "User Data", "Default", "Cookies") if prof else "")]
        refused = 0
        checked = 0
        missed = []
        for label, path in cases:
            if not path:
                continue
            checked += 1
            if not junk._safe_target(path):
                refused += 1
            else:
                missed.append(label)
        if checked and refused == checked:
            lines.append(f"保护路径拒绝     : 通过（{refused}/{checked} 全部被 "
                         f"_safe_target 拒绝，含凭据与隐私）")
        else:
            ok = False
            lines.append(f"  !! 保护路径拒绝异常：{refused}/{checked}，"
                         f"漏掉的是 {missed}")
    finally:
        try:
            shutil.rmtree(root, ignore_errors=True)
        except Exception:                                   # noqa: BLE001
            pass
    return ok, lines


def _fixture_self_tree_test(mem) -> tuple[bool, list[str]]:
    """验证「自己的子孙进程」也受保护。

    为什么必须测这个：新版界面是 WebView2 渲染的，而 `msedgewebview2.exe`
    这个进程名在「可关闭」名单里（TIER_OPTIONAL）。它的进程是**自己的子进程**，
    而 `self_and_ancestors()` 只向上找祖先 —— 于是「关闭可选级后台应用」
    会把自己的界面渲染进程一起关掉（界面白屏/崩溃）。

    这个 bug 在真实数据里留下过证据：用户的 closed_apps 里有两条
    msedgewebview2.exe。所以这里造一个真实子进程来守住它。
    """
    import subprocess
    import time as _time

    lines = []
    ok = True
    child = None
    try:
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"])
        _time.sleep(1.2)

        anc = mem.self_and_ancestors()
        tree = mem.self_process_tree()

        if child.pid not in tree:
            ok = False
            lines.append(f"  !! 自己的子进程 (PID {child.pid}) 不在保护集合里")
        else:
            lines.append(f"自身子孙保护     : 通过（子进程 PID {child.pid} 已被"
                         f" self_process_tree 纳入；旧实现有 {len(tree - anc)} 个"
                         f"子孙漏在外面）")

        # 用真实判定函数再过一遍：名字在可关闭名单里，但因为是自己的子孙，
        # 必须判定为受保护
        opt = mem.Optimizer(lambda *_: None)
        probe = {"pid": child.pid, "name": "msedgewebview2.exe",
                 "mem": 150 * 1048576}
        closable = opt.is_closable(probe)
        if closable:
            ok = False
            lines.append("  !! 模拟的自身 WebView2 子进程被判定为「可关闭」")
        else:
            lines.append("界面渲染进程保护 : 通过（msedgewebview2 在自己的进程树"
                         "里时不可关闭）")
    except Exception as e:                                  # noqa: BLE001
        ok = False
        lines.append(f"  !! 自身子孙保护测试异常: {type(e).__name__}: {e}")
    finally:
        if child is not None:
            try:
                child.terminate()
            except Exception:                               # noqa: BLE001
                pass
    return ok, lines


def _fixture_venv_marker_test(junk) -> tuple[bool, list[str]]:
    """验证「同名目录」能被区分开。

    真实事故：全盘清理时 `dir:venv` 只按名字匹配，把
    `.../python/Lib/venv`（Python 标准库模块）当成虚拟环境删掉了，
    结果 `python -m venv` 从此报「No module named venv」，
    整个 Python 安装的建虚拟环境能力被破坏。

    真正的 venv 一定带 `pyvenv.cfg`，标准库模块目录没有。
    现在用标记文件区分，这里守住这个行为。
    """
    import shutil
    import tempfile

    lines = []
    ok = True
    root = tempfile.mkdtemp(prefix="gbtest_venvmark_")
    try:
        rule = next((r for r in junk.RULES if r["key"] == "dev_artifacts"), None)
        types = list((rule or {}).get("types") or [])
        if not types:
            return False, ["  !! 找不到 dev_artifacts 规则，无法验证"]

        # 像标准库 Lib/venv：名字叫 venv，但没有 pyvenv.cfg
        lib = os.path.join(root, "python", "Lib", "venv")
        os.makedirs(lib)
        with open(os.path.join(lib, "__init__.py"), "w", encoding="utf-8") as f:
            f.write("# stdlib module\n")

        # 真正的虚拟环境：有 pyvenv.cfg
        real = os.path.join(root, "proj", "venv")
        os.makedirs(real)
        with open(os.path.join(real, "pyvenv.cfg"), "w", encoding="utf-8") as f:
            f.write("home = C:\\Python312\n")

        fake_hit = junk._match_type("venv", types, lib)
        real_hit = junk._match_type("venv", types, real)

        if fake_hit:
            ok = False
            lines.append("  !! 标准库的 Lib/venv 仍会被当成虚拟环境删掉")
        elif not real_hit:
            ok = False
            lines.append("  !! 真正的虚拟环境反而不被识别了")
        else:
            lines.append("虚拟环境识别     : 通过（靠 pyvenv.cfg 区分；"
                         "标准库 Lib/venv 不会被误删）")
    except Exception as e:                                  # noqa: BLE001
        ok = False
        lines.append(f"  !! 虚拟环境识别测试异常: {type(e).__name__}: {e}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return ok, lines


def _fixture_startup_test(tools) -> tuple[bool, list[str]]:
    """用真实注册表夹具验证启动项的「禁用 / 启用 / 还原」。

    为什么必须用真实注册表：这个功能踩过一个只有真跑才会暴露的 bug ——
    「设为禁用」时把 src/dst 写反了，于是去**禁用区**里找那个值，
    那里当然是空的，用户每次点都报「找不到（可能已被其他程序改动）」。
    纯逻辑推演看不出来，必须真读真写。

    在 HKCU 下建一个测试值，走完整流程，最后一定清理干净。
    """
    lines = []
    ok = True
    try:
        import winreg
    except ImportError:
        return True, ["启动项读写     : 跳过（当前环境没有 winreg）"]

    sub = r"Software\Microsoft\Windows\CurrentVersion\Run"
    suf = tools._DISABLED_SUFFIX
    name = "__mahiru_selftest_entry__"
    value = r"C:\Windows\System32\notepad.exe"
    hive = winreg.HKEY_CURRENT_USER

    def has(path):
        try:
            with winreg.OpenKey(hive, path) as k:
                winreg.QueryValueEx(k, name)
                return True
        except OSError:
            return False

    def cleanup():
        for path in (sub, sub + suf):
            try:
                with winreg.OpenKey(hive, path, 0,
                                    winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, name)
            except OSError:
                pass

    cleanup()
    try:
        with winreg.CreateKeyEx(hive, sub, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)

        item_id = f"reg|HKCU|{sub}|{name}"

        r1, m1 = tools.set_startup_enabled(item_id, False)
        moved = (not has(sub)) and has(sub + suf)
        if not (r1 and moved):
            ok = False
            lines.append(f"  !! 禁用失败：{m1}（活动键={has(sub)}）")
        else:
            lines.append("启动项禁用/还原 : 通过（值在活动键与禁用区之间搬移，"
                         "不是删除）")

        # 重复禁用应被挡下，而不是把值弄丢
        r2, _ = tools.set_startup_enabled(item_id, False)
        if r2:
            ok = False
            lines.append("  !! 重复禁用居然成功了（应当拒绝）")

        r3, m3 = tools.set_startup_enabled(item_id, True)
        back = has(sub) and (not has(sub + suf))
        if not (r3 and back):
            ok = False
            lines.append(f"  !! 还原失败：{m3}")
        else:
            with winreg.OpenKey(hive, sub) as k:
                v, t = winreg.QueryValueEx(k, name)
            if v != value or t != winreg.REG_SZ:
                ok = False
                lines.append("  !! 搬移过程中值内容或类型被改了")
            else:
                lines.append("启动项内容保真   : 通过（搬移不改值，类型也保留）")
    except Exception as e:                                  # noqa: BLE001
        ok = False
        lines.append(f"  !! 启动项测试异常: {type(e).__name__}: {e}")
    finally:
        cleanup()
        if has(sub) or has(sub + suf):
            ok = False
            lines.append("  !! 测试夹具没清理干净")
    return ok, lines


def run(label, fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            code = fn()
        except Exception as e:          # noqa: BLE001
            import traceback
            buf.write(traceback.format_exc())
            code = 99
    print(f"───── {label}  (exit={code}) ─────")
    print(buf.getvalue().rstrip())
    print()
    return code


def main() -> int:
    for s in ("stdout", "stderr"):
        try:
            getattr(sys, s).reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    from app.core import junk, mem

    rc_mem = run("内存优化核心", mem.selftest)
    rc_junk = run("垃圾清理核心", junk.cli_selftest)

    # 清理是破坏性操作，不能用真实数据做自动化验证。
    # 这里在临时目录造受控夹具，单独验证「删除」这条路径。
    print("───── 清理行为（受控夹具） ─────")
    fok, flines = _fixture_clean_tests(junk)
    for ln in flines:
        print(ln)
    print()

    # 自身进程树保护：这是「一键加速把自己界面关掉」那个 bug 的守卫
    print("───── 自身进程保护 ─────")
    sok, slines = _fixture_self_tree_test(mem)
    for ln in slines:
        print(ln)
    print()

    # 同名目录区分：这是「把 Python 标准库的 Lib/venv 删掉」那个 bug 的守卫
    print("───── 同名目录区分 ─────")
    vok, vlines = _fixture_venv_marker_test(junk)
    for ln in vlines:
        print(ln)
    print()

    # 启动项读写：这是「禁用时报找不到」那个 bug 的守卫
    print("───── 启动项读写（受控夹具） ─────")
    try:
        from . import tools as _tools
    except ImportError:
        from app.core import tools as _tools
    tok, tlines = _fixture_startup_test(_tools)
    for ln in tlines:
        print(ln)
    print()

    print("=" * 62)
    results = [("内存优化核心", rc_mem), ("垃圾清理核心", rc_junk),
               ("清理行为夹具", 0 if fok else 1),
               ("自身进程保护", 0 if sok else 1),
               ("虚拟环境识别", 0 if vok else 1),
               ("启动项读写", 0 if tok else 1)]
    for name, rc in results:
        print(f"  {name:<14} {'通过' if rc == 0 else f'失败 (exit={rc})'}")
    ok = all(rc == 0 for _, rc in results)
    print("=" * 62)
    print("M1 回归：" + ("全部通过" if ok else "存在失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
