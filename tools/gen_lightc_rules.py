# -*- coding: utf-8 -*-
"""从 lightc-rules.json 生成 app/core/rules_lightc.py。

lightc-rules.json 是子代理从 LightC（Chunyu33/light-c）的
src-tauri/src/scanner/categories.rs 提取的 18 个 JunkCategory 的完整规则表。

生成物 rules_lightc.py 是一个**纯数据模块**：它在 import 时通过
`from app.core import junk as _j` 引用 junk 的运行时环境常量（TEMP/WINDIR/…），
把 LightC 的 %VAR% 模板路径还原成真实路径，产出 18 条 junk 引擎可直接消费的
规则字典。这样打包后无论在谁的机器上跑，路径都跟着那台机器的真实环境走。

风险映射：LightC 的 risk 1/2/3 → junk 的 level safe/caution/risky。
locked（仅 OldWindowsInstallation）→ level=risky + 额外 locked 标志。

运行方式：`python tools/gen_lightc_rules.py`（在仓库根或任意目录均可，
脚本自身按 __file__ 定位仓库根）。产物写入 app/core/rules_lightc.py。
"""

from __future__ import annotations

import json
import os
import sys

# 仓库根 = 本脚本所在 tools/ 的上一级
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(ROOT, "lightc-rules.json")
OUT_PATH = os.path.join(ROOT, "app", "core", "rules_lightc.py")

# LightC 的 %VAR% → junk 运行时常量的属性名（生成物里写成 _j.<名字>）
VAR_EXPR = {
    "%TEMP%": "TEMP",           # junk 无 TMP 常量，%TMP% 与 %TEMP% 同源
    "%TMP%": "TEMP",
    "%WINDIR%": "WINDIR",       # SystemRoot
    "%LOCALAPPDATA%": "LOCAL",
    "%APPDATA%": "ROAMING",
    "%PROGRAMDATA%": "PROGRAMDATA",
    "%SYSTEMDRIVE%": "SYSTEM_ROOT_DIR",   # 形如 "C:\\"，与 LightC 的 "C:" 语义一致
}

# risk → junk level
RISK_LEVEL = {1: "safe", 2: "caution", 3: "risky"}

# key 前缀，避免与 junk 内置规则（user_temp/prefetch/…）撞名，且便于 grep 溯源
KEY_PREFIX = "lightc_"

# 每条规则的人类可读中文说明（生成时写死，保证描述质量与稳定性）
DESC = {
    "WindowsTemp": "系统和程序的临时文件。删除后会自动重建，是最值得清理的一项。",
    "SystemCache": "系统预读取缓存（Prefetch）与 Windows 缓存目录。\n"
                   "删除后系统启动与程序首次启动会变慢，之后自动重建。",
    "BrowserCache": "浏览器网页缓存、脚本缓存、GPU 缓存与着色器缓存，覆盖 "
                    "Edge/Chrome/Firefox/Brave/Opera/QQ浏览器/360 等。\n"
                    "不影响收藏夹、密码与登录状态。",
    "RecycleBin": "清空回收站。\n注意：这是永久删除，清空后无法还原。",
    "WindowsUpdate": "已下载的 Windows 更新包。已安装的可以删，系统会重新下载需要的部分。",
    "DeliveryOptimization": "Windows 更新分发优化缓存（局域网/互联网共享的更新片段）。",
    "WindowsDefenderCache": "Microsoft Defender 的本地副本、支持文件与扫描历史缓存。",
    "ThumbnailCache": "资源管理器的缩略图与图标缓存数据库。删除后重新打开文件夹会重建。",
    "LogFiles": "Windows 日志（*.log / *.etl / *.evtx）与崩溃转储目录。",
    "MemoryDump": "蓝屏时产生的小型转储（Minidump 目录下的 *.dmp）。仅排障需要。\n"
                  "完整内存镜像 MEMORY.DMP 由内置规则单独处理。",
    "OldWindowsInstallation": "系统升级前的旧 Windows 备份与更新回滚数据。删除后无法回退。\n"
                              "此项目由系统管理，本工具不直接删除，请在「磁盘清理」中处理。",
    "AppCache": "应用程序缓存（WebCache）。",
    "ThirdPartyAppCache": "第三方应用缓存（Discord / Slack / Teams / Steam / Epic / "
                          "网易云音乐 / QQ音乐）。",
    "FontCache": "字体渲染缓存，自动重建。",
    "WindowsErrorReports": "Windows 错误报告存档与队列。",
    "InstallerTemp": "安装程序的补丁缓存与已下载的安装包。",
    "ClipboardCache": "剪贴板历史缓存。",
    "ShaderCache": "DirectX 着色器缓存。删除后游戏首次运行会重新编译，"
                   "画面异常时清它常能解决。",
}


def _snake(name: str) -> str:
    """PascalCase 分类名 → snake_case key。"""
    out = []
    for ch in name:
        if ch.isupper() and out:
            out.append("_")
        out.append(ch.lower())
    return KEY_PREFIX + "".join(out).strip("_")


def _render_path(p: str) -> str | None:
    """把一个 LightC 模板路径渲染成 Python 表达式字符串。

    返回 None 表示该路径需要调用方特殊处理（目前只有 {DRIVE}: 动态盘符）。
    """
    if p == "{DRIVE}:\\$Recycle.Bin":
        return None
    segments = p.split("\\")
    exprs = []
    for seg in segments:
        if seg in VAR_EXPR:
            exprs.append(f"_j.{VAR_EXPR[seg]}")
        else:
            exprs.append(repr(seg))
    if len(exprs) == 1:
        return exprs[0]
    return f"_j._join({', '.join(exprs)})"


def _emit_rule(entry: dict, lines: list[str]) -> None:
    cat = entry["category"]
    key = _snake(cat)
    level = RISK_LEVEL[entry["risk"]]
    locked = bool(entry.get("locked"))
    system_managed = bool(entry.get("system_managed"))
    default = bool(entry.get("default_checked")) and not locked

    patterns = list(entry.get("patterns") or [])

    # RecycleBin：junk 有专用 shell API（kind="recyclebin"），比 LightC 直接扫
    # $Recycle.Bin 目录更安全（尊重每卷回收站设置、不绕过系统），风险档按 LightC。
    if cat == "RecycleBin":
        kind = "recyclebin"
        paths = ["::recyclebin::"]
        patterns = []
        path_exprs = ['"::recyclebin::"']
    # MemoryDump：只保留 Minidump 目录 + *.dmp。%WINDIR%\MEMORY.DMP 是单个
    # 大文件，且 expand_paths 会把 Minidump（WINDIR 的子目录）去重掉只剩 WINDIR
    # 根，导致 glob(WINDIR, "*.dmp") 扫整个 Windows 树 —— 过宽危险。完整镜像
    # MEMORY.DMP 交给 junk 内置 memory_dmp 规则单独处理。
    elif cat == "MemoryDump":
        kind = "files"
        path_exprs = ['_j._join(_j.WINDIR, "Minidump")']
        patterns = ["*.dmp"]
    else:
        kind = "files" if patterns != ["*"] else "contents"
        path_exprs = []
        for p in entry["scan_paths"]:
            e = _render_path(p)
            if e is not None:
                path_exprs.append(e)

    lines.append(f"    # {cat} — {entry['source']}")
    lines.append(f"    _r({key!r}, {entry['category_name_cn']!r}, "
                 f"{_category(entry)!r}, {level!r}, {kind!r},")
    lines.append(f"       [{', '.join(path_exprs)}],")
    lines.append(f"       {DESC[cat]!r}, default={default!r},"
                 f" patterns={patterns!r},")
    lines.append(f"       locked={locked!r}, system_managed={system_managed!r},"
                 f" source={entry['source']!r}),")
    lines.append("")


def _category(entry: dict) -> str:
    """给规则一个中文类别标签（用于前端按类别聚合展示）。"""
    return {
        "WindowsTemp": "临时文件",
        "SystemCache": "系统缓存",
        "BrowserCache": "浏览器缓存",
        "RecycleBin": "回收站",
        "WindowsUpdate": "更新残留",
        "DeliveryOptimization": "更新残留",
        "WindowsDefenderCache": "系统缓存",
        "ThumbnailCache": "系统缓存",
        "LogFiles": "日志与转储",
        "MemoryDump": "日志与转储",
        "OldWindowsInstallation": "系统残留",
        "AppCache": "应用缓存",
        "ThirdPartyAppCache": "应用缓存",
        "FontCache": "临时文件",
        "WindowsErrorReports": "日志与转储",
        "InstallerTemp": "安装残留",
        "ClipboardCache": "系统缓存",
        "ShaderCache": "系统缓存",
    }[entry["category"]]


def generate() -> str:
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    lines: list[str] = []
    lines.append("# -*- coding: utf-8 -*-")
    lines.append('"""LightC 垃圾清理规则库（**生成文件，勿手改**）。')
    lines.append("")
    lines.append(f"由 tools/gen_lightc_rules.py 从 lightc-rules.json 生成，"
                 f"共 {len(data)} 条规则。")
    lines.append("")
    lines.append("来源：LightC（Chunyu33/light-c），src-tauri/src/scanner/categories.rs")
    lines.append("     的 JunkCategory::all() 18 个分类。")
    lines.append("许可：LightC Source Available License v1.0，Copyright (c) 2026 Evan Lau，")
    lines.append("     **非开源**（第 7 条声明）。规则表属其实质内容，复用受其第 2 条限制。")
    lines.append("")
    lines.append("风险映射：LightC risk 1/2/3 → junk level safe/caution/risky。")
    lines.append("locked（仅 OldWindowsInstallation，is_system_managed=true）→ risky + locked 标志，")
    lines.append("前端整片禁用勾选，只引导系统磁盘清理。")
    lines.append("")
    lines.append("本模块在 import 时引用 junk 的运行时环境常量还原路径，")
    lines.append("因此在任何机器上跑都跟随该机器的真实环境变量。")
    lines.append('"""')
    lines.append("")
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("from app.core import junk as _j")
    lines.append("")
    lines.append("")
    lines.append("def _r(key, name, category, level, kind, paths, desc, default,")
    lines.append("      patterns=(), locked=False, system_managed=False, source=\"\"):")
    lines.append("    \"\"\"用 junk._rule 造规则，再补 LightC 独有的字段。\"\"\"")
    lines.append("    r = _j._rule(key, name, category, level, kind, paths, desc,")
    lines.append("                 default=default, patterns=patterns)")
    lines.append("    if locked or system_managed:")
    lines.append("        r[\"locked\"] = True")
    lines.append("        r[\"system_managed\"] = bool(system_managed)")
    lines.append("    r[\"source\"] = source")
    lines.append("    return r")
    lines.append("")
    lines.append("")
    lines.append("# 18 条规则，顺序与 categories.rs 的 JunkCategory::all() 一致。")
    lines.append("LIGHTC_RULES: list[dict] = [")
    for entry in data:
        _emit_rule(entry, lines)
    lines.append("]")
    lines.append("")
    lines.append("")
    lines.append("def lightc_keys() -> list[str]:")
    lines.append("    \"\"\"所有 LightC 规则的 key（verify 与覆盖过滤用）。\"\"\"")
    lines.append("    return [r[\"key\"] for r in LIGHTC_RULES]")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    text = generate()
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"已生成 {OUT_PATH}（{len(text.encode('utf-8'))} 字节）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
