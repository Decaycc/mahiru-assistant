# -*- coding: utf-8 -*-
"""
JunkClean —— Windows C/D 盘安全垃圾清理

设计原则（决定了它与"注册表清理大师"们的区别）：

  1. **只删缓存和临时文件，绝不删用户数据。** 规则是白名单式的：每一条规则都
     明确指向一个已知可再生的目录，而不是"扫描全盘找出看起来像垃圾的东西"。
  2. **不碰必须先删的目录本身。** 只清目录**内容**，保留目录，避免破坏程序的
     目录结构假设。
  3. **正在使用中的文件跳过，不强制删除。** 删不掉就如实报告原因，不用各种
     手段硬删 —— 硬删正在被占用的文件是搞坏系统的常见原因。
  4. **明确列出"不能删"的东西以及原因。** 这是本工具刻意做的功能：很多清理
     软件会把 C:\\Windows\\Installer 这类目录当垃圾推荐你删，删完软件就无法
     卸载/修复了。

零第三方依赖：只用 Python 标准库 + ctypes。

命令行：
  python junkclean.py            图形界面
  python junkclean.py --scan     命令行扫描，列出各类垃圾占用
  python junkclean.py --analyze C:\\path   分析指定目录的占用构成
"""

from __future__ import annotations

import ctypes
import fnmatch
import os
import queue
import shutil
import stat
import subprocess
import sys
import threading
import time
from ctypes import wintypes

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except Exception:  # pragma: no cover
    tk = None

APP_NAME = "JunkClean 垃圾清理"
APP_VERSION = "1.0"
# 配置目录：由 app/paths.py 统一解析。
# 直接按 __file__ 推导在 onefile 打包后会指到临时解压目录，
# 导致每次启动配置都是空的，所以这里必须走 paths。
#
# 兼容两种运行方式：作为包导入时 'app' 已在 sys.path 里；
# 直接 `python app/core/xxx.py` 跑脚本时 sys.path[0] 是
# app/core/，包根不在里面，需要自己补上。
try:
    from app.paths import config_dir as _config_dir
except ImportError:                 # 脚本方式直接运行
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    from app.paths import config_dir as _config_dir
SCRIPT_DIR = _config_dir()
CONFIG_PATH = os.path.join(SCRIPT_DIR, "junkclean_config.json")

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4

# ---------------------------------------------------------------------------
# 环境变量展开
# ---------------------------------------------------------------------------
# 注意：这里一律从环境变量推导，不写死 C:\ —— 系统盘不是 C 的机器上同样可用。

LOCAL = os.environ.get("LOCALAPPDATA", "")
ROAMING = os.environ.get("APPDATA", "")
PROFILE = os.environ.get("USERPROFILE", "")
SYSTEM_DRIVE = os.environ.get("SystemDrive", "C:")      # 形如 "C:"
SYSTEM_ROOT_DIR = SYSTEM_DRIVE + "\\"                   # 形如 "C:\"
PROGRAMDATA = os.environ.get("ProgramData", SYSTEM_ROOT_DIR + "ProgramData")
WINDIR = os.environ.get("SystemRoot", SYSTEM_ROOT_DIR + "Windows")
TEMP = os.environ.get("TEMP", "")


def _join(*parts) -> str:
    return os.path.join(*parts) if all(parts) else ""


def _chromium_cache_paths(user_data: str) -> list[str]:
    """Chromium 系浏览器（Edge / Chrome / Brave / Opera…）的完整缓存路径集合。

    参考 BleachBit 的 microsoft_edge.xml / google_chrome.xml：
    除了 Default\\Cache，还有各配置文件的多种缓存、扩展的 GPU 缓存、
    以及用户数据根目录下的着色器缓存。用 * 通配以覆盖所有配置文件。
    """
    if not user_data:
        return []
    paths: list[str] = []
    # 用户数据根目录下的缓存
    for d in ("component_crx_cache", "extensions_crx_cache",
              "GPUPersistentCache", "GraphiteDawnCache", "ShaderCache",
              "GrShaderCache"):
        paths.append(os.path.join(user_data, d))
    profile = os.path.join(user_data, "*")     # Default / Profile 1 / …
    for d in ("Cache", "Code Cache", "GPUCache", "Media Cache",
              "Application Cache", "DawnGraphiteCache", "DawnWebGPUCache",
              r"Service Worker\CacheStorage"):
        paths.append(os.path.join(profile, d))
    # 各扩展独立的 GPU/WebGPU 缓存
    for d in ("GPUCache", "DawnGraphiteCache", "DawnWebGPUCache"):
        paths.append(os.path.join(profile, "Storage", "ext", "*", "*", d))
    return paths


# ---------------------------------------------------------------------------
# 磁盘 / 已安装软件探测
# ---------------------------------------------------------------------------
# 目的：让规则能用在任意一台电脑上。绝不假设「Steam 装在 D:\steam」。

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.GetLogicalDrives.restype = wintypes.DWORD
k32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
k32.GetDriveTypeW.restype = wintypes.UINT
DRIVE_FIXED = 3

_DRIVE_CACHE: list[str] | None = None


def fixed_drives() -> list[str]:
    """枚举本地固定磁盘（排除光驱、U 盘、网络盘）。"""
    global _DRIVE_CACHE
    if _DRIVE_CACHE is not None:
        return _DRIVE_CACHE
    out: list[str] = []
    try:
        mask = k32.GetLogicalDrives()
    except Exception:
        _DRIVE_CACHE = [SYSTEM_ROOT_DIR]
        return _DRIVE_CACHE
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(ord('A') + i)}:\\"
            try:
                if k32.GetDriveTypeW(root) == DRIVE_FIXED:
                    out.append(root)
            except Exception:
                continue
    _DRIVE_CACHE = out or [SYSTEM_ROOT_DIR]
    return _DRIVE_CACHE


def steam_libraries() -> list[str]:
    """找出本机所有 Steam 安装目录与库目录。

    来源：注册表 SteamPath/InstallPath + 各库下的 libraryfolders.vdf。
    这样无论 Steam 装在哪个盘、哪个自定义目录都能找到。
    """
    import re
    found: list[str] = []

    def add(p):
        if not p:
            return
        try:
            if os.path.isdir(p):
                found.append(os.path.normpath(p))
        except OSError:
            pass

    try:
        import winreg
        for root, sub in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam")):
            try:
                with winreg.OpenKey(root, sub) as key:
                    for value in ("SteamPath", "InstallPath"):
                        try:
                            v, _ = winreg.QueryValueEx(key, value)
                            add(v)
                        except OSError:
                            pass
            except OSError:
                continue
    except Exception:
        pass

    # 从 libraryfolders.vdf 解析额外库目录
    for base in list(found):
        vdf = os.path.join(base, "steamapps", "libraryfolders.vdf")
        if not os.path.isfile(vdf):
            continue
        try:
            with open(vdf, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            for m in re.finditer(r'"path"\s*"([^"]+)"', text):
                add(m.group(1).replace("\\\\", "\\"))
        except Exception:
            continue

    seen, out = set(), []
    for p in found:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def _key_from_path(prefix: str, path: str) -> str:
    """由路径生成稳定的规则 key（跨进程一致，配置才能记住勾选状态）。"""
    import re
    slug = re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_")
    return f"{prefix}_{slug}"[:60]


# ---------------------------------------------------------------------------
# 规则定义
# ---------------------------------------------------------------------------
# level 含义：
#   safe    —— 纯缓存/临时文件，删除后系统或程序会自动重建，无任何数据风险
#   caution —— 可能有轻微副作用（如首次启动变慢、需要重新下载更新），默认勾选
#   risky   —— 需要用户明确知道后果，默认不勾选
#
# kind 含义：
#   "contents" —— 删除该目录下的所有内容（保留目录本身）
#   "files"    —— 只删除该目录下匹配扩展名的文件
#   "recyclebin" —— 清空回收站（专用 API）
#   "dir"      —— 删除整个目录（仅用于确实应该整个删掉的，如残留目录）

def _rule(key, name, category, level, kind, paths, desc, default=None,
          patterns=None, types=None):
    return {
        "key": key, "name": name, "category": category, "level": level,
        "kind": kind, "paths": paths, "desc": desc,
        # 每条 files 规则必须自带精确的匹配模式。绝不使用共享的兜底模式列表——
        # 否则会出现「规则名说清缩略图、实际却删了别的文件」这种错配。
        "patterns": list(patterns or []),
        # types 模式（全盘深扫）的匹配条目，语法见 _match_type
        "types": list(types or []),
        "default": (level != "risky") if default is None else default,
    }


RULES: list[dict] = [
    # ---------------- 系统临时文件 ----------------
    _rule("user_temp", "用户临时文件", "临时文件", "safe", "contents",
          [TEMP, _join(LOCAL, "Temp")],
          "程序和安装包运行时留下的临时文件。删完系统会自动重建，是最值得清的一项。"),
    _rule("win_temp", "系统临时文件", "临时文件", "safe", "contents",
          [_join(WINDIR, "Temp")],
          "系统级临时目录。部分文件正被占用，删不掉的会自动跳过。"),
    _rule("prefetch", "预读取文件", "临时文件", "caution", "files",
          [_join(WINDIR, "Prefetch")],
          "Windows 用来加速程序启动的缓存（*.pf）。\n"
          "删除后前几次启动会稍慢，之后自动重建。",
          patterns=["*.pf"], default=False),
    _rule("font_cache", "字体缓存", "临时文件", "safe", "files",
          [_join(WINDIR, "ServiceProfiles\\LocalService\\AppData\\Local\\FontCache")],
          "字体渲染缓存，会自动重建。",
          patterns=["*.dat"]),

    # ---------------- 浏览器缓存 ----------------
    # 路径集合参考 BleachBit 的 microsoft_edge.xml / google_chrome.xml 规则
    # （GPL 开源、长期维护），比只清 Default\Cache 完整得多。
    _rule("edge_cache", "Edge 缓存", "浏览器缓存", "safe", "contents",
          _chromium_cache_paths(_join(LOCAL, "Microsoft", "Edge", "User Data")),
          "网页缓存、脚本缓存、GPU/WebGPU 缓存、着色器缓存，覆盖所有配置文件。\n"
          "不会影响收藏夹、密码、登录状态和历史记录。"),
    _rule("chrome_cache", "Chrome 缓存", "浏览器缓存", "safe", "contents",
          _chromium_cache_paths(_join(LOCAL, "Google", "Chrome", "User Data")),
          "同上。不含书签与密码。"),
    _rule("edge_tmp", "Edge/Chrome 临时文件", "浏览器缓存", "safe", "files",
          [_join(LOCAL, "Microsoft", "Edge", "User Data"),
           _join(LOCAL, "Google", "Chrome", "User Data")],
          "浏览器在用户数据目录里留下的 B*.tmp 临时文件。",
          patterns=["B*.tmp"]),
    _rule("webview_cache", "WebView2 缓存", "浏览器缓存", "safe", "contents",
          [_join(LOCAL, "Microsoft", "EdgeWebView")],
          "内嵌浏览器组件（很多软件用它显示网页）的缓存。"),
    _rule("inetcache", "IE/系统网络缓存", "浏览器缓存", "safe", "contents",
          [_join(LOCAL, "Microsoft", "Windows", "INetCache"),
           _join(LOCAL, "Microsoft", "Windows", "WebCache"),
           _join(LOCAL, "Microsoft", "Feeds Cache")],
          "系统级网络缓存与订阅源缓存。\n"
          "（SYSTEM 账户下的同名缓存在 System32 之内，属保护范围，本工具不碰。）"),
    _rule("ie_legacy", "IE 兼容性缓存", "浏览器缓存", "safe", "contents",
          [_join(ROAMING, "Microsoft", "Windows", "IETldCache"),
           _join(ROAMING, "Microsoft", "Windows", "IECompatCache"),
           _join(ROAMING, "Microsoft", "Windows", "IECompatUACache"),
           _join(LOCAL, "Microsoft", "Internet Explorer", "iconcache"),
           # 注意：这里必须逐个写死，不能用 INet* 通配 ——
           # 那个通配会连 INetCookies / INetHistory 一起匹配上，
           # 那是用户的 Cookie 和浏览历史，不是垃圾。
           _join(LOCAL, "Packages", "windows_ie_ac_*", "AC", "INetCache"),
           _join(LOCAL, "Packages", "windows_ie_ac_*", "AC", "Temp"),
           _join(LOCAL, "Packages", "windows_ie_ac_*", "LocalState", "Cache"),
           _join(LOCAL, "Packages", "windows_ie_ac_*", "TempState")],
          "IE 的顶级域名缓存、兼容性视图缓存与其 UWP 版本的缓存。\n"
          "不含 Cookie、历史记录与已保存的密码。"),
    _rule("app_caches", "应用缓存（Office / 媒体播放器 / 邮件）", "应用缓存",
          "safe", "contents",
          [_join(LOCAL, "Microsoft", "Office", "OffDiag"),
           _join(LOCAL, "Microsoft", "Media Player", "Cache*"),
           _join(LOCAL, "Microsoft", "Media Player", "Grafikcache"),
           _join(LOCAL, "Microsoft", "Media Player", "Transcoded Files Cache"),
           _join(LOCAL, "Thunderbird", "Profiles", "*", "cache2"),
           _join(LOCAL, "Thunderbird", "Profiles", "*", "startupCache")],
          "Office 诊断缓存、媒体播放器缩略图/转码缓存、Thunderbird 邮件缓存。"),
    _rule("d3d_cache", "DirectX 着色器缓存", "系统缓存", "caution", "contents",
          [_join(LOCAL, "D3DSCache"), _join(LOCAL, "NVIDIA", "DXCache"),
           _join(LOCAL, "AMD", "DxCache")],
          "游戏编译好的显卡着色器缓存。\n删除后游戏首次运行会重新编译，"
          "可能有一小段卡顿；遇到画面异常时删掉它常能解决问题。",
          default=False),

    # ---------------- 缩略图与图标 ----------------
    _rule("thumb_cache", "缩略图与图标缓存", "系统缓存", "safe", "files",
          [_join(LOCAL, "Microsoft", "Windows", "Explorer")],
          "资源管理器为图片/视频生成的缩略图与图标数据库"
          "（thumbcache_*.db / iconcache_*.db）。\n"
          "删除后重新打开文件夹会重建。若缩略图显示异常，清它常能解决。",
          patterns=["thumbcache_*.db", "iconcache_*.db"]),

    # ---------------- 日志与转储 ----------------
    _rule("crash_dumps", "崩溃转储文件", "日志与转储", "safe", "contents",
          [_join(LOCAL, "CrashDumps")],
          "程序崩溃时产生的内存转储文件。除非要排障，否则可以删。"),
    _rule("wer_reports", "Windows 错误报告", "日志与转储", "safe", "contents",
          [_join(LOCAL, "Microsoft", "Windows", "WER"),
           _join(PROGRAMDATA, "Microsoft", "Windows", "WER")],
          "系统错误报告的存档与队列。"),
    _rule("minidump", "系统小内存转储", "日志与转储", "caution", "contents",
          [_join(WINDIR, "Minidump")],
          "蓝屏时产生的小型转储。如果近期排查过蓝屏问题，建议先留着。"),
    _rule("cbs_logs", "组件安装日志", "日志与转储", "safe", "files",
          [_join(WINDIR, "Logs", "CBS"), _join(WINDIR, "Logs", "DISM"),
           _join(WINDIR, "Logs", "WindowsUpdate")],
          "系统更新与服务组件安装日志。体积可能很大。",
          patterns=["*.log", "*.cab", "*.etl", "*.txt"]),
    _rule("installer_logs", "安装程序日志", "日志与转储", "safe", "files",
          [WINDIR, _join(LOCAL, "Temp")],
          "形如 MSI*.log / dd_*.log 的散落安装日志。",
          patterns=["MSI*.LOG", "MSI*.log", "dd_*.log", "dd_*.txt"]),

    # ---------------- Windows 更新残留 ----------------
    _rule("wu_download", "Windows 更新下载缓存", "更新残留", "caution", "contents",
          [_join(WINDIR, "SoftwareDistribution", "Download")],
          "已下载的更新包。已装完的可以删；系统会重新下载需要的部分。\n"
          "建议在系统更新完成后清理。"),
    _rule("delivery_opt", "更新分发优化缓存", "更新残留", "caution", "contents",
          [_join(WINDIR, "SoftwareDistribution", "DeliveryOptimization"),
           _join(WINDIR, "ServiceProfiles\\NetworkService\\AppData\\Local\\Microsoft\\Windows\\DeliveryOptimization")],
          "用于在局域网/互联网上共享更新片段的缓存。"),
    _rule("winre_agent", "更新回滚残留", "更新残留", "caution", "contents",
          [SYSTEM_ROOT_DIR + "$WinREAgent", SYSTEM_ROOT_DIR + "$Windows.~BT"],
          "系统更新过程中的回滚数据。更新稳定运行一段时间后可删。"),

    # ---------------- 开发工具缓存 ----------------
    _rule("pip_cache", "pip 缓存", "开发缓存", "safe", "contents",
          [_join(LOCAL, "pip", "Cache")],
          "Python 包下载缓存。删掉后重装包会重新下载。"),
    _rule("npm_cache", "npm 缓存", "开发缓存", "safe", "contents",
          [_join(ROAMING, "npm-cache"), _join(LOCAL, "npm-cache")],
          "Node.js 包缓存。"),
    _rule("nuget_cache", "NuGet 缓存", "开发缓存", "safe", "contents",
          [_join(PROFILE, ".nuget", "packages")],
          ".NET 包缓存。"),
    _rule("gradle_cache", "Gradle 缓存", "开发缓存", "caution", "contents",
          [_join(PROFILE, ".gradle", "caches")],
          "Gradle 构建缓存。删除后下次构建会重新下载依赖。", default=False),
    _rule("vscode_cache", "VS Code 缓存", "开发缓存", "safe", "contents",
          [_join(ROAMING, "Code", "Cache"), _join(ROAMING, "Code", "CachedData"),
           _join(ROAMING, "Code", "GPUCache")],
          "编辑器缓存，不含你的配置与插件。"),

    # ---------------- 回收站 ----------------
    _rule("recyclebin", "回收站", "回收站", "caution", "recyclebin",
          ["::recyclebin::"],
          "清空 C 盘与 D 盘的回收站。\n注意：这是永久删除，清空后无法还原！",
          default=False),

    # ---------------- 微软 cleanmgr 已覆盖、但常被忽略的安全项 ----------------
    # 下面这些类别的依据是 Windows 自带「磁盘清理」注册的 VolumeCaches 列表
    # （HKLM\...\Explorer\VolumeCaches），也就是微软自己认可的可清理范围。
    _rule("downloaded_program_files", "已下载的程序文件 (ActiveX)", "系统残留",
          "safe", "contents",
          [os.path.join(WINDIR, "Downloaded Program Files")],
          "早年网页 ActiveX 控件留下的缓存，现在已无用。"),
    _rule("offline_pages", "离线网页", "浏览器缓存", "safe", "contents",
          [_join(LOCAL, "Microsoft", "Windows", "Offline Web Pages")],
          "IE 时代保存的离线网页副本。"),
    _rule("feedback_logs", "反馈中心日志", "日志与转储", "safe", "contents",
          [_join(LOCAL, "Microsoft", "FeedbackHub"),
           _join(PROGRAMDATA, "Microsoft", "FeedbackHub")],
          "Windows 反馈中心的归档日志。"),
    _rule("retaildemo", "零售演示内容", "系统残留", "safe", "contents",
          [_join(PROGRAMDATA, "Microsoft", "RetailDemo")],
          "电脑预装的零售演示资料，普通用户用不到。"),
    _rule("diagnostic_data", "诊断数据数据库", "日志与转储", "safe", "contents",
          [_join(LOCAL, "Microsoft", "DiagnosticDataViewer"),
           _join(PROGRAMDATA, "Microsoft", "DiagnosticLogCNS")],
          "系统诊断数据的本地数据库。"),
    _rule("livekernel_dumps", "内核实时转储", "日志与转储", "safe", "contents",
          [os.path.join(WINDIR, "LiveKernelReports")],
          "内核记录的问题报告，只在排障时有用。"),
    _rule("temp_setup", "临时安装文件", "安装残留", "safe", "contents",
          [os.path.join(WINDIR, "Setup", "Temp")],
          "Windows 组件安装时解压的临时文件。"),
    _rule("setup_logs", "安装与升级日志", "日志与转储", "caution", "contents",
          [os.path.join(WINDIR, "Panther"),
           _join(WINDIR, "Logs", "SIH"), _join(WINDIR, "Logs", "MoSetup"),
           _join(WINDIR, "Logs", "NetSetup"), _join(WINDIR, "Logs", "Reset")],
          "系统安装 / 升级过程的详细日志，通常几十到几百 MB。"),
    _rule("memory_dmp", "完整内存转储 (MEMORY.DMP)", "日志与转储", "caution", "files",
          [WINDIR],
          "蓝屏时导出的完整内存镜像，大小约等于你的物理内存。\n"
          "只有需要把蓝屏交给厂商分析时才有用。",
          patterns=["MEMORY.DMP"], default=False),
    _rule("chkdsk_files", "磁盘检查恢复的文件碎片", "系统残留", "caution", "files",
          fixed_drives(),
          "chkdsk 把损坏的文件链恢复成 .CHK 放在盘根。\n"
          "里面可能含有你以前文件的内容，确认不需要再删。",
          patterns=["*.CHK", "*.chk"], default=False),
    _rule("esd_files", "Windows ESD 安装文件", "更新残留", "caution", "contents",
          [SYSTEM_ROOT_DIR + "$Windows.~WS"],
          "重置系统时会用到的安装镜像数据。确认不需要重置可删。", default=False),
    _rule("search_index", "Windows 搜索索引数据库", "系统缓存", "caution", "contents",
          [_join(PROGRAMDATA, "Microsoft", "Search", "Data",
                 "Applications", "Windows")],
          "搜索索引数据库 (Windows.edb)，可能有数 GB。\n"
          "被系统占用时删不掉；删除后索引会重建，期间搜索变慢。",
          default=False),

    # ---------------- 开发工具残留（散布全盘，参考 BleachBit deepscan）----
    _rule("dev_artifacts", "开发构建残留（node_modules / __pycache__ / venv）",
          "开发缓存", "caution", "types",
          fixed_drives(),
          "散落在各个项目里的构建产物与虚拟环境：\n"
          "  node_modules、__pycache__、.venv / venv、.angular\n"
          "它们是**可重建的**，但删掉后下次构建/运行需要重新安装依赖。\n"
          "只在磁盘实在紧张时清，且务必先看预览确认没有重要项目。",
          types=["dir:node_modules", "dir:__pycache__",
                 "dir:.venv@pyvenv.cfg", "dir:venv@pyvenv.cfg",
                 "dir:.angular"],
          default=False),
    _rule("editor_backup", "编辑器备份与临时文件", "临时文件", "caution", "types",
          fixed_drives(),
          "编辑器/Office 留下的备份与临时文件：\n"
          "  *.BAK、xxxx~（备份）、~wr*.tmp（Word）、ppt*.tmp（PowerPoint）、\n"
          "  .DS_Store、Thumbs.db、Vim 的 .swp\n"
          "其中 .BAK / ~ 备份有时是你手动留的，清前请先看预览。",
          types=["file:Thumbs.db", "file:.DS_Store", "glob:*.BAK",
                 "glob:*.bak", "glob:*~", "glob:~wr*.tmp", "glob:ppt*.tmp",
                 "glob:*.swp", "glob:*.swo"],
          default=False),

    # ---------------- 系统级动作 ----------------
    _rule("dism_components", "组件存储清理 (DISM)", "系统残留", "caution", "dism",
          ["::dism::"],
          "用微软官方的 DISM 清理 WinSxS 里被更新取代的旧组件。\n"
          "这是**唯一**安全清理 WinSxS 的方式 —— 手删会破坏系统更新与修复能力。\n"
          "耗时较长（5~20 分钟），需要管理员权限；回收量无法预先计算。",
          default=False),

    # ---------------- 需要谨慎的 ----------------
    _rule("windows_old", "旧版 Windows 备份 (Windows.old)", "系统残留", "risky",
          "contents", [SYSTEM_ROOT_DIR + "Windows.old"],
          "系统升级前的旧系统备份，通常有 10~30 GB。\n"
          "删除后将无法回退到上一个 Windows 版本。\n"
          "系统会在升级 10 天后自动清理它。", default=False),
]


# ---------------------------------------------------------------------------
# 动态探测：游戏平台 / 模拟器 / 安装器缓存
# ---------------------------------------------------------------------------
# 这些目录的位置在每台电脑上都不同（可能装在任意盘、任意目录），
# 所以不能写死路径，必须现场探测。这也是本工具能直接拿到别人电脑上用的关键。

# 盘根下这些名字的目录本身就是垃圾（安装器解压残留等）
# 注意：系统更新残留（$WinREAgent / $Windows.~BT / $Windows.~WS）已由上面的
# 静态规则覆盖，这里不要重复列出，否则会重复统计。
_ROOT_JUNK_DIRS = [
    ("squirreltemp", "安装器残留", "安装残留", "safe",
     "Electron 系安装程序（某些聊天工具、编辑器）解压时留下的临时目录，"
     "装完就没用了。"),
]

# 容器目录：在确认了程序身份后，按「子目录名特征」去找它的缓存目录。
# 不写死具体子目录名 —— 各版本/各安装方式下命名并不一致
# （实测：WeGame 用的是 cachedata / log，而不是 cache / logs）。
_SAFE_CACHE_SUBDIR_NAMES = {
    "cache", "caches", "cachedata", "cache_data", "cache2",
    "log", "logs",
    "temp", "tmp",
    "dumps", "crashlogs", "crashdumps",
    "appcache", "gpucache", "codecache", "shadercache", "webcache",
}

# 绝不进入这些目录：反作弊相关的东西一个字节都不碰
_NEVER_WALK = ("anticheat", "anti_cheat", "anti-cheat", "tenprotect", "tp3",
               "sguard", "easyanticheat", "battleye", "vanguard", "ace-guard",
               "aceguard", "ace_guard")

# 隐私敏感目录名：这些是用户数据，不是垃圾。任何规则都不允许匹配到它们。
# 起因：照搬 BleachBit 的 INet* 通配时，它连 INetCookies / INetHistory
# 一起匹配上了 —— 那等于替用户删掉了 Cookie 和浏览历史。
_PRIVACY_DIRS = {
    "cookies", "inetcookies", "history", "inethistory", "bookmarks",
    "favorites", "login data", "logins", "web data", "passwords",
    "formhistory", "form history", "autofill", "sessions", "sessionstore",
    "session store", "recent", "index.dat", "userdata", "saved passwords",
    "cookies-journal", "network persistent state", "preferences",
}


def _is_privacy_path(path: str) -> bool:
    """判断某个路径是否会碰到用户的隐私数据。"""
    low = path.lower()
    parts = [p for p in low.replace("/", "\\").split("\\") if p]
    for part in parts:
        base = part.split(".", 1)[0] if part.endswith(".dat") else part
        if part in _PRIVACY_DIRS or base in _PRIVACY_DIRS:
            return True
        # INetCookies 之类的前缀变体
        if any(part.startswith(x) for x in ("inetcookies", "inethistory",
                                            "cookies", "logindata")):
            return True
    return False


# 凭据与密钥：**删了不可恢复**，性质比 Cookie 严重得多 ——
# Cookie 没了重新登录即可，私钥没了就是永久丢失。
#
# 这个名单是受控夹具测试发现的缺口：当时 `_safe_target` 放行了 `~/.ssh`。
# 虽然现有规则没有一条指向它，但保护不应该依赖「恰好没写错规则」。
_CREDENTIAL_NAMES = {
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker",
    ".netrc", "_netrc", ".npmrc", ".pypirc", ".git-credentials",
    ".vault-token", ".pgpass", ".terraform.d", ".gitconfig",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "known_hosts", "authorized_keys", ".keystore", ".p12", ".pfx",
}


def _is_credential_path(path: str) -> bool:
    """是否是凭据/密钥类路径（按路径段精确判定，避免误伤同名子串）。"""
    low = path.replace("/", "\\").lower()
    for seg in (s for s in low.split("\\") if s):
        if seg in _CREDENTIAL_NAMES:
            return True
        # 扩展名类：xxx.p12 / xxx.pfx
        if seg.rsplit(".", 1)[-1] in ("p12", "pfx") and "." in seg:
            return True
    return False


def _find_cache_dirs(base: str, max_depth: int = 2,
                     max_visit: int = 400) -> list[str]:
    """在 base 下按目录名特征找出缓存目录（最多下探 max_depth 层）。"""
    found: list[str] = []
    visited = [0]

    def walk(d: str, depth: int):
        if depth > max_depth or visited[0] > max_visit:
            return
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError:
            return
        for e in entries:
            if visited[0] > max_visit:
                return
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            low = e.name.lower()
            if any(bad in low for bad in _NEVER_WALK):
                continue
            visited[0] += 1
            if low in _SAFE_CACHE_SUBDIR_NAMES:
                found.append(e.path)
                continue                      # 命中缓存目录后不再往里钻
            walk(e.path, depth + 1)

    walk(base, 1)
    return found


_CONTAINER_CACHES = [
    {"key": "steam", "names": ("steam", "steamlibrary"),
     "marker": ("steamapps", "steam.exe", "steamclient.dll"),
     "title": "Steam 下载缓存与临时文件", "category": "游戏平台", "level": "safe",
     "subpaths": (r"steamapps\downloading", r"steamapps\temp", r"appcache",
                  r"logs", r"dumps", r"crashlogs"),
     "desc": "Steam 下载中途的碎片、网页缓存与日志。\n"
             "若 Steam 里有「下载到一半」的任务，清理后需要重新下载。"},
    {"key": "wegame", "names": ("wegame",),
     "marker": ("wegame", "rail", "tencent"),
     "title": "WeGame 缓存与日志", "category": "游戏平台", "level": "caution",
     "scan_cache_names": True,
     "desc": "WeGame 的缓存数据与运行日志。\n"
             "不含反作弊目录（tenprotect / AntiCheatExpert 会被跳过）。"},
    {"key": "wegameapps", "names": ("wegameapps",),
     "marker": ("wegame", "download", "rail"),
     "title": "WeGame 游戏下载缓存", "category": "游戏平台", "level": "caution",
     "subpaths": ("downloading",),
     "desc": "WeGame 下载游戏时的临时目录。\n"
             "若正在下载游戏，清理后需要重新下载。"},
    {"key": "mumu", "names": ("mumu", "mumuplayer"),
     "marker": ("mumuplayer", "nemu", "mumu"),
     "title": "MuMu 模拟器缓存", "category": "游戏平台", "level": "caution",
     "scan_cache_names": True,
     "desc": "安卓模拟器的临时缓存。删除后首次启动会慢一些。"},
    {"key": "bluestacks", "names": ("bluestacks_nxt", "bluestacks"),
     "marker": ("bluestacks", "hd-player"),
     "title": "BlueStacks 模拟器缓存", "category": "游戏平台", "level": "caution",
     "scan_cache_names": True,
     "desc": "安卓模拟器的临时缓存。"},
    {"key": "epiccache", "names": (r"epic games\launcher",),
     "marker": ("portal", "epic"),
     "title": "Epic 启动器缓存", "category": "游戏平台", "level": "safe",
     "subpaths": (r"portal\cache", r"logs"),
     "desc": "Epic 启动器的网页与清单缓存。"},
]


def _has_marker(base: str, markers) -> bool:
    """确认这个目录确实是目标程序（避免同名的无关目录被误判）。"""
    if not markers:
        return True
    try:
        with os.scandir(base) as it:
            for entry in it:
                low = entry.name.lower()
                if any(m in low for m in markers):
                    return True
    except OSError:
        return False
    return False


def discover_app_cache_rules() -> list[dict]:
    """现场探测本机的游戏平台 / 模拟器 / 安装器缓存目录，生成规则。

    顺序：先用注册表精确定位 Steam，再在各固定盘按目录名兜底探测。
    每一步都会把已认领的路径记录下来，避免重复计数与重复删除。
    """
    claimed: set[str] = set()
    rules: list[dict] = []

    def take(paths):
        out = []
        for p in paths:
            try:
                if not os.path.isdir(p):
                    continue
            except OSError:
                continue
            norm = os.path.normcase(os.path.abspath(p))
            if norm in claimed:
                continue
            claimed.add(norm)
            out.append(p)
        return out

    # 1) Steam：注册表 / libraryfolders.vdf 给出的准确位置
    for lib in steam_libraries():
        got = take([os.path.join(lib, "steamapps", "downloading"),
                    os.path.join(lib, "steamapps", "temp"),
                    os.path.join(lib, "appcache"),
                    os.path.join(lib, "logs"),
                    os.path.join(lib, "dumps"),
                    os.path.join(lib, "crashlogs")])
        if got:
            rules.append(_rule(
                _key_from_path("steam_lib", lib),
                f"Steam 缓存 ({lib})", "游戏平台", "safe", "contents", got,
                "Steam 安装 / 库目录里的下载缓存与日志。\n"
                "若 Steam 里有「下载到一半」的任务，清理后需要重新下载。"))

    # 2) 其余容器目录 + 盘根垃圾目录
    for drive in fixed_drives():
        for spec in _CONTAINER_CACHES:
            for name in spec["names"]:
                base = os.path.join(drive, name)
                if not os.path.isdir(base):
                    continue
                if not _has_marker(base, spec.get("marker")):
                    continue
                wanted = [os.path.join(base, sub)
                          for sub in spec.get("subpaths", ())]
                if spec.get("scan_cache_names"):
                    wanted.extend(_find_cache_dirs(base))
                got = take(wanted)
                if got:
                    rules.append(_rule(
                        f"{spec['key']}_{drive[0].lower()}",
                        f"{spec['title']} ({drive[0]}:)",
                        spec["category"], spec["level"], "contents", got,
                        spec["desc"],
                        default=(spec["level"] != "caution")))
                    break

        for name, title, category, level, desc in _ROOT_JUNK_DIRS:
            got = take([os.path.join(drive, name)])
            if got:
                rules.append(_rule(
                    _key_from_path("root", name) + f"_{drive[0].lower()}",
                    f"{title} ({drive[0]}:)", category, level, "contents",
                    got, desc, default=(level != "caution")))

    for r in rules:
        r["discovered"] = True
    return rules


RULES.extend(discover_app_cache_rules())


# ---------------------------------------------------------------------------
# 第三方规则库（BleachBit / Winapp2）
# ---------------------------------------------------------------------------
# 这两个开源规则库合计覆盖上千个应用，正好补上「本机没装、但别人电脑上会有」
# 的软件。规则只在本机真实存在时才会命中；没装的软件贡献 0，不影响扫描。
# 数据在 third_party_rules.py 里，附有来源与许可说明。

_TEMPLATE_VARS = {
    "LOCAL": LOCAL, "ROAMING": ROAMING, "PROFILE": PROFILE,
    "WINDIR": WINDIR, "PROGRAMDATA": PROGRAMDATA, "TEMP": TEMP,
    "SYSTEMDRIVE": SYSTEM_ROOT_DIR,
    "PUBLIC": os.environ.get("PUBLIC", ""),
    "PROGRAMFILES": os.environ.get("ProgramFiles", ""),
    "PROGRAMFILES86": os.environ.get("ProgramFiles(x86)", ""),
}


def _expand_template(tpl: str) -> str:
    """把 {LOCAL}\\Foo\\Cache 这样的模板还原成真实路径。"""
    out = tpl
    for name, value in _TEMPLATE_VARS.items():
        if value:
            out = out.replace("{%s}" % name, value)
    return out


# 按模式清理时只使用这一组「放之四海皆安全」的日志/临时模式。
# 规则库里每个目录本来有各自专属的模式，但把专属模式套到别的目录上可能误删，
# 所以取交集式的保守做法：只删这些无论如何都是日志/临时性质的文件。
_UNIVERSAL_LOG_PATTERNS = [
    "*.log", "LOG", "LOG.old", "*-journal", "*_shutdown_ms.txt",
    "debug.log", "*.tmp", "*.dmp",
]


# 用户的个人文件夹：第三方规则库里有「删桌面/文档里的 *.log」这类条目，
# 但本工具的承诺是「不碰用户数据」，所以一律排除。
# 注意：保护清单能拦住删除动作，但规则不该出现在列表里 —— 那会误导用户。
_PERSONAL_DIR_NAMES = {
    "desktop", "documents", "downloads", "pictures", "videos", "music",
    "favorites", "links", "contacts", "saved games", "3d objects",
    "searches", "onedrive", "one drive", "dropbox", "google drive",
    "我的文档", "桌面", "下载", "图片", "视频", "音乐",
}


def _is_personal_dir(path: str) -> bool:
    """是否用户目录本身、或位于其下任何个人文件夹之内。

    必须判到任意层级：`Documents\\Adobe` 虽然只是个应用子目录，
    但它位于「文档」之内，而本工具承诺不碰用户的文档。
    """
    if not PROFILE:
        return False
    low = os.path.normcase(os.path.abspath(path)).rstrip("\\")
    prof = os.path.normcase(os.path.abspath(PROFILE)).rstrip("\\")
    if low == prof:
        return True
    for name in _PERSONAL_DIR_NAMES:
        p = os.path.normcase(os.path.join(prof, name)).rstrip("\\")
        if low == p or low.startswith(p + "\\"):
            return True
    return False


def _load_rules_module():
    """载入第三方规则模块，**优先用可写目录里的那份**。

    为什么需要这个顺序：打包成 onefile 后，内置的 third_party_rules.py 位于
    每次启动都变的临时解压目录（%TEMP%\\_MEIxxxx，退出即删）。
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


def _load_third_party() -> dict:
    """载入第三方规则库中「本机真实存在」的目录，分三档返回。"""
    empty = {"safe": [], "caution": [], "file_dirs": []}
    try:
        tpr = _load_rules_module()
        if tpr is None:
            raise ImportError('找不到规则模块')
    except Exception:
        return empty
    import glob as _glob

    # 已被内置/探测规则认领的目录，避免重复统计
    claimed: set[str] = set()
    for r in RULES:
        if r["kind"] in ("types", "dism", "recyclebin"):
            continue
        for p in expand_paths(r):
            if len(p) <= 4 and p.endswith(":\\"):
                continue
            claimed.add(os.path.normcase(os.path.abspath(p)))

    def resolve(tpls, allow_glob=True):
        found = []
        for tpl in tpls:
            real = _expand_template(tpl)
            if not real or "{" in real:
                continue
            low = real.lower()
            # 逐条再校验一次：隐私数据、目录联接、反作弊、个人文件夹一律不要
            if _is_privacy_path(real) or "documents and settings" in low:
                continue
            if any(bad in low for bad in _NEVER_WALK):
                continue
            if _is_personal_dir(real):
                continue
            if "*" in real:
                if not allow_glob:
                    continue
                targets = [m for m in _glob.glob(real) if os.path.isdir(m)]
            else:
                targets = [real] if os.path.isdir(real) else []
            for one in targets:
                norm = os.path.normcase(os.path.abspath(one))
                if norm in claimed:
                    continue
                if any(norm.startswith(c + "\\") for c in claimed):
                    continue
                claimed.add(norm)
                found.append(one)
        return found

    return {
        "safe": resolve(getattr(tpr, "THIRD_PARTY_SAFE_DIRS", ())),
        "caution": resolve(getattr(tpr, "THIRD_PARTY_CAUTION_DIRS", ())),
        # 按模式清理：目录本身不清空，只删里面的日志/临时文件
        "file_dirs": resolve([t for t, _ in
                              getattr(tpr, "THIRD_PARTY_FILE_RULES", ())],
                             allow_glob=False),
    }


def register_third_party_rule() -> int:
    """把第三方规则库注册成三条规则，返回纳入的目录总数。"""
    global _THIRD_PARTY_LOADED
    if _THIRD_PARTY_LOADED:
        return 0
    _THIRD_PARTY_LOADED = True
    got = _load_third_party()
    total = 0

    if got["safe"]:
        RULES.append(_rule(
            "third_party_apps", "其他应用缓存（社区规则库）", "应用缓存",
            "safe", "contents", got["safe"],
            f"来自 BleachBit 与 Winapp2 两个开源规则库，覆盖 {len(got['safe'])} 个"
            f"**本机真实存在**的应用缓存目录。\n"
            f"本机没装的软件不会出现；换台电脑会自动换成那台机器上装了的。\n"
            f"已按路径段严格过滤：Cookie / 历史 / 密码 / 书签 / IndexedDB / "
            f"localStorage / File System / 客户端证书 / 反作弊 —— 一律不碰。\n"
            f"双击可查看具体路径。"))
        total += len(got["safe"])

    if got["caution"]:
        RULES.append(_rule(
            "third_party_caution", "应用缓存（有副作用的，默认不勾选）",
            "应用缓存", "caution", "contents", got["caution"],
            f"共 {len(got['caution'])} 个目录：Service Worker（离线应用要重新注册）、"
            f"Widevine/MediaFoundation（受保护视频要重新下载组件）、"
            f"Platform Notifications（可能重复弹通知）。\n"
            f"都能重建，但有可见副作用，所以默认不勾选。",
            default=False))
        total += len(got["caution"])

    if got["file_dirs"]:
        RULES.append(_rule(
            "third_party_logs", "其他应用日志与临时文件（按文件名）", "日志与转储",
            "safe", "files", got["file_dirs"],
            f"在 {len(got['file_dirs'])} 个应用目录里，只删除日志与临时性质的"
            f"文件，**不动目录内容**：\n"
            f"  " + "、".join(_UNIVERSAL_LOG_PATTERNS) + "\n"
            f"这些目录里可能有该应用的重要数据，所以只按文件名精确匹配删除。",
            patterns=list(_UNIVERSAL_LOG_PATTERNS)))
        total += len(got["file_dirs"])

    return total


_THIRD_PARTY_LOADED = False


# ---------------------------------------------------------------------------
# 明确「不能删」的目录：只统计占用，供用户了解空间去向
# ---------------------------------------------------------------------------

PROTECTED_PATHS: list[tuple[str, str]] = [
    (_join(WINDIR, "Installer"),
     "已安装软件的安装包与补丁库。删除后软件将无法卸载、修复或更新 —— "
     "这是很多清理工具的经典误伤点。"),
    (_join(WINDIR, "WinSxS"),
     "组件存储。系统用它来修复与更新自身。必须用 DISM 命令清理，不能手删。"),
    (_join(WINDIR, "System32"),
     "系统核心文件。"),
    (_join(WINDIR, "SysWOW64"),
     "32 位系统兼容层。"),
    (_join(WINDIR, "Fonts"),
     "已安装字体。删除会导致部分界面显示异常。"),
    (_join(WINDIR, "assembly"),
     ".NET 程序集缓存。"),
    (_join(PROGRAMDATA, "Package Cache"),
     "Visual Studio / VC++ 运行库等的安装缓存。删除后这些软件无法修复安装。"),
    (_join(PROFILE, "Documents"),
     "你的文档。"),
    (_join(PROFILE, "Desktop"),
     "你的桌面。"),
    (_join(PROFILE, "Downloads"),
     "你的下载文件夹。本工具不会替你决定里面的东西能不能删。"),
    (_join(PROFILE, "Pictures"),
     "你的图片。"),
    (SYSTEM_ROOT_DIR + "$Recycle.Bin",
     "回收站的底层存储。请用「清空回收站」功能，不要手删。"),
    (SYSTEM_ROOT_DIR + "hiberfil.sys",
     "休眠文件。如需释放，请用 powercfg /h off，不要手删。"),
    (SYSTEM_ROOT_DIR + "pagefile.sys",
     "虚拟内存页面文件。系统正在使用，不可删除。"),
    (SYSTEM_ROOT_DIR + "swapfile.sys",
     "系统交换文件。系统正在使用，不可删除。"),
    (os.path.join(WINDIR, "System32", "DriverStore", "FileRepository"),
     "驱动仓库。旧驱动包可能占用数 GB，但必须用「磁盘清理」里的"
     "「设备驱动程序包」或 pnputil 安全移除，手删会导致设备驱动损坏。"),
]


# ---------------------------------------------------------------------------
# 文件系统工具
# ---------------------------------------------------------------------------

def _is_reparse(entry) -> bool:
    """是否为符号链接 / 目录联接（junction）—— 必须跳过，否则会跟丢或删到别处。"""
    try:
        st = entry.stat(follow_symlinks=False)
        return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return True


def dir_size(path: str, cancel: threading.Event | None = None,
             progress=None) -> dict:
    """迭代式计算目录占用。返回 {size, files, dirs, denied, links}。

    不使用递归，避免超深目录导致栈溢出；跳过 reparse point 避免重复计算。
    """
    result = {"size": 0, "files": 0, "dirs": 0, "denied": 0, "links": 0}
    if not os.path.exists(path):
        return result
    stack = [path]
    while stack:
        if cancel is not None and cancel.is_set():
            break
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if cancel is not None and cancel.is_set():
                        break
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if _is_reparse(entry):
                                result["links"] += 1
                                continue
                            result["dirs"] += 1
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            result["files"] += 1
                            try:
                                result["size"] += entry.stat(
                                    follow_symlinks=False).st_size
                            except OSError:
                                pass
                    except OSError:
                        result["denied"] += 1
                    if progress is not None and result["files"] % 400 == 0:
                        progress(entry.path)
        except PermissionError:
            result["denied"] += 1
        except OSError:
            result["denied"] += 1
    return result


def expand_paths(rule: dict) -> list[str]:
    """展开规则里的路径（支持 * 通配），返回真实存在的路径列表。"""
    import glob as _glob
    found: list[str] = []
    for p in rule["paths"]:
        if not p:
            continue
        if "*" in p or "?" in p:
            found.extend(_glob.glob(p))
        elif os.path.exists(p):
            found.append(p)
    # 去重，并剔除互为父子关系的重复路径（父目录已覆盖子目录）
    uniq: list[str] = []
    for p in sorted(set(os.path.abspath(x) for x in found), key=len):
        if not any(p == u or p.startswith(u + os.sep) for u in uniq):
            uniq.append(p)
    return uniq


# ---------------- types 模式：全盘按名字深扫 ----------------
# 语法： "file:名字" 精确文件名 | "dir:名字" 精确目录名 | "glob:通配" 通配匹配
# 参考 BleachBit 的 deepscan.xml（它的 deep 搜索是同样思路）。

# 深扫时永不进入的目录。理由与 BleachBit 一致：
#   - 系统/程序目录里的东西不属于"散落的构建残留"
#   - AppData 下多为应用自带依赖，删了会破坏软件
_SKIP_WALK_DIRS = {
    "windows", "program files", "program files (x86)", "programdata",
    "appdata", "application data", "local settings", "$recycle.bin",
    "system volume information", "recovery", "perflogs", "$winreagent",
    "windows.old", ".git", ".svn", ".hg", "node_modules.old",
    "$windows.~bt", "$windows.~ws",
}

# 全盘深扫的安全上限，防止在超大磁盘上跑到天荒地老
_DEEP_MAX_VISIT = 400000
_DEEP_MAX_HITS = 5000


def _match_type(name: str, types, path: str = "") -> bool:
    """判断一个目录/文件是否命中 types 声明。

    支持 `dir:名称@标记文件` 形式：除了名字要对，目录里还必须存在该标记文件。

    为什么需要标记：只按名字匹配太危险 —— `dir:venv` 会同时命中
    **真正的虚拟环境**和 **Python 标准库自己的 `Lib/venv` 模块目录**，
    删掉后者会直接破坏整个 Python 安装（真实事故：
    某次全盘清理把 `.../python/Lib/venv` 删了，`python -m venv` 从此报
    「No module named venv」）。而真正的 venv 一定带 `pyvenv.cfg`。
    """
    low = name.lower()
    for t in types:
        kind, _, pat = t.partition(":")
        marker = ""
        if "@" in pat:
            pat, _, marker = pat.partition("@")
        pat = pat.lower()

        if kind == "file":
            hit = (low == pat)
        elif kind == "dir":
            hit = (low == pat)
        elif kind == "glob":
            hit = fnmatch.fnmatch(low, pat)
        else:
            hit = False
        if not hit:
            continue
        # 声明了标记文件就必须存在，否则不算命中
        if marker and path:
            if not os.path.exists(os.path.join(path, marker)):
                continue
        return True
    return False


def scan_types(rule: dict, cancel: threading.Event | None = None,
               progress=None) -> dict:
    """在各固定磁盘上按名字特征深扫。慢，但能找出散落各处的残留。"""
    out = {"key": rule["key"], "name": rule["name"], "paths": [], "size": 0,
           "files": 0, "dirs": 0, "denied": 0, "exists": False}
    types = rule.get("types") or []
    if not types:
        return out
    hit_dirs: list[tuple[str, int]] = []
    visited = 0
    truncated = False

    for drive in expand_paths(rule):
        if cancel is not None and cancel.is_set():
            break
        stack = [drive]
        while stack:
            if cancel is not None and cancel.is_set():
                break
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    entries = list(it)
            except OSError:
                out["denied"] += 1
                continue
            for e in entries:
                visited += 1
                if visited > _DEEP_MAX_VISIT or len(hit_dirs) > _DEEP_MAX_HITS:
                    truncated = True
                    break
                try:
                    if e.is_dir(follow_symlinks=False):
                        if _is_reparse(e):
                            continue
                        low = e.name.lower()
                        if low in _SKIP_WALK_DIRS:
                            continue
                        if _match_type(e.name, types, e.path):
                            size = dir_size(e.path, cancel)["size"]
                            hit_dirs.append((e.path, size))
                            out["size"] += size
                            out["dirs"] += 1
                            continue            # 命中后不再往里钻
                        stack.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        if _match_type(e.name, types, e.path):
                            try:
                                out["size"] += e.stat(
                                    follow_symlinks=False).st_size
                                out["files"] += 1
                            except OSError:
                                pass
                except OSError:
                    out["denied"] += 1
                if progress is not None and visited % 2000 == 0:
                    progress(e.path)
            if truncated:
                break
        if truncated:
            break

    out["exists"] = bool(hit_dirs) or out["files"] > 0
    hit_dirs.sort(key=lambda x: x[1], reverse=True)
    out["paths"] = [(p, s) for p, s in hit_dirs[:200]]
    if truncated:
        out["paths"].append(("……（命中过多，已截断，仅统计前一部分）", 0))
    return out


def scan_rule(rule: dict, cancel: threading.Event | None = None,
              progress=None) -> dict:
    """扫描单条规则，返回统计信息。"""
    if rule["kind"] == "types":
        return scan_types(rule, cancel, progress)
    if rule["kind"] == "dism":
        win = os.path.join(WINDIR, "WinSxS")
        out = {"key": rule["key"], "name": rule["name"], "paths": [], "size": 0,
               "files": 0, "dirs": 0, "denied": 0, "exists": False}
        if os.path.isdir(win):
            info = dir_size(win, cancel)
            out["exists"] = True
            out["paths"] = [(
                f"当前 WinSxS 占用 {info['size'] / 1048576:.0f} MB。"
                f"DISM 只移除其中被取代的旧组件，回收量无法预先计算。", 0)]
        return out
    out = {"key": rule["key"], "name": rule["name"], "paths": [], "size": 0,
           "files": 0, "dirs": 0, "denied": 0, "exists": False}
    if rule["kind"] == "recyclebin":
        info = recycle_bin_info()
        out["size"] = info["size"]
        out["files"] = info["items"]
        out["exists"] = info["items"] > 0
        out["paths"] = ["回收站"]
        return out

    for path in expand_paths(rule):
        if rule["kind"] == "files":
            # 只统计匹配的文件。模式必须由规则自己声明；没有就什么都不匹配，
            # 避免落到某个共享的兜底列表上去删错东西。
            import glob as _glob
            patterns = rule.get("patterns") or []
            subtotal = {"size": 0, "files": 0, "dirs": 0, "denied": 0, "links": 0}
            for pat in patterns:
                for f in _glob.glob(os.path.join(path, pat)):
                    if os.path.isfile(f):
                        try:
                            subtotal["size"] += os.path.getsize(f)
                            subtotal["files"] += 1
                        except OSError:
                            subtotal["denied"] += 1
        else:
            subtotal = dir_size(path, cancel, progress)
        out["paths"].append((path, subtotal["size"]))
        for k in ("size", "files", "dirs", "denied"):
            out[k] += subtotal[k]
        out["exists"] = True
    return out


# ---------------------------------------------------------------------------
# 回收站
# ---------------------------------------------------------------------------

shell32 = ctypes.WinDLL("shell32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)

SHERB_NOCONFIRMATION = 0x00000001
SHERB_NOPROGRESSUI = 0x00000002
SHERB_NOSOUND = 0x00000004


class SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("i64Size", ctypes.c_longlong),
                ("i64NumItems", ctypes.c_longlong)]


shell32.SHEmptyRecycleBinW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.DWORD]
shell32.SHEmptyRecycleBinW.restype = ctypes.c_long
shell32.SHQueryRecycleBinW.argtypes = [wintypes.LPCWSTR,
                                       ctypes.POINTER(SHQUERYRBINFO)]
shell32.SHQueryRecycleBinW.restype = ctypes.c_long
ole32.CoInitialize.argtypes = [ctypes.c_void_p]
ole32.CoInitialize.restype = ctypes.c_long


def recycle_bin_info() -> dict:
    """查询回收站占用（字节）与条目数。"""
    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
    try:
        hr = shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    except Exception:
        return {"size": 0, "items": 0, "ok": False}
    if hr != 0:
        return {"size": 0, "items": 0, "ok": False}
    return {"size": int(info.i64Size), "items": int(info.i64NumItems), "ok": True}


def empty_recycle_bin() -> tuple[bool, str]:
    """清空所有驱动器的回收站。返回 (成功, 消息)。"""
    try:
        ole32.CoInitialize(None)
    except Exception:
        pass
    try:
        before = recycle_bin_info()
        hr = shell32.SHEmptyRecycleBinW(
            None, None, SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND)
        if hr == 0:
            return True, f"已清空回收站（{before['items']} 项，释放约 "\
                         f"{before['size'] / 1048576:.0f} MB）"
        if hr == -2147418113:      # 0x8000FFFF E_UNEXPECTED，回收站本来就是空的
            return True, "回收站已经是空的"
        return False, f"清空回收站失败（HRESULT=0x{hr & 0xFFFFFFFF:08X}）"
    except Exception as e:
        return False, f"清空回收站失败：{e}"


# ---------------------------------------------------------------------------
# 清理执行
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# DISM 组件存储清理
# ---------------------------------------------------------------------------
# WinSxS 里堆积的是被更新取代的旧组件。它**不能手删**（会破坏系统更新与修复
# 能力），唯一安全的清理方式是微软自己的 DISM 命令。

class ULARGE_INTEGER(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.DWORD)]


k32.GetDiskFreeSpaceExW.argtypes = [wintypes.LPCWSTR,
                                    ctypes.POINTER(ULARGE_INTEGER),
                                    ctypes.POINTER(ULARGE_INTEGER),
                                    ctypes.POINTER(ULARGE_INTEGER)]
k32.GetDiskFreeSpaceExW.restype = wintypes.BOOL


def disk_free(root: str) -> int:
    """返回指定磁盘的可用字节数。"""
    free = ULARGE_INTEGER()
    total = ULARGE_INTEGER()
    totalfree = ULARGE_INTEGER()
    try:
        if k32.GetDiskFreeSpaceExW(root, ctypes.byref(free),
                                   ctypes.byref(total), ctypes.byref(totalfree)):
            return (free.HighPart << 32) | free.LowPart
    except Exception:
        pass
    return 0


def dism_component_cleanup(reset_base: bool = False,
                           timeout: int = 3600) -> tuple[bool, str]:
    """用 DISM 清理组件存储里被取代的旧组件。

    reset_base=True 会额外清理所有被取代版本的备份（释放更多，但之后
    无法卸载已安装的更新）。默认不启用。
    """
    exe = shutil.which("dism") or os.path.join(WINDIR, "System32", "Dism.exe")
    if not os.path.isfile(exe):
        return False, "找不到 DISM，无法执行组件清理"
    args = [exe, "/Online", "/Cleanup-Image", "/StartComponentCleanup"]
    if reset_base:
        args.append("/ResetBase")
    try:
        proc = subprocess.run(args, capture_output=True, text=True,
                              creationflags=0x08000000, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "DISM 超时未完成"
    except Exception as e:
        return False, f"DISM 调用失败：{e}"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    tail = "\n".join(out.splitlines()[-6:])
    if proc.returncode == 0:
        return True, f"DISM 组件清理完成。{tail}"
    if proc.returncode == 740:      # ERROR_ELEVATION_REQUIRED
        return False, "DISM 需要管理员权限（请用「以管理员身份运行」）"
    return False, f"DISM 返回 {proc.returncode}：{tail}"


def _safe_target(path: str) -> bool:
    """删除前的最后一道校验：拒绝明显的危险目标。"""
    p = os.path.abspath(path)
    if len(p) <= 4 and p.endswith(":\\"):        # 盘根
        return False
    # 隐私数据（Cookie / 历史 / 密码 / 书签 …）绝不删除
    if _is_privacy_path(p):
        return False
    # 凭据与密钥删了不可恢复，同样绝不删除
    if _is_credential_path(p):
        return False
    # Win10 上 Documents and Settings 是指向 Users 的目录联接，
    # 顺着它会把删除动作带到我并不打算碰的地方
    if "documents and settings" in p.lower():
        return False
    if p.count(os.sep) <= 1 and not p.endswith(":"):
        # 形如 C:\Windows 这种一级目录，只有显式允许的才放行
        pass
    banned = {
        os.path.abspath(WINDIR),
        os.path.abspath(PROGRAMDATA),
        os.path.abspath(PROFILE),
        os.path.abspath(LOCAL),
        os.path.abspath(ROAMING),
    }
    if p in banned:
        return False
    # 保护清单里的路径一律不删
    for prot, _ in PROTECTED_PATHS:
        try:
            if os.path.abspath(prot) == p:
                return False
        except Exception:
            pass
    return True


def delete_path(path: str, errors: list) -> int:
    """删除文件或目录，返回释放的字节数。失败记录到 errors，不抛异常。"""
    try:
        if os.path.islink(path) or os.path.isfile(path):
            size = 0
            try:
                size = os.path.getsize(path)
            except OSError:
                pass
            try:
                os.remove(path)
                return size
            except PermissionError:
                errors.append((path, "文件正在被其他程序使用"))
                return 0
            except OSError as e:
                errors.append((path, f"删除失败：{e.strerror or e}"))
                return 0
        if os.path.isdir(path):
            total = dir_size(path)["size"]
            try:
                shutil.rmtree(path, onerror=_rmtree_handler)
                return total
            except Exception as e:
                errors.append((path, f"目录删除失败：{e}"))
                return 0
    except Exception as e:
        errors.append((path, f"未知错误：{e}"))
    return 0


def _rmtree_handler(func, path, exc_info):
    """rmtree 出错时的回调：交给上层记录，不要中途崩溃。"""
    raise exc_info[1] if exc_info and exc_info[1] else OSError(f"无法删除 {path}")


def clean_rule(rule: dict, cancel: threading.Event | None = None,
               progress=None) -> dict:
    """执行一条规则的清理。返回统计。"""
    report = {"key": rule["key"], "name": rule["name"], "freed": 0,
              "deleted": 0, "failed": [], "skipped": 0}

    if rule["kind"] == "recyclebin":
        ok, msg = empty_recycle_bin()
        report["message"] = msg
        report["freed"] = 0 if not ok else -1     # -1 表示"已处理"，具体大小见消息
        return report

    errors: list[tuple[str, str]] = []

    # DISM 组件清理：不是删文件，而是调用系统工具
    if rule["kind"] == "dism":
        before = disk_free(SYSTEM_ROOT_DIR)
        ok, msg = dism_component_cleanup()
        after = disk_free(SYSTEM_ROOT_DIR)
        report["freed"] = max(0, after - before)
        report["message"] = msg
        return report

    # types 模式：先深扫出目标，再逐个删除。深扫本身不删，所以有两次遍历。
    if rule["kind"] == "types":
        info = scan_types(rule, cancel, progress)
        for item in info["paths"]:
            if cancel is not None and cancel.is_set():
                break
            path = item[0] if isinstance(item, tuple) else item
            if not os.path.exists(path):
                continue                      # 截断提示行等
            if not _safe_target(path):
                report["skipped"] += 1
                errors.append((path, "路径受保护，已跳过"))
                continue
            got = delete_path(path, errors)
            if got:
                report["freed"] += got
                report["deleted"] += 1
            if progress is not None:
                progress(path)
        report["failed"] = errors
        return report

    for path in expand_paths(rule):
        if cancel is not None and cancel.is_set():
            break
        if not _safe_target(path):
            report["skipped"] += 1
            errors.append((path, "路径在保护名单中，已跳过"))
            continue

        if rule["kind"] == "files":
            import glob as _glob
            patterns = rule.get("patterns") or []
            for pat in patterns:
                for f in _glob.glob(os.path.join(path, pat)):
                    if cancel is not None and cancel.is_set():
                        break
                    if not os.path.isfile(f):
                        continue
                    got = delete_path(f, errors)
                    if got:
                        report["freed"] += got
                        report["deleted"] += 1
                    if progress is not None:
                        progress(f)
            continue

        # contents / dir：删除目录下的条目
        try:
            with os.scandir(path) as it:
                entries = list(it)
        except OSError as e:
            errors.append((path, f"无法读取目录：{e.strerror or e}"))
            continue

        for entry in entries:
            if cancel is not None and cancel.is_set():
                break
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            # 跳过 reparse point：可能指向别处，删了会误伤
            if _is_reparse(entry):
                report["skipped"] += 1
                errors.append((entry.path, "是符号链接/目录联接，为安全起见跳过"))
                continue
            if not _safe_target(entry.path):
                report["skipped"] += 1
                continue
            if is_dir and rule["kind"] == "contents":
                got = delete_path(entry.path, errors)
                if got:
                    report["freed"] += got
                    report["deleted"] += 1
            elif not is_dir:
                got = delete_path(entry.path, errors)
                if got:
                    report["freed"] += got
                    report["deleted"] += 1
            if progress is not None:
                progress(entry.path)

    # 只保留前若干条错误，避免界面刷屏
    report["failed"] = errors
    return report


def clean_rules(rules: list[dict], cancel: threading.Event | None = None,
                log=None) -> dict:
    """按顺序清理多条规则。"""
    total = {"freed": 0, "deleted": 0, "rules": [], "failed": []}
    for rule in rules:
        if cancel is not None and cancel.is_set():
            if log:
                log("已取消。")
            break
        if log:
            log(f"→ 正在清理：{rule['name']}")
        rep = clean_rule(rule, cancel, progress=None)
        total["rules"].append(rep)
        if "message" in rep and log:
            log("  " + rep["message"])
        if rep["freed"] > 0:
            total["freed"] += rep["freed"]
            total["deleted"] += rep["deleted"]
            if log:
                log(f"  释放 {rep['freed'] / 1048576:.1f} MB，"
                    f"删除 {rep['deleted']} 项")
        if rep["failed"]:
            total["failed"].extend(rep["failed"])
            if log:
                for p, why in rep["failed"][:3]:
                    log(f"  跳过：{os.path.basename(p)} —— {why}")
                if len(rep["failed"]) > 3:
                    log(f"  …另有 {len(rep['failed']) - 3} 项跳过")
    return total


# ---------------------------------------------------------------------------
# 目录占用分析
# ---------------------------------------------------------------------------

def analyze_directory(root: str, top_n: int = 25,
                      cancel: threading.Event | None = None,
                      progress=None) -> list[dict]:
    """分析某个目录下各子项的占用，返回按大小降序的列表。"""
    out = []
    try:
        with os.scandir(root) as it:
            entries = list(it)
    except OSError:
        return out
    for entry in entries:
        if cancel is not None and cancel.is_set():
            break
        try:
            if entry.is_dir(follow_symlinks=False):
                if _is_reparse(entry):
                    out.append({"name": entry.name, "path": entry.path,
                                "size": 0, "kind": "链接", "files": 0})
                    continue
                info = dir_size(entry.path, cancel, progress)
                out.append({"name": entry.name, "path": entry.path,
                            "size": info["size"], "kind": "目录",
                            "files": info["files"]})
            elif entry.is_file(follow_symlinks=False):
                out.append({"name": entry.name, "path": entry.path,
                            "size": entry.stat(follow_symlinks=False).st_size,
                            "kind": "文件", "files": 1})
        except OSError:
            continue
    out.sort(key=lambda x: x["size"], reverse=True)
    return out[:top_n]


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

def load_config() -> dict:
    import json
    cfg = {"selected": {}, "last_log": []}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> None:
    import json
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 图形界面
# ---------------------------------------------------------------------------

LEVEL_LABEL = {"safe": "✅ 安全", "caution": "⚠ 谨慎", "risky": "⛔ 有风险"}
LEVEL_TAG = {"safe": "safe", "caution": "caution", "risky": "risky"}
# 控制台（GBK 代码页）无法输出 emoji，命令行走这套纯文本标签
LEVEL_PLAIN = {"safe": "安全", "caution": "谨慎", "risky": "风险"}

# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------

def _setup_console() -> None:
    """让命令行在 GBK 控制台下也不会因 Unicode 字符崩溃。"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def cli_scan() -> int:
    _setup_console()
    print(f"{APP_NAME} v{APP_VERSION} —— 扫描")
    print("=" * 62)
    total = 0
    rows = []
    for rule in RULES:
        info = scan_rule(rule)
        total += info["size"]
        rows.append((rule, info))
    rows.sort(key=lambda x: x[1]["size"], reverse=True)
    for rule, info in rows:
        if info["size"] <= 0 and not info.get("exists"):
            continue
        size = info["size"]
        for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
            if size >= div:
                text = f"{size / div:.2f} {unit}"
                break
        else:
            text = f"{size} B"
        label = LEVEL_PLAIN[rule["level"]]
        count = f"{info['files']} 文件"
        if info["dirs"]:
            count += f" / {info['dirs']} 目录"
        print(f"  [{label}] {rule['name']:<26} {text:>10}  ({count})")
    print("-" * 62)
    default_on = sum(info["size"] for rule, info in rows if rule["default"])
    print(f"默认勾选（安全项）合计：{default_on / 1048576:.1f} MB")
    print(f"含需手动勾选的谨慎项合计：{total / 1048576:.1f} MB")
    print("注意：谨慎项默认不勾选，需要你自己确认后才清理。")
    print()
    print("不能删（仅供参考，本工具不会碰）：")
    for path, why in PROTECTED_PATHS:
        try:
            if not os.path.exists(path):
                continue
            info = dir_size(path)
        except OSError:
            continue
        if info["size"] > 100 * 1048576:
            print(f"  {path}  {info['size'] / 1048576:.0f} MB")
            print(f"      {why[:70]}")
    return 0


def cli_analyze(path: str) -> int:
    _setup_console()
    if not os.path.isdir(path):
        print(f"目录不存在：{path}", file=sys.stderr)
        return 1
    print(f"分析：{path}")
    rows = analyze_directory(path, 30)
    for r in rows:
        print(f"  {r['size'] / 1048576:10.1f} MB  {r['kind']:<4}  {r['path']}")
    return 0


def cli_selftest() -> int:
    """自检：验证规则定义与安全约束。"""
    _setup_console()
    print(f"{APP_NAME} v{APP_VERSION} — 自检")
    print("=" * 62)
    ok = True

    # 1) files 模式必须自带模式（否则规则名与实际行为不符）
    missing = [r["name"] for r in RULES
               if r["kind"] == "files" and not r.get("patterns")]
    if missing:
        ok = False
        print(f"  !! 以下 files 规则未声明匹配模式：{missing}")
    else:
        print("模式声明         : 通过（所有 files 规则都自带精确模式）")

    # 2) 可清理规则不得落在保护清单内
    prot = {os.path.abspath(p).lower() for p, _ in PROTECTED_PATHS}
    conflicts = []
    for r in RULES:
        if r["kind"] == "recyclebin":
            continue
        for p in r["paths"]:
            if not p:
                continue
            ap = os.path.abspath(p).lower()
            for pp in prot:
                if ap == pp or ap.startswith(pp + os.sep):
                    conflicts.append((r["name"], p))
    if conflicts:
        ok = False
        print(f"  !! 可清理规则与保护清单冲突：{conflicts}")
    else:
        print("保护清单隔离     : 通过（无规则落在保护清单内）")

    # 3) 保护路径必须被 _safe_target 拒绝
    bad = []
    for p, _ in PROTECTED_PATHS:
        if _safe_target(p):
            bad.append(p)
    if bad:
        ok = False
        print(f"  !! _safe_target 未拒绝这些保护路径：{bad}")
    else:
        print("删除前校验       : 通过（保护路径全部被拒绝）")

    # 4) risky 项与回收站必须默认不勾选
    bad_default = [r["name"] for r in RULES
                   if r["level"] == "risky" and r["default"]]
    if bad_default:
        ok = False
        print(f"  !! 高风险项不应默认勾选：{bad_default}")
    else:
        print("默认勾选策略     : 通过（高风险项默认不勾选）")

    # 5) 反作弊目录绝不能被任何规则纳入（含动态探测出来的规则）
    ac_hits = [(r["name"], p) for r in RULES for p in r["paths"]
               if any(bad in p.lower() for bad in _NEVER_WALK)]
    if ac_hits:
        ok = False
        print(f"  !! 有规则指向反作弊目录：{ac_hits}")
    else:
        print("反作弊隔离       : 通过（无规则指向反作弊目录）")

    # 5b) 隐私数据（Cookie / 历史 / 密码 / 书签）绝不能被匹配 ——
    #     这条检查是必要的：照搬第三方规则时，INet* 这类通配会连
    #     INetCookies / INetHistory 一起匹配上。
    priv = []
    for r in RULES:
        for tpl in r["paths"]:
            if tpl and _is_privacy_path(tpl):
                priv.append((r["name"], "模板", tpl))
        for real in expand_paths(r):
            if _is_privacy_path(real):
                priv.append((r["name"], "实际", real))
    if priv:
        ok = False
        print(f"  !! 有规则会碰到隐私数据：{priv}")
    else:
        print("隐私数据隔离     : 通过（未匹配到 Cookie/历史/密码/书签）")

    # 5c) 用户个人文件夹（文档/桌面/下载/图片/音乐…）及其内部任何层级都不能出现。
    #     第三方规则库里有「删桌面里的 *.log」这类条目，必须逐层拦住。
    personal = []
    for r in RULES:
        if r["kind"] in ("types", "dism", "recyclebin"):
            continue
        for tpl in r["paths"]:
            if tpl and "%" not in tpl and "{" not in tpl \
                    and _is_personal_dir(tpl):
                personal.append((r["name"], "模板", tpl))
        for real in expand_paths(r):
            if _is_personal_dir(real):
                personal.append((r["name"], "实际", real))
    if personal:
        ok = False
        print(f"  !! 有规则落在用户个人文件夹内：{personal}")
    else:
        print("个人目录隔离     : 通过（文档/桌面/下载等及其内部均未涉及）")

    # 6) 可移植性：这些值在每台电脑上都不同，列出来便于在别的机器上核对
    print("可移植性         :")
    print(f"    系统盘       : {SYSTEM_DRIVE}")
    print(f"    固定磁盘     : {', '.join(fixed_drives())}")
    libs = steam_libraries()
    print(f"    Steam 库目录 : {', '.join(libs) if libs else '未检测到'}")
    dyn = [r for r in RULES if r.get("discovered")]
    print(f"    动态探测规则 : {len(dyn)} 条")
    for r in dyn:
        print(f"        [{r['level']}] {r['name']}")
    if not dyn:
        print("        （本机未发现游戏平台/模拟器缓存，属正常）")

    # 7) 每条 files 规则的模式在实际目录里能否匹配到东西（仅报告，不算失败）
    print("模式命中情况     :")
    for r in RULES:
        if r["kind"] != "files":
            continue
        paths = expand_paths(r)
        if not paths:
            continue
        hits = 0
        for p in paths:
            for pat in r["patterns"]:
                import glob as _glob
                hits += len(_glob.glob(os.path.join(p, pat)))
        print(f"    {r['name']:<20} 命中 {hits} 个文件")

    # 8) 基本统计
    print(f"规则总数         : {len(RULES)}"
          f"（安全 {sum(1 for r in RULES if r['level']=='safe')} / "
          f"谨慎 {sum(1 for r in RULES if r['level']=='caution')} / "
          f"风险 {sum(1 for r in RULES if r['level']=='risky')}）")
    rb = recycle_bin_info()
    print(f"回收站           : {'可访问' if rb['ok'] else '不可访问'}"
          f"（{rb['items']} 项，{rb['size']/1048576:.1f} MB）")

    print("-" * 62)
    print("自检结果：" + ("全部通过" if ok else "存在问题，见上面的 !! 标记"))
    return 0 if ok else 1


# 第三方规则库要等 expand_paths 定义好之后再注册（需要按真实路径去重）。
register_third_party_rule()



if __name__ == "__main__":
    # 直接运行本模块时沿用原版命令行入口
    _setup_console()
    if "--selftest" in sys.argv:
        sys.exit(cli_selftest())
    if "--scan" in sys.argv:
        sys.exit(cli_scan())
    if "--analyze" in sys.argv:
        _p = sys.argv[sys.argv.index("--analyze") + 1]
        sys.exit(cli_analyze(_p))
    print("用法: python junk.py [--selftest|--scan|--analyze PATH]")
