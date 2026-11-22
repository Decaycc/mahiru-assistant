# -*- coding: utf-8 -*-
"""M1：把两个脚本的「纯逻辑」机械抽取到 app/core/。

⚠ 重要：app/core/*.py 是**生成物**。直接改它们，下次重跑本脚本就会被覆盖。
   要改行为请改 GameBoost/ 下的源文件（或改本脚本的 fix_* 适配步骤），
   然后重跑本脚本来保持两边一致。

原则：逐行搬运，不改行为。整个过程**只有 2 处改动**，且都可审计：
  1. SCRIPT_DIR 的解析方式 —— 改为走 app/paths.py，兼容 onefile 打包
  2. third_party_rules 的导入方式 —— 兼容包内相对导入

切分点全部由内容定位，不写死行号，源文件改动后重跑仍然正确。
"""
import os
import shutil
import sys

# 路径按本文件位置推导，不写死机器路径 —— 否则别人克隆下来直接跑不了。
# 目录结构约定：<仓库根>/GameBoostNext/tools/split_core.py
#               <仓库根>/GameBoost/{gameboost,junkclean,third_party_rules}.py
DST = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(DST)
SRC = os.environ.get("MAHIRU_SRC") or os.path.join(_REPO, "GameBoost")
CORE = os.path.join(DST, "app", "core")
if not os.path.isfile(os.path.join(SRC, "gameboost.py")):
    print(f"找不到源文件目录：{SRC}\n"
          f"  本脚本需要与它同级的 GameBoost/ 目录（旧版 tkinter 源码）。\n"
          f"  如在别处，可用环境变量 MAHIRU_SRC 指定。", file=sys.stderr)
    sys.exit(2)


def load(path):
    with open(path, encoding="utf-8") as f:
        return f.readlines()


def find(lines, pred, start=0, what=""):
    for i in range(start, len(lines)):
        if pred(lines[i]):
            return i
    raise LookupError(f"找不到切分点: {what}")


def strip_marker(line):
    return line.strip()


def fix_paths(lines, app_name):
    """改动 1：把 SCRIPT_DIR 指向可写的 config 目录。

    不能用「相对 __file__ 往上数三层」那种写法：打包成 onefile 后
    __file__ 位于每次启动都变的临时解压目录，配置会跟着丢。
    统一走 app/paths.py —— 它把只读资源与可写数据分开处理。
    """
    out, done = [], False
    for line in lines:
        if not done and line.strip().startswith("SCRIPT_DIR = "):
            out.append("# 配置目录：由 app/paths.py 统一解析。\n")
            out.append("# 直接按 __file__ 推导在 onefile 打包后会指到临时解压目录，\n")
            out.append("# 导致每次启动配置都是空的，所以这里必须走 paths。\n")
            out.append("#\n")
            out.append("# 兼容两种运行方式：作为包导入时 'app' 已在 sys.path 里；\n")
            out.append("# 直接 `python app/core/xxx.py` 跑脚本时 sys.path[0] 是\n")
            out.append("# app/core/，包根不在里面，需要自己补上。\n")
            out.append("try:\n")
            out.append("    from app.paths import config_dir as _config_dir\n")
            out.append("except ImportError:                 # 脚本方式直接运行\n")
            out.append("    import sys as _sys\n")
            out.append("    _sys.path.insert(0, os.path.dirname(os.path.dirname(\n")
            out.append("        os.path.dirname(os.path.abspath(__file__)))))\n")
            out.append("    from app.paths import config_dir as _config_dir\n")
            out.append("SCRIPT_DIR = _config_dir()\n")
            done = True
            continue
        out.append(line)
    if not done:
        raise LookupError(f"{app_name}: 没找到 SCRIPT_DIR 定义")
    return out


_RULES_LOADER = '''

def _load_rules_module():
    """载入第三方规则模块，**优先用可写目录里的那份**。

    为什么需要这个顺序：打包成 onefile 后，内置的 third_party_rules.py 位于
    每次启动都变的临时解压目录（%TEMP%\\\\_MEIxxxx，退出即删）。
    用户在软件里点「更新规则」如果写到那里，下次启动就没了。
    所以更新后的规则写到 config/ 下，加载时优先读它，读不到才用内置的。

    返回模块对象；都拿不到时返回 None。
    """
    import importlib.util as _ilu
    try:
        from app.paths import config_dir as _cd
        override = os.path.join(_cd(), "third_party_rules.py")
        if os.path.isfile(override):
            spec = _ilu.spec_from_file_location(
                "third_party_rules_override", override)
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    except Exception:
        pass                      # 覆盖版坏了就退回内置，不影响可用性
    try:
        import third_party_rules as _tpr
        return _tpr
    except ImportError:           # 抽取到包内后走相对导入
        try:
            from . import third_party_rules as _tpr
            return _tpr
        except Exception:
            return None


'''


def fix_third_party_import(lines):
    """改动 2：规则模块改为「可写目录优先，内置兜底」。

    同时注入 _load_rules_module 辅助函数。这样打包后也能更新规则。
    """
    out, done = [], False
    for line in lines:
        if not done and line.strip() == "import third_party_rules as tpr":
            indent = line[:len(line) - len(line.lstrip())]
            out.append(f"{indent}tpr = _load_rules_module()\n")
            out.append(f"{indent}if tpr is None:\n")
            out.append(f"{indent}    raise ImportError('找不到规则模块')\n")
            done = True
            continue
        out.append(line)

    # 在 _load_third_party 之前插入辅助函数
    final, injected = [], False
    for line in out:
        if not injected and line.startswith("def _load_third_party"):
            final.append(_RULES_LOADER.lstrip("\n"))
            injected = True
        final.append(line)
    if not injected:
        raise LookupError("找不到 _load_third_party，无法注入规则加载器")
    return final


def write(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)
    print(f"  写入 {os.path.relpath(path, DST):<40} {len(lines):>5} 行")


# ============================================================ gameboost.py
def split_mem():
    lines = load(os.path.join(SRC, "gameboost.py"))
    gi = find(lines, lambda l: strip_marker(l) == "# 图形界面", what="图形界面")
    si = find(lines, lambda l: strip_marker(l) == "# 自检 / 报告模式", what="自检")
    ci = find(lines, lambda l: l.startswith("def _install_crash_handler"),
              what="_install_crash_handler")
    core = lines[:gi - 1] + lines[si - 1:ci - 1]
    core = fix_paths(core, "gameboost")
    core.append('\n\nif __name__ == "__main__":\n')
    core.append('    # 直接运行本模块时沿用原版命令行入口\n')
    core.append('    if "--selftest" in sys.argv:\n')
    core.append('        sys.exit(selftest())\n')
    core.append('    if "--report" in sys.argv:\n')
    core.append('        sys.exit(report())\n')
    core.append('    print("用法: python mem.py [--selftest|--report]")\n')
    write(os.path.join(CORE, "mem.py"), core)
    return len(lines) - len(core)


# ============================================================ junkclean.py
def split_junk():
    lines = load(os.path.join(SRC, "junkclean.py"))
    cls = find(lines, lambda l: l.startswith("class JunkCleanWindow:"),
               what="JunkCleanWindow")
    c1 = find(lines, lambda l: strip_marker(l) == "# 命令行", what="命令行")
    ci = find(lines, lambda l: l.startswith("def _install_crash_handler"),
              what="_install_crash_handler")
    core = lines[:cls - 1] + lines[c1 - 1:ci - 1]
    core = fix_paths(core, "junkclean")
    core = fix_third_party_import(core)
    core.append('\n\nif __name__ == "__main__":\n')
    core.append('    # 直接运行本模块时沿用原版命令行入口\n')
    core.append('    _setup_console()\n')
    core.append('    if "--selftest" in sys.argv:\n')
    core.append('        sys.exit(cli_selftest())\n')
    core.append('    if "--scan" in sys.argv:\n')
    core.append('        sys.exit(cli_scan())\n')
    core.append('    if "--analyze" in sys.argv:\n')
    core.append('        _p = sys.argv[sys.argv.index("--analyze") + 1]\n')
    core.append('        sys.exit(cli_analyze(_p))\n')
    core.append('    print("用法: python junk.py [--selftest|--scan|--analyze PATH]")\n')
    write(os.path.join(CORE, "junk.py"), core)
    return len(lines) - len(core)


def main():
    print("M1 核心抽取")
    print("=" * 60)
    os.makedirs(CORE, exist_ok=True)

    for pkg in (os.path.join(DST, "app"), CORE):
        init = os.path.join(pkg, "__init__.py")
        if not os.path.exists(init):
            with open(init, "w", encoding="utf-8") as f:
                f.write("")

    d_mem = split_mem()
    d_junk = split_junk()

    # 规则数据。
    # 只在**目标不存在**时复制：third_party_rules.py 现在归 tools/update_rules.py
    # 管（它会同时写 app/core/ 与旧版两份）。切分器若无条件覆盖，
    # 两个工具就会互相打架 —— 先跑更新、再跑切分，更新就白做了。
    rules_src = os.path.join(SRC, "third_party_rules.py")
    rules_dst = os.path.join(CORE, "third_party_rules.py")
    if os.path.exists(rules_dst):
        print(f"  跳过 third_party_rules.py（已存在，归 update_rules.py 管）")
    else:
        shutil.copyfile(rules_src, rules_dst)
        print(f"  复制 third_party_rules.py"
              f"  {os.path.getsize(rules_dst) // 1024} KB")

    print()
    print(f"  gameboost.py  剔除 {d_mem} 行（图形界面）")
    print(f"  junkclean.py  剔除 {d_junk} 行（图形界面）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
