# -*- coding: utf-8 -*-
"""
GameBoost —— Windows 游戏内存优化 / 后台进程清理工具

设计目标：在启动游戏之前，把不需要的后台程序关掉、把被缓存占住的内存还回来，
让游戏能拿到更多物理内存和更少的 CPU/磁盘竞争，从而让帧率更稳。

零第三方依赖：只用 Python 标准库 + ctypes 调用 Win32 API（不需要 psutil）。

安全模型（三道锁）：
  1. 硬保护名单 PROTECTED —— 系统关键进程、杀毒软件、输入法、音频、显卡驱动、
     远程控制、本工具自身及其父进程链。这些进程永远不会被本工具结束。
  2. 分级名单 —— TIER_SAFE（默认勾选，关掉无任何数据风险）/ TIER_OPTIONAL
     （默认不勾选，可能正在用，例如微信、浏览器）。
  3. 反作弊保护 —— 反作弊进程既不会被结束，也不会被"清理工作集"
     （改动反作弊进程的内存可能触发封号或导致游戏崩溃）。

命令行：
  python gameboost.py              启动图形界面
  python gameboost.py --selftest   不开界面，自检所有底层 API 是否可用
  python gameboost.py --report     打印当前内存与可优化进程清单
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import winreg
from ctypes import wintypes

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except Exception:  # pragma: no cover - 允许在无 tkinter 环境下跑 --selftest
    tk = None

APP_NAME = "GameBoost 游戏加速器"
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
CONFIG_PATH = os.path.join(SCRIPT_DIR, "gameboost_config.json")

# ---------------------------------------------------------------------------
# 名单定义
# ---------------------------------------------------------------------------

# 硬保护：绝不允许结束 / 绝不清理工作集
PROTECTED: dict[str, str] = {
    # 内核与系统
    "system": "系统内核", "registry": "注册表", "memory compression": "内存压缩",
    "idle": "空闲进程", "secure system": "安全系统",
    "smss.exe": "会话管理器", "csrss.exe": "客户端服务", "wininit.exe": "Windows 初始化",
    "winlogon.exe": "登录管理", "services.exe": "服务控制", "lsass.exe": "本地安全认证",
    "svchost.exe": "系统服务宿主", "fontdrvhost.exe": "字体驱动宿主",
    "dwm.exe": "桌面窗口管理器(合成/垂直同步)", "conhost.exe": "控制台宿主",
    "wudfhost.exe": "驱动宿主", "spoolsv.exe": "打印后台", "audiodg.exe": "音频引擎",
    "sihost.exe": "外壳基础结构", "startmenuexperiencehost.exe": "开始菜单",
    "shellexperiencehost.exe": "外壳体验", "searchhost.exe": "搜索宿主", "dllhost.exe": "COM 代理",
    "taskhostw.exe": "任务宿主", "runtimebroker.exe": "运行时代理",
    "ctfmon.exe": "输入法框架", "textinputhost.exe": "输入法(触摸键盘)",
    "chsime.exe": "微软拼音", "msctfime.exe": "输入法", "sogoucloud.exe": "搜狗输入法云",
    # 安全软件（杀掉会导致机器失去防护，甚至蓝屏）
    "msmpeng.exe": "Windows Defender 反恶意软件", "nissrv.exe": "Defender 扫描",
    "securityhealthservice.exe": "Windows 安全中心", "securityhealthsystray.exe": "安全中心托盘",
    "hipsdaemon.exe": "火绒安全-主程序", "hipstray.exe": "火绒安全-托盘",
    "usysdiag.exe": "火绒-安全诊断",
    "360tray.exe": "360 安全卫士", "zhudongfangyu.exe": "360 主动防御", "360sd.exe": "360 杀毒",
    "qqpctray.exe": "腾讯电脑管家", "qqpcmgr.exe": "腾讯电脑管家",
    "kxetray.exe": "金山毒霸", "kwsprotect64.exe": "金山毒霸",
    "avp.exe": "卡巴斯基", "avastui.exe": "Avast", "avgui.exe": "AVG",
    # 音频 / 显卡 / 触控板等硬件驱动配套（关掉会没声音或掉帧）
    "rtkauduservice64.exe": "Realtek 音频服务", "rtkngui64.exe": "Realtek 音频面板",
    "nvcontainer.exe": "NVIDIA 容器服务", "nvsphelper64.exe": "NVIDIA 捕捉助手",
    "nvidia share.exe": "NVIDIA 覆盖", "nvdisplay.container.exe": "NVIDIA 显示容器",
    "igfxtray.exe": "Intel 显卡托盘", "hkcmd.exe": "Intel 热键", "igfxpers.exe": "Intel 持久化",
    "radeonsoftware.exe": "AMD 显卡软件", "amdow.exe": "AMD 覆盖",
    "etdctl.exe": "触控板", "synaptics.exe": "触控板",
    # 远程控制（关掉可能导致你再也连不上这台机器）
    "awesun.exe": "向日葵远程控制", "sunloginclient.exe": "向日葵远程控制",
    "todesk.exe": "ToDesk", "rustdesk.exe": "RustDesk", "teamviewer.exe": "TeamViewer",
    "anydesk.exe": "AnyDesk", "mstsc.exe": "远程桌面",
    # 游戏平台（关掉游戏就启动不了）
    "steam.exe": "Steam", "steamwebhelper.exe": "Steam 内嵌浏览器",
    "epicgameslauncher.exe": "Epic 启动器", "battle.net.exe": "战网",
    "galaxyclient.exe": "GOG Galaxy", "riotclientservices.exe": "拳头客户端",
    "eadesktop.exe": "EA App", "origin.exe": "Origin", "ubisoftconnect.exe": "Ubisoft Connect",
    "wegame.exe": "WeGame", "tgp.exe": "WeGame",
    # 反作弊（绝对不能结束，也不能动它的内存）
    "easyanticheat.exe": "EasyAntiCheat", "easyanticheat_eos.exe": "EasyAntiCheat EOS",
    "beservice.exe": "BattlEye", "beservice64.exe": "BattlEye", "battleye.exe": "BattlEye",
    "vgc.exe": "Vanguard 反作弊", "vgtray.exe": "Vanguard 托盘",
    "anticheatexpert.exe": "ACE 反作弊", "ace-guard client.exe": "ACE 反作弊",
    "sguard64.exe": "ACE 反作弊", "sguard.exe": "ACE 反作弊",
    "tp3helper.exe": "腾讯反作弊", "tenprotect.exe": "腾讯反作弊",
    "mssec.exe": "反作弊", "bservice.exe": "反作弊",
    # 本工具与宿主环境（结束它们会导致本工具/当前会话崩掉）
    "node.exe": "DSH 运行环境(本工具宿主)", "python.exe": "Python 宿主(本工具自身)",
    "pythonw.exe": "Python 宿主(本工具自身)",
    "deepseek harness.exe": "DeepSeek Harness 本体",
    "workbuddy.exe": "WorkBuddy",
    "explorer.exe": "资源管理器(桌面/任务栏)",
}

# 默认勾选：纯后台，关掉没有任何数据风险
TIER_SAFE: dict[str, str] = {
    "onedrive.exe": "OneDrive 云同步",
    "microsoftedgeupdate.exe": "Edge 更新器",
    "googleupdate.exe": "Google 更新器",
    "googlecrashhandler.exe": "Google 崩溃上报",
    "googlecrashhandler64.exe": "Google 崩溃上报",
    "jucheck.exe": "Java 更新检查",
    "adobeupdateservice.exe": "Adobe 更新服务",
    "armsvc.exe": "Adobe 更新服务",
    "ccxprocess.exe": "Adobe Creative Cloud",
    "creative cloud helper.exe": "Adobe 助手",
    "yourphone.exe": "手机连接",
    "phoneexperiencehost.exe": "手机连接(体验主机)",
    "crossdeviceresume.exe": "跨设备续传",
    "gamebar.exe": "Xbox Game Bar",
    "gamebarft.exe": "Xbox Game Bar",
    "xboxgameoverlay.exe": "Xbox 游戏覆盖",
    "xboxgamingoverlay.exe": "Xbox 游戏覆盖",
    "xboxapp.exe": "Xbox 应用",
    "gamingapp.exe": "Xbox 应用",
    "widgets.exe": "Windows 小组件(资讯)",
    "widgetservice.exe": "Windows 小组件服务",
    "cortana.exe": "Cortana",
    "searchapp.exe": "搜索界面(旧版)",
    "skypeapp.exe": "Skype",
    "skype.exe": "Skype",
    "teams.exe": "Microsoft Teams",
    "ms-teams.exe": "Microsoft Teams(新版)",
    "msteamsupdate.exe": "Teams 更新器",
    "yourphoneexe.exe": "手机连接",
    "setpoint.exe": "罗技驱动后台",
    "logioptionsplus_agent.exe": "罗技 Options+",
    "nahimicsvc.exe": "Nahimic 音频后台",
    "nahimicbtlink.exe": "Nahimic 蓝牙",
    "cnext.exe": "AMD 后台",
    "wsappx.exe": "商店应用部署",
    "officebackgroundtaskhandler.exe": "Office 后台任务",
    "msoia.exe": "Office 智能服务",
    "adobedesktop.exe": "Adobe 桌面服务",
    "dropbox.exe": "Dropbox",
    "baidunetdisk.exe": "百度网盘",
    "aliyundrive.exe": "阿里云盘",
    "quarkpc.exe": "夸克网盘",
    "thunder.exe": "迅雷",
    "xldl.exe": "迅雷",
    "qbittorrent.exe": "qBittorrent",
    "utorrent.exe": "uTorrent",
    "spotify.exe": "Spotify",
    "cloudmusic.exe": "网易云音乐",
    "qqmusic.exe": "QQ音乐",
    "kugou.exe": "酷狗音乐",
    "kuwo.exe": "酷我音乐",
    "searchindexer.exe": "Windows 搜索索引(会自行重启)",
    "youdaodict.exe": "有道词典",
    "eudic.exe": "欧路词典",
    "dingtalk.exe": "钉钉",
    "wxwork.exe": "企业微信",
    "feishu.exe": "飞书",
    "lark.exe": "飞书",
    "notion.exe": "Notion",
    "wallpaper32.exe": "Wallpaper Engine",
    "wallpaper64.exe": "Wallpaper Engine",
    "webwallpaper32.exe": "Wallpaper Engine",
    "ai.exe": "Adobe Illustrator 后台",
    "acrobat.exe": "Acrobat 后台",
}

# 默认不勾选：用户可能正在用，勾掉会丢当前上下文（但不会损坏数据）
TIER_OPTIONAL: dict[str, str] = {
    # 会中断正在进行的事情（看视频、开会、直播），所以默认不关
    "potplayer.exe": "PotPlayer(正在播放)",
    "vlc.exe": "VLC(正在播放)",
    "mpc-hc64.exe": "MPC-HC(正在播放)",
    "obs64.exe": "OBS(正在直播/录制)",
    "obs32.exe": "OBS(正在直播/录制)",
    "streamlabs obs.exe": "Streamlabs OBS",
    "wemeetapp.exe": "腾讯会议(正在开会)",
    "zoom.exe": "Zoom(正在开会)",
    "msedgewebview2.exe": "WebView2 宿主(可能被某应用内嵌使用)",
    "wechat.exe": "微信",
    "weixin.exe": "微信(新版)",
    "qq.exe": "QQ",
    "tim.exe": "TIM",
    "msedge.exe": "Edge 浏览器",
    "chrome.exe": "Chrome 浏览器",
    "firefox.exe": "Firefox 浏览器",
    "opera.exe": "Opera",
    "brave.exe": "Brave",
    "telegram.exe": "Telegram",
    "discord.exe": "Discord(会断开语音)",
    "code.exe": "VS Code",
    "pycharm64.exe": "PyCharm",
    "idea64.exe": "IntelliJ IDEA",
    "devenv.exe": "Visual Studio",
    "excel.exe": "Excel",
    "winword.exe": "Word",
    "powerpnt.exe": "PowerPoint",
    "outlook.exe": "Outlook",
    "wps.exe": "WPS",
    "et.exe": "WPS 表格",
    "wpp.exe": "WPS 演示",
    "photoshop.exe": "Photoshop",
    "illustrator.exe": "Illustrator",
    "premiere pro.exe": "Premiere",
    "afterfx.exe": "After Effects",
    "blender.exe": "Blender",
    "vmware-vmx.exe": "VMware 虚拟机",
    "virtualboxvm.exe": "VirtualBox 虚拟机",
    "docker desktop.exe": "Docker Desktop",
    "com.docker.backend.exe": "Docker 后台",
    "wslservice.exe": "WSL",
    "vmmemwsl": "WSL 虚拟机",
    "navicat.exe": "Navicat",
    "sublime_text.exe": "Sublime Text",
    "notepad++.exe": "Notepad++",
    "typora.exe": "Typora",
}

# 绝不清理工作集的进程（反作弊 + 系统 + 硬件相关）——
# 清理反作弊的内存可能被判定为篡改而封号；清理音频/显示驱动配套进程会卡顿
NEVER_TRIM = {
    "audiodg.exe", "dwm.exe", "csrss.exe", "winlogon.exe", "lsass.exe", "services.exe",
    "smss.exe", "wininit.exe", "svchost.exe", "msmpeng.exe", "nissrv.exe",
    "easyanticheat.exe", "easyanticheat_eos.exe", "beservice.exe", "beservice64.exe",
    "battleye.exe", "vgc.exe", "vgtray.exe", "anticheatexpert.exe", "ace-guard client.exe",
    "sguard64.exe", "sguard.exe", "tp3helper.exe", "tenprotect.exe",
    "hipsdaemon.exe", "usysdiag.exe", "360tray.exe", "zhudongfangyu.exe", "qqpctray.exe",
    "nvcontainer.exe", "nvsphelper64.exe", "nvidia share.exe",
}

SAFE_NAMES = set(TIER_SAFE)
OPTIONAL_NAMES = set(TIER_OPTIONAL)
ALL_CLOSABLE = SAFE_NAMES | OPTIONAL_NAMES


def describe(name: str) -> str:
    n = name.lower()
    if n in PROTECTED:
        return "受保护：" + PROTECTED[n]
    if n in TIER_SAFE:
        return "可安全关闭：" + TIER_SAFE[n]
    if n in TIER_OPTIONAL:
        return "可选关闭：" + TIER_OPTIONAL[n]
    return ""


# ---------------------------------------------------------------------------
# Win32 / ctypes 底层
# ---------------------------------------------------------------------------

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

INVALID_HANDLE = ctypes.c_void_p(-1).value
TH32CS_SNAPPROCESS = 0x00000002

PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
PROCESS_SET_INFORMATION = 0x0200
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010

HIGH_PRIORITY_CLASS = 0x00000080
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
NORMAL_PRIORITY_CLASS = 0x00000020
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
IDLE_PRIORITY_CLASS = 0x00000040
REALTIME_PRIORITY_CLASS = 0x00000100

WM_CLOSE = 0x0010

# --- NT 系统信息类（取值经 Process Hacker phnt 头文件核对）-------------------
SYSTEM_MEMORY_LIST_INFORMATION = 0x50            # 需 SeProfileSingleProcessPrivilege
SYSTEM_COMBINE_PHYSICAL_MEMORY_INFORMATION = 0x82
SYSTEM_REGISTRY_RECONCILIATION_INFORMATION = 0x9B  # 缓冲区传 NULL

# SYSTEM_MEMORY_LIST_COMMAND 枚举（phnt: MemoryCaptureAccessedBits 起顺序编号）
MEMORY_CAPTURE_ACCESSED_BITS = 0
MEMORY_CAPTURE_AND_RESET_ACCESSED_BITS = 1
MEMORY_EMPTY_WORKING_SETS = 2      # 系统级：清空所有进程工作集
MEMORY_FLUSH_MODIFIED_LIST = 3     # 把已修改页写回磁盘并转入待机列表
MEMORY_PURGE_STANDBY_LIST = 4      # 清空待机列表
MEMORY_PURGE_LOW_PRIORITY_STANDBY_LIST = 5   # 只清低优先级待机列表（较温和）

NTSTATUS_TEXT = {
    0xC0000061: "权限不足（需要以管理员身份运行）",
    0xC0000001: "系统不支持该操作",
    0xC00000BB: "当前系统不支持该操作",
    0xC0000004: "参数长度不匹配",
    0xC000000D: "参数无效",
    0xC0000022: "访问被拒绝",
}


def ntstatus_text(status: int) -> str:
    s = status & 0xFFFFFFFF
    if s == 0:
        return "成功"
    return NTSTATUS_TEXT.get(s, f"失败，NTSTATUS=0x{s:08X}")


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("CommitTotal", ctypes.c_size_t),
        ("CommitLimit", ctypes.c_size_t),
        ("CommitPeak", ctypes.c_size_t),
        ("PhysicalTotal", ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t),
        ("SystemCache", ctypes.c_size_t),
        ("KernelTotal", ctypes.c_size_t),
        ("KernelPaged", ctypes.c_size_t),
        ("KernelNonpaged", ctypes.c_size_t),
        ("PageSize", ctypes.c_size_t),
        ("HandleCount", wintypes.DWORD),
        ("ProcessCount", wintypes.DWORD),
        ("ThreadCount", wintypes.DWORD),
    ]


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]


class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD),
                ("Privileges", LUID_AND_ATTRIBUTES * 1)]


class MEMORY_COMBINE_INFORMATION_EX(ctypes.Structure):
    """内存合并参数结构（phnt: MEMORY_COMBINE_INFORMATION_EX）。"""
    _fields_ = [("EventHandle", wintypes.HANDLE),
                ("PagesCombined", ctypes.c_size_t),
                ("Flags", wintypes.ULONG)]


k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
k32.Process32FirstW.restype = wintypes.BOOL
k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
k32.Process32NextW.restype = wintypes.BOOL
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.CloseHandle.restype = wintypes.BOOL
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenProcess.restype = wintypes.HANDLE
k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
k32.TerminateProcess.restype = wintypes.BOOL
k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
k32.SetPriorityClass.restype = wintypes.BOOL
k32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
k32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
k32.GlobalMemoryStatusEx.restype = wintypes.BOOL
k32.GetCurrentProcess.argtypes = []
k32.GetCurrentProcess.restype = wintypes.HANDLE

psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
psapi.EmptyWorkingSet.restype = wintypes.BOOL
psapi.GetProcessMemoryInfo.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
psapi.GetPerformanceInfo.argtypes = [ctypes.POINTER(PERFORMANCE_INFORMATION), wintypes.DWORD]
psapi.GetPerformanceInfo.restype = wintypes.BOOL

# SetSystemFileCacheSize：把文件缓存上下限都设为 (SIZE_T)-1 即可触发缓存收缩
k32.SetSystemFileCacheSize.argtypes = [ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD]
k32.SetSystemFileCacheSize.restype = wintypes.BOOL

ntdll.NtSetSystemInformation.argtypes = [wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG]
ntdll.NtSetSystemInformation.restype = ctypes.c_long

advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.HANDLE)]
advapi32.OpenProcessToken.restype = wintypes.BOOL
advapi32.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                           ctypes.POINTER(LUID)]
advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL
advapi32.AdjustTokenPrivileges.argtypes = [
    wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(TOKEN_PRIVILEGES), wintypes.DWORD,
    ctypes.c_void_p, ctypes.c_void_p]
advapi32.AdjustTokenPrivileges.restype = wintypes.BOOL

user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL

shell32.IsUserAnAdmin.argtypes = []
shell32.IsUserAnAdmin.restype = wintypes.BOOL

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008
SE_PRIVILEGE_ENABLED = 0x00000002


def _handle_ok(h) -> bool:
    return bool(h) and h != INVALID_HANDLE


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT,
                                         ctypes.c_void_p, wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int


def work_area() -> tuple[int, int, int, int]:
    """主显示器工作区（已排除任务栏），物理像素。"""
    r = RECT()
    SPI_GETWORKAREA = 0x0030
    if user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0):
        if r.right > r.left and r.bottom > r.top:
            return r.left, r.top, r.right, r.bottom
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def is_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def system_dpi() -> int:
    """系统 DPI（96 = 100%，120 = 125%，144 = 150%）。"""
    try:
        dpi = int(ctypes.windll.user32.GetDpiForSystem())
        if 72 <= dpi <= 480:
            return dpi
    except Exception:
        pass
    return 96


def enable_dpi_awareness() -> int:
    """声明本进程 DPI 感知，避免 Windows 把界面位图拉伸导致发虚。返回系统 DPI。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    return system_dpi()


def enable_privilege(name: str) -> bool:
    """启用当前进程的一个特权（需要管理员）。"""
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(k32.GetCurrentProcess(),
                                     TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                                     ctypes.byref(token)):
        return False
    try:
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
            return False
        tp = TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
        ok = advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
        return bool(ok) and ctypes.get_last_error() == 0
    finally:
        k32.CloseHandle(token)


def enable_all_privileges() -> dict[str, bool]:
    out = {}
    for p in ("SeDebugPrivilege", "SeProfileSingleProcessPrivilege",
              "SeIncreaseQuotaPrivilege", "SeSystemProfilePrivilege"):
        out[p] = enable_privilege(p)
    return out


def get_memory_status() -> dict:
    """返回内存概览（字节）。"""
    ms = MEMORYSTATUSEX()
    ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    k32.GlobalMemoryStatusEx(ctypes.byref(ms))

    pi = PERFORMANCE_INFORMATION()
    pi.cb = ctypes.sizeof(PERFORMANCE_INFORMATION)
    cache = 0
    if psapi.GetPerformanceInfo(ctypes.byref(pi), pi.cb):
        cache = pi.SystemCache * pi.PageSize

    total = ms.ullTotalPhys
    avail = ms.ullAvailPhys
    return {
        "total": total,
        "avail": avail,
        "used": total - avail,
        "percent": ms.dwMemoryLoad,
        "cache": cache,               # 系统缓存/待机内存，清理待机列表主要回收这块
        "commit_used": pi.CommitTotal * pi.PageSize if pi.PageSize else 0,
        "commit_limit": pi.CommitLimit * pi.PageSize if pi.PageSize else 0,
    }


def snapshot_processes() -> list[tuple[int, int, str]]:
    """返回 [(pid, ppid, exe_name)]"""
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not _handle_ok(snap):
        return []
    out = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not k32.Process32FirstW(snap, ctypes.byref(entry)):
            return []
        while True:
            out.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            if not k32.Process32NextW(snap, ctypes.byref(entry)):
                break
    finally:
        k32.CloseHandle(snap)
    return out


def self_and_ancestors() -> set[int]:
    """本进程 + 所有父进程 PID（防止工具把自己或宿主关掉）。"""
    parents = {pid: ppid for pid, ppid, _ in snapshot_processes()}
    protected = set()
    pid = os.getpid()
    for _ in range(16):
        if not pid or pid in protected:
            break
        protected.add(pid)
        pid = parents.get(pid, 0)
    return protected


def self_process_tree() -> set[int]:
    """本进程 + 祖先 + **子孙** PID。

    为什么必须包含子孙：新版界面是 WebView2 渲染的，而
    `msedgewebview2.exe` 这个进程名在「可关闭」名单里（TIER_OPTIONAL）。
    只保护祖先的话，勾上「关闭可选级后台应用」就会把**自己的界面渲染进程**
    一起关掉 —— 表现是界面白屏或直接崩。

    注意：**只从自己往下找**。如果从祖先（比如 explorer.exe）往下找，
    会把用户启动的所有其他程序都算成"自己的子孙"，那就保护过度了。
    """
    procs = snapshot_processes()
    parents = {pid: ppid for pid, ppid, _ in procs}
    children: dict[int, list[int]] = {}
    for pid, ppid, _ in procs:
        children.setdefault(ppid, []).append(pid)

    out = set()
    # 向上：祖先链
    pid = os.getpid()
    for _ in range(16):
        if not pid or pid in out:
            break
        out.add(pid)
        pid = parents.get(pid, 0)

    # 向下：只看自己的子孙
    queue = [os.getpid()]
    while queue:
        cur = queue.pop()
        for child in children.get(cur, []):
            if child not in out:
                out.add(child)
                queue.append(child)
    return out


def list_windows_by_pid() -> dict[int, str]:
    """pid -> 可见窗口标题（取第一个非空标题）。"""
    result: dict[int, str] = {}

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value.strip()
        if title:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            result.setdefault(pid.value, title)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return result


def process_path(pid: int) -> str:
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not _handle_ok(h):
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        k32.CloseHandle(h)


def process_memory(pid: int) -> int | None:
    """工作集字节数，失败返回 None。"""
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid)
    if not _handle_ok(h):
        h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not _handle_ok(h):
        return None
    try:
        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return int(pmc.WorkingSetSize)
        return None
    finally:
        k32.CloseHandle(h)


def collect_processes() -> list[dict]:
    """一次性收集全部进程信息，按内存降序。"""
    titles = list_windows_by_pid()
    out = []
    for pid, ppid, name in snapshot_processes():
        if pid == 0:
            continue
        out.append({
            "pid": pid,
            "ppid": ppid,
            "name": name,
            "mem": process_memory(pid),
            "title": titles.get(pid, ""),
        })
    out.sort(key=lambda p: (p["mem"] or 0), reverse=True)
    return out


def trim_working_set(pid: int) -> tuple[bool, int]:
    """清理单个进程的工作集。返回 (成功, 释放字节数)。"""
    before = process_memory(pid) or 0
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_QUOTA, False, pid)
    if not _handle_ok(h):
        h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
    if not _handle_ok(h):
        return False, 0
    try:
        if not psapi.EmptyWorkingSet(h):
            return False, 0
    finally:
        k32.CloseHandle(h)
    time.sleep(0.03)
    after = process_memory(pid) or 0
    return True, max(0, before - after)


def nt_memory_list_command(command: int, name: str) -> tuple[bool, str]:
    """调用 NtSetSystemInformation(SystemMemoryListInformation, <命令>)。

    这条通道是 PCL 等启动器"内存优化"的核心：它是系统级的，
    一次调用作用于整台机器，而不是某个进程。
    """
    val = wintypes.ULONG(command)
    status = ntdll.NtSetSystemInformation(SYSTEM_MEMORY_LIST_INFORMATION,
                                          ctypes.byref(val), ctypes.sizeof(val))
    if status == 0:
        return True, f"{name}：成功"
    return False, f"{name}：{ntstatus_text(status)}"


def empty_all_working_sets() -> tuple[bool, str]:
    """系统级清空所有进程的工作集（比逐个进程清理更彻底，但也更粗暴）。"""
    return nt_memory_list_command(MEMORY_EMPTY_WORKING_SETS, "清空所有进程工作集")


def flush_modified_list() -> tuple[bool, str]:
    """把"已修改但未写回"的内存页强制写盘并转入待机列表。"""
    return nt_memory_list_command(MEMORY_FLUSH_MODIFIED_LIST, "写回已修改页面")


def purge_low_priority_standby_list() -> tuple[bool, str]:
    """只清空低优先级待机列表（比全量清理温和）。"""
    return nt_memory_list_command(MEMORY_PURGE_LOW_PRIORITY_STANDBY_LIST,
                                  "清空低优先级待机内存")


def flush_system_file_cache() -> tuple[bool, str]:
    """收缩系统文件缓存（SetSystemFileCacheSize 上下限设为 -1）。

    需要 SeIncreaseQuotaPrivilege；游戏启动时读取的大量资源会被缓存在这里。
    """
    minus_one = ctypes.c_size_t(-1).value
    if k32.SetSystemFileCacheSize(minus_one, minus_one, 0):
        return True, "刷新系统文件缓存：成功"
    err = ctypes.get_last_error()
    if err == 5:      # ERROR_ACCESS_DENIED
        return False, "刷新系统文件缓存：权限不足（需要以管理员身份运行）"
    if err == 1314:   # ERROR_PRIVILEGE_NOT_HELD
        return False, "刷新系统文件缓存：缺少 SeIncreaseQuotaPrivilege 特权"
    return False, f"刷新系统文件缓存：失败（错误码 {err}）"


def reconcile_registry() -> tuple[bool, str]:
    """让内核回收整理注册表 hive 在内存中的副本（缓冲区传 NULL）。"""
    status = ntdll.NtSetSystemInformation(SYSTEM_REGISTRY_RECONCILIATION_INFORMATION,
                                          None, 0)
    if status == 0:
        return True, "整理注册表内存：成功"
    return False, f"整理注册表内存：{ntstatus_text(status)}"


def combine_physical_memory() -> tuple[bool, str]:
    """合并内容相同的物理页面（Win8.1+ 的页面合并）。

    结构体长度在不同 Windows 版本上要求不同，这里依次尝试几种长度；
    长度不匹配时内核返回 STATUS_INFO_LENGTH_MISMATCH，不会造成损坏。
    """
    info = MEMORY_COMBINE_INFORMATION_EX()
    info.EventHandle = None
    info.PagesCombined = 0
    info.Flags = 0
    sizes = [ctypes.sizeof(MEMORY_COMBINE_INFORMATION_EX), 20, 16]
    last = ""
    for size in sizes:
        status = ntdll.NtSetSystemInformation(
            SYSTEM_COMBINE_PHYSICAL_MEMORY_INFORMATION, ctypes.byref(info), size)
        if status == 0:
            pages = info.PagesCombined
            return True, f"合并重复物理页：成功（合并 {pages} 个页面）"
        last = ntstatus_text(status)
        if (status & 0xFFFFFFFF) != 0xC0000004:   # 非「长度不匹配」就没必要再试
            break
    return False, f"合并重复物理页：{last}"


DEEP_OPS = [
    ("empty_working_sets", "系统级清空所有进程工作集",
     "把全系统进程常驻内存的页面一次性踢出去，降数字最猛的一步。\n"
     "注意：它不区分进程，受保护程序和反作弊的工作集也会被清。"),
    ("purge_standby", "清空待机内存列表（全量）",
     "回收 Windows 用来加速二次访问的文件缓存，通常能腾出 1~3 GB。"),
    ("purge_low_standby", "清空低优先级待机内存",
     "比全量清理温和，只回收优先级最低的那部分缓存。"),
    ("flush_modified", "写回已修改页面",
     "把「脏页」立即写盘并转入待机列表。会产生一次磁盘写入。"),
    ("file_cache", "刷新系统文件缓存",
     "游戏启动时读取的 jar/资源包会占住文件缓存，这一步把它收回来。"),
    ("registry", "整理注册表内存",
     "让内核回收注册表 hive 的内存副本，通常只有几十 MB。"),
    ("combine", "合并重复物理页",
     "把内容完全相同的物理页面合并成一份。收益中等，\n"
     "极少数老驱动/虚拟化环境下兼容性较差，默认不勾选。"),
]

DEFAULT_DEEP = {
    "empty_working_sets": True,
    "purge_standby": True,
    "purge_low_standby": True,
    "flush_modified": True,
    "file_cache": True,
    "registry": True,
    "combine": False,
}


def run_deep_optimize(opts: dict, log) -> dict:
    """执行 PCL 同款的全系统内存优化，返回统计。"""
    steps = [
        ("empty_working_sets", empty_all_working_sets),
        ("flush_modified", flush_modified_list),
        ("purge_standby", lambda: purge_standby_list(False)),
        ("purge_low_standby", purge_low_priority_standby_list),
        ("file_cache", flush_system_file_cache),
        ("registry", reconcile_registry),
        ("combine", combine_physical_memory),
    ]
    if not is_admin():
        log("⚠ 当前不是管理员权限：下面绝大多数系统级操作会因权限不足失败。")
    before = get_memory_status()["avail"]
    ok_count = 0
    for key, fn in steps:
        if not opts.get(key):
            log(f"  [跳过] {dict((k, t) for k, t, _ in DEEP_OPS)[key]}")
            continue
        try:
            result = fn()
        except Exception as e:
            log(f"  [异常] {key}: {e}")
            continue
        ok, msg = result[0], result[1]
        log(("  [成功] " if ok else "  [失败] ") + msg)
        ok_count += 1 if ok else 0
        time.sleep(0.15)
    after = get_memory_status()["avail"]
    delta = after - before
    log("")
    log(f"可用内存：{before / 2**30:.2f} GB → {after / 2**30:.2f} GB"
        f"（{'增加' if delta >= 0 else '减少'} {abs(delta) / 2**20:.0f} MB）")
    log(f"共 {ok_count} 项成功。")
    if delta < 0:
        log("提示：可用内存反而下降属正常——工作集被踢出后系统会立刻重新填充部分页面。")
    return {"ok": ok_count, "delta": delta, "before": before, "after": after}


def purge_standby_list(low_priority_only: bool = False) -> tuple[bool, str]:
    """清空待机内存列表（Windows 的文件缓存）。需要管理员 + SeProfileSingleProcessPrivilege。"""
    if low_priority_only:
        return purge_low_priority_standby_list()
    return nt_memory_list_command(MEMORY_PURGE_STANDBY_LIST, "清空待机内存列表")


def close_process_gracefully(pid: int, timeout: float = 1.5) -> bool:
    """先给该进程的所有窗口发 WM_CLOSE，超时未退出返回 False。"""
    sent = [False]

    def cb(hwnd, _lparam):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            sent[0] = True
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    if not sent[0]:
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not process_alive(pid):
            return True
        time.sleep(0.1)
    return not process_alive(pid)


def process_alive(pid: int) -> bool:
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not _handle_ok(h):
        return False
    try:
        code = wintypes.DWORD()
        if k32.GetExitCodeProcess(h, ctypes.byref(code)):
            return code.value == 259  # STILL_ACTIVE
        return False
    finally:
        k32.CloseHandle(h)


k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
k32.GetExitCodeProcess.restype = wintypes.BOOL


def terminate_process(pid: int) -> tuple[bool, str]:
    h = k32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not _handle_ok(h):
        err = ctypes.get_last_error()
        return False, f"无法打开进程（错误码 {err}，通常是权限不足或系统保护进程）"
    try:
        if k32.TerminateProcess(h, 1):
            return True, "已结束"
        return False, f"结束失败（错误码 {ctypes.get_last_error()}）"
    finally:
        k32.CloseHandle(h)


def kill_process(pid: int, graceful: bool = True) -> tuple[bool, str]:
    if not process_alive(pid):
        return True, "进程已不存在"
    if graceful and close_process_gracefully(pid):
        return True, "已正常退出"
    ok, msg = terminate_process(pid)
    if ok:
        return True, "已强制结束"
    return False, msg


def set_priority(pid: int, level: str) -> tuple[bool, str]:
    classes = {
        "高": HIGH_PRIORITY_CLASS,
        "高于正常": ABOVE_NORMAL_PRIORITY_CLASS,
        "正常": NORMAL_PRIORITY_CLASS,
        "低于正常": BELOW_NORMAL_PRIORITY_CLASS,
    }
    if level not in classes:
        return False, "未知优先级"
    h = k32.OpenProcess(PROCESS_SET_INFORMATION, False, pid)
    if not _handle_ok(h):
        return False, "无法打开进程（需要管理员权限）"
    try:
        if k32.SetPriorityClass(h, classes[level]):
            return True, f"优先级已设为「{level}」"
        return False, f"设置失败（错误码 {ctypes.get_last_error()}）"
    finally:
        k32.CloseHandle(h)


def get_priority(pid: int) -> str:
    """读取进程当前优先级，返回中文级别；读不到返回空串。

    界面上要显示「这个游戏现在是什么优先级」，否则用户没法判断
    到底要不要再设一次。
    """
    by_class = {
        IDLE_PRIORITY_CLASS: "低",
        BELOW_NORMAL_PRIORITY_CLASS: "低于正常",
        NORMAL_PRIORITY_CLASS: "正常",
        ABOVE_NORMAL_PRIORITY_CLASS: "高于正常",
        HIGH_PRIORITY_CLASS: "高",
        REALTIME_PRIORITY_CLASS: "实时",
    }
    h = k32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if not _handle_ok(h):
        # 查询权限不够时退一步：QUERY_LIMITED 在很多进程上也够用
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not _handle_ok(h):
            return ""
    try:
        cls = k32.GetPriorityClass(h)
        return by_class.get(cls, "")
    except Exception:
        return ""
    finally:
        k32.CloseHandle(h)


def norm_priority(level: str) -> str:
    """把界面传来的优先级级别归一化成 set_priority 认识的中文键。

    界面用英文键（idle/below/normal/above/high），旧版 tkinter 用中文；
    两边都要能用，所以在入口处统一转换，避免调用方各自记得规则。
    """
    table = {
        "idle": "低于正常", "low": "低于正常",
        "below": "低于正常", "belownormal": "低于正常",
        "normal": "正常",
        "above": "高于正常", "abovenormal": "高于正常",
        "high": "高",
        "实时": "高", "realtime": "高",       # 实时优先级风险高，降级到「高」
        "低": "低于正常", "低于正常": "低于正常",
        "正常": "正常", "高于正常": "高于正常", "高": "高",
    }
    return table.get(str(level).strip().lower(), "")


# ---------------------------------------------------------------------------
# 注册表 / 电源计划（可回滚的系统优化）
# ---------------------------------------------------------------------------

GAMEDVR_KEYS = [
    (winreg.HKEY_CURRENT_USER, r"System\GameConfigStore", "GameDVR_Enabled", 0),
    (winreg.HKEY_CURRENT_USER,
     r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 0),
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar", "AllowAutoGameMode", 1),
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar", "AutoGameModeEnabled", 1),
]

HIGH_PERF_GUIDS = [
    ("e9a42b02-d5df-448d-aa00-03f14749eb61", "卓越性能"),
    ("8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c", "高性能"),
]


def _read_reg(root, path, name):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as k:
            v, _ = winreg.QueryValueEx(k, name)
            return v
    except OSError:
        return None


def _write_reg(root, path, name, value, kind=winreg.REG_DWORD):
    with winreg.CreateKeyEx(root, path, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, kind, value)


def apply_gamedvr_off() -> tuple[list[str], dict]:
    """关闭 Xbox 后台录制、开启游戏模式。返回 (日志, 用于回滚的原始值)。"""
    logs = []
    backup = {}
    for root, path, name, value in GAMEDVR_KEYS:
        old = _read_reg(root, path, name)
        backup[f"{path}\\{name}"] = old
        try:
            _write_reg(root, path, name, value)
            logs.append(f"  已设置 {name} = {value}（原值 {old}）")
        except OSError as e:
            logs.append(f"  设置 {name} 失败：{e}")
    return logs, backup


def revert_gamedvr(backup: dict) -> list[str]:
    logs = []
    for key, old in (backup or {}).items():
        path, _, name = key.rpartition("\\")
        try:
            if old is None:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                                    winreg.KEY_SET_VALUE) as k:
                    try:
                        winreg.DeleteValue(k, name)
                    except OSError:
                        pass
                logs.append(f"  已删除 {name}")
            else:
                _write_reg(winreg.HKEY_CURRENT_USER, path, name, old)
                logs.append(f"  已还原 {name} = {old}")
        except OSError as e:
            logs.append(f"  还原 {name} 失败：{e}")
    return logs


def _run_powercfg(args: list[str]) -> str:
    try:
        p = subprocess.run(["powercfg"] + args, capture_output=True, text=True,
                           creationflags=0x08000000, timeout=15)
        return (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return f"__error__{e}"


def active_power_plan() -> tuple[str, str]:
    out = _run_powercfg(["/getactivescheme"])
    if out.startswith("__error__"):
        return "", ""
    import re
    m = re.search(r"([0-9a-fA-F-]{36})\s*\((.*?)\)", out)
    if m:
        return m.group(1).lower(), m.group(2)
    return "", ""


def available_plans() -> dict[str, str]:
    out = _run_powercfg(["/list"])
    import re
    plans = {}
    for m in re.finditer(r"([0-9a-fA-F-]{36})\s*\((.*?)\)", out):
        plans[m.group(1).lower()] = m.group(2)
    return plans


def set_power_plan(guid: str) -> tuple[bool, str]:
    out = _run_powercfg(["/setactive", guid])
    if "error" in out.lower() or out.startswith("__error__"):
        return False, out.strip()[:200]
    return True, f"已切换电源计划到 {guid}"


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "opt_kill_safe": True,
    "opt_kill_optional": False,
    "opt_trim": True,
    "opt_standby": True,
    "opt_gamedvr": False,
    "opt_power": False,
    "trim_min_mb": 50,
    "graceful_kill": True,
    "previous_power_plan": "",
    "gamedvr_backup": {},
    "closed_apps": [],
    "deep_opts": {},
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 优化流程（与界面解耦，可被自检复用）
# ---------------------------------------------------------------------------

class Optimizer:
    """执行优化动作，通过 log 回调输出。"""

    def __init__(self, log=print):
        self.log = log
        self.cfg = load_config()
        # 用 self_process_tree 而不是 self_and_ancestors：
        # 后者只保护祖先，会让「关闭可选级后台应用」把自己的 WebView2
        # 渲染进程（msedgewebview2.exe，属子孙）一起关掉。
        self.protected_pids = self_process_tree()

    # -- 判定 -------------------------------------------------------------
    def is_protected(self, proc: dict) -> bool:
        name = (proc.get("name") or "").lower()
        if proc["pid"] in (0, 4):
            return True
        if name in PROTECTED:
            return True
        if proc["pid"] in self.protected_pids:
            return True
        return False

    def is_closable(self, proc: dict) -> bool:
        if self.is_protected(proc):
            return False
        return (proc.get("name") or "").lower() in ALL_CLOSABLE

    def is_trimmable(self, proc: dict) -> bool:
        name = (proc.get("name") or "").lower()
        if self.is_protected(proc) or name in NEVER_TRIM:
            return False
        mem = proc.get("mem") or 0
        return mem >= int(self.cfg.get("trim_min_mb", 50)) * 1024 * 1024

    # -- 动作 -------------------------------------------------------------
    def close_processes(self, procs: list[dict], graceful: bool | None = None) -> tuple[int, int]:
        if graceful is None:
            graceful = bool(self.cfg.get("graceful_kill", True))
        closed = failed = 0
        for p in procs:
            if self.is_protected(p):
                self.log(f"  [跳过] {p['name']} (PID {p['pid']}) 属于受保护进程")
                continue
            path = process_path(p["pid"])
            mem_mb = (p.get("mem") or 0) / 1048576
            ok, msg = kill_process(p["pid"], graceful=graceful)
            if ok:
                closed += 1
                self.log(f"  [关闭] {p['name']} (PID {p['pid']}, {mem_mb:.0f} MB) — {msg}")
                # PID 是会被系统复用的：枚举时的 PID 和关闭时查到的路径未必
                # 属于同一个进程。名字对不上就不记录路径，否则「重启已关闭的
                # 应用」会去启动一个完全不相干的程序。
                if path and os.path.basename(path).lower() != \
                        (p.get("name") or "").lower():
                    path = ""
                if path:
                    apps = self.cfg.setdefault("closed_apps", [])
                    rec = {"name": p["name"], "path": path, "mem": int(p.get("mem") or 0)}
                    if not any(a.get("path") == path for a in apps):
                        apps.append(rec)
                    save_config(self.cfg)
            else:
                failed += 1
                self.log(f"  [失败] {p['name']} (PID {p['pid']}) — {msg}")
        return closed, failed

    def trim_all(self, procs: list[dict]) -> tuple[int, int]:
        total_freed = 0
        count = 0
        for p in procs:
            if not self.is_trimmable(p):
                continue
            ok, freed = trim_working_set(p["pid"])
            if ok:
                count += 1
                total_freed += freed
                if freed > 2 * 1024 * 1024:
                    self.log(f"  [清理] {p['name']} 释放 {freed / 1048576:.0f} MB")
        self.log(f"  共清理 {count} 个进程，释放约 {total_freed / 1048576:.0f} MB 工作集")
        return count, total_freed

    # -- 一键流程 ---------------------------------------------------------
    def run_full(self, procs: list[dict], opts: dict) -> None:
        t0 = time.time()
        before = get_memory_status()
        self.log("=" * 56)
        self.log(f"开始优化   可用内存 {before['avail'] / 1073741824:.2f} GB "
                 f"（占用 {before['percent']}%）")
        self.log("=" * 56)

        if not is_admin():
            self.log("⚠ 当前不是管理员权限，部分功能（清理待机内存、关闭系统级进程）会失败。")
            self.log("  建议关闭后用「以管理员身份运行」重新打开。")

        # 1) 关闭后台应用
        if opts.get("kill_safe") or opts.get("kill_optional"):
            self.log("\n[1/4] 关闭后台应用")
            targets = []
            for p in procs:
                n = (p.get("name") or "").lower()
                if n not in ALL_CLOSABLE or self.is_protected(p):
                    continue
                if n in SAFE_NAMES and opts.get("kill_safe"):
                    targets.append(p)
                elif n in OPTIONAL_NAMES and opts.get("kill_optional"):
                    targets.append(p)
            if not targets:
                self.log("  没有发现可关闭的后台应用")
            else:
                self.close_processes(targets)
        else:
            self.log("\n[1/4] 跳过关闭后台应用")

        # 2) 清理工作集
        if opts.get("trim"):
            self.log("\n[2/4] 清理进程工作集（把闲置内存还给系统）")
            fresh = collect_processes()
            self.trim_all(fresh)
        else:
            self.log("\n[2/4] 跳过工作集清理")

        # 3) 清理待机内存
        if opts.get("standby"):
            self.log("\n[3/4] 清空待机内存列表（文件缓存）")
            time.sleep(0.5)
            ok, msg = purge_standby_list()
            self.log(f"  {msg}")
            if not ok:
                self.log("  提示：该项需要管理员权限；清理后首次打开软件会略微变慢，属正常现象。")
        else:
            self.log("\n[3/4] 跳过待机内存清理")

        # 4) 系统级优化
        if opts.get("gamedvr") or opts.get("power"):
            self.log("\n[4/4] 系统设置优化")
            if opts.get("gamedvr"):
                logs, backup = apply_gamedvr_off()
                # 只在第一次记录原始值。否则重复执行会把「已被改过的值」当成原值存下来，
                # 导致「还原系统设置」变成空操作。
                if not self.cfg.get("gamedvr_backup"):
                    self.cfg["gamedvr_backup"] = backup
                    save_config(self.cfg)
                self.log("  已关闭 Xbox 后台录制 / 开启游戏模式：")
                for line in logs:
                    self.log(line)
            if opts.get("power"):
                old_guid, old_name = active_power_plan()
                plans = available_plans()
                target = None
                for guid, label in HIGH_PERF_GUIDS:
                    if guid in plans:
                        target = (guid, label)
                        break
                if not target:
                    self.log("  未找到「高性能」电源计划，跳过")
                elif old_guid == target[0]:
                    self.log(f"  当前已是「{target[1]}」电源计划")
                else:
                    if old_guid:
                        self.cfg["previous_power_plan"] = old_guid
                        save_config(self.cfg)
                    ok, msg = set_power_plan(target[0])
                    self.log(f"  {msg if ok else '切换电源计划失败：' + msg}")
                    if ok:
                        self.log(f"  （原计划 {old_name or old_guid} 已记录，可在「还原」中恢复）")
        else:
            self.log("\n[4/4] 跳过系统设置优化")

        time.sleep(0.6)
        after = get_memory_status()
        delta = after["avail"] - before["avail"]
        self.log("\n" + "-" * 56)
        self.log(f"优化完成，用时 {time.time() - t0:.1f} 秒")
        self.log(f"可用内存：{before['avail'] / 1073741824:.2f} GB → "
                 f"{after['avail'] / 1073741824:.2f} GB  "
                 f"({'释放' if delta >= 0 else '减少'} {abs(delta) / 1048576:.0f} MB)")
        self.log(f"系统缓存：{before['cache'] / 1073741824:.2f} GB → "
                 f"{after['cache'] / 1073741824:.2f} GB")
        self.log("-" * 56)
        self.log("现在可以启动游戏了。祝帧率稳定 :)")

    def revert_system(self) -> None:
        self.log("开始还原系统设置……")
        if self.cfg.get("gamedvr_backup"):
            for line in revert_gamedvr(self.cfg["gamedvr_backup"]):
                self.log(line)
            self.cfg["gamedvr_backup"] = {}
            save_config(self.cfg)
        else:
            self.log("  没有需要还原的 GameDVR 设置")
        prev = self.cfg.get("previous_power_plan")
        if prev:
            ok, msg = set_power_plan(prev)
            self.log(f"  {'已恢复原电源计划' if ok else '恢复电源计划失败：' + msg}")
            self.cfg["previous_power_plan"] = ""
            save_config(self.cfg)
        else:
            self.log("  没有需要还原的电源计划")

    def relaunch_closed(self) -> None:
        apps = self.cfg.get("closed_apps", [])
        if not apps:
            self.log("没有记录到已关闭的应用。")
            return
        still = []
        running = {p["name"].lower() for p in collect_processes() if p.get("name")}
        for a in apps:
            path = a.get("path", "")
            name = a.get("name", "?")
            if not path or not os.path.exists(path):
                self.log(f"  [跳过] {name} — 找不到路径")
                continue
            base = os.path.basename(path).lower()
            if base in running:
                still.append(a)
                continue
            try:
                subprocess.Popen([path], cwd=os.path.dirname(path),
                                 creationflags=0x00000008 | 0x00000200)
                self.log(f"  [已启动] {name}")
            except Exception as e:
                self.log(f"  [失败] {name} — {e}")
                still.append(a)
        self.cfg["closed_apps"] = still
        save_config(self.cfg)


# ---------------------------------------------------------------------------
# 自检 / 报告模式
# ---------------------------------------------------------------------------

def selftest() -> int:
    print(f"{APP_NAME} v{APP_VERSION} — 自检")
    print("=" * 60)
    ok = True
    enable_dpi_awareness()      # 与图形界面保持一致，才能读到真实 DPI

    # 名单一致性：同一进程名不能既"受保护"又"可关闭"
    overlap = {n for n in ALL_CLOSABLE if n in PROTECTED}
    if overlap:
        ok = False
        print(f"  !! 名单冲突（既受保护又可关闭）：{sorted(overlap)}")
    else:
        print("名单一致性       : 通过（受保护与可关闭名单无重叠）")

    print(f"Python           : {sys.version.split()[0]} ({'64' if sys.maxsize > 2**32 else '32'} 位)")
    print(f"屏幕 DPI         : {system_dpi()}（缩放 {int(system_dpi() / 96 * 100)}%）")
    print(f"管理员权限       : {is_admin()}")
    privs = enable_all_privileges()
    for name, got in privs.items():
        print(f"  特权 {name:<32}: {'已启用' if got else '未启用（需管理员）'}")

    m = get_memory_status()
    print(f"内存统计         : 共 {m['total'] / 2**30:.2f} GB, "
          f"可用 {m['avail'] / 2**30:.2f} GB, 占用 {m['percent']}%, "
          f"系统缓存 {m['cache'] / 2**30:.2f} GB")
    if m["total"] <= 0:
        ok = False
        print("  !! GlobalMemoryStatusEx 返回异常")

    procs = snapshot_processes()
    print(f"进程枚举         : {len(procs)} 个进程")
    if len(procs) < 10:
        ok = False
        print("  !! 进程快照异常")

    detailed = collect_processes()
    with_mem = [p for p in detailed if p["mem"] is not None]
    print(f"内存读取         : 成功读取 {len(with_mem)}/{len(detailed)} 个进程")
    top = with_mem[:5]
    for p in top:
        print(f"    {p['name'][:30]:<30} PID {p['pid']:<7} {p['mem'] / 2**20:8.1f} MB")

    opt = Optimizer(log=lambda *_: None)
    protected = [p for p in detailed if opt.is_protected(p)]
    closable = [p for p in detailed if opt.is_closable(p)]
    trimmable = [p for p in detailed if opt.is_trimmable(p)]
    print(f"分类结果         : 受保护 {len(protected)} 个, 可关闭 {len(closable)} 个, "
          f"可清理工作集 {len(trimmable)} 个")
    for p in closable[:12]:
        tier = "安全" if p["name"].lower() in SAFE_NAMES else "可选"
        print(f"    [{tier}] {p['name']:<30} PID {p['pid']:<7} "
              f"{(p['mem'] or 0) / 2**20:8.1f} MB")
    assert not any(p["name"].lower() == "hipsdaemon.exe" for p in closable), "火绒被误判为可关闭！"
    assert not any(p["pid"] in opt.protected_pids for p in closable), "自身进程被误判为可关闭！"
    print("保护名单断言     : 通过（杀软 / 远程控制 / 自身进程 均不可关闭）")

    paths = [(p["name"], process_path(p["pid"])) for p in with_mem[:40]]
    got_path = [x for x in paths if x[1]]
    print(f"路径读取         : {len(got_path)}/{len(paths)} 成功")

    # 工作集清理：对本进程做一次无损测试
    before = process_memory(os.getpid())
    trimmed, freed = trim_working_set(os.getpid())
    print(f"工作集清理测试   : {'成功' if trimmed else '失败'}，"
          f"自身进程 {before / 2**20:.1f} MB → 释放 {freed / 2**20:.1f} MB")
    if not trimmed:
        ok = False

    # 待机列表清理：需要管理员，失败不算致命
    purge_ok, purge_msg = purge_standby_list()
    print(f"待机内存清理测试 : {'成功' if purge_ok else '不可用'} — {purge_msg}")

    # 系统级内存操作（PCL 同款）。非管理员时会返回权限不足，
    # 关键是内核必须「认得」这些信息类：返回 0xC0000061(权限) 而不是
    # 0xC0000003(无效信息类)，就说明常量取值正确。
    print("系统级内存操作   :")
    invalid_class = 0xC0000003
    for label, fn in (
        ("清空所有进程工作集", empty_all_working_sets),
        ("写回已修改页面", flush_modified_list),
        ("清空待机列表(全量)", lambda: purge_standby_list(False)),
        ("清空低优先级待机列表", purge_low_priority_standby_list),
        ("刷新系统文件缓存", flush_system_file_cache),
        ("整理注册表内存", reconcile_registry),
        ("合并重复物理页", combine_physical_memory),
    ):
        try:
            good, msg = fn()
        except Exception as e:
            good, msg = False, f"异常 {type(e).__name__}: {e}"
            ok = False
        low = msg.lower()
        bad_class = (not good) and ("0xc0000003" in low or "不支持" in msg)
        flag = "OK " if good else ("!! " if bad_class else "·  ")
        if bad_class:
            ok = False
        print(f"    {flag}{label:<22} {'成功' if good else msg}")
    print("    （!! 表示内核不认这个信息类，即常量填错了；· 表示仅权限不足，属正常）")

    guid, name = active_power_plan()
    plans = available_plans()
    print(f"电源计划         : 当前 {name or '未知'} ({guid or '-'})，"
          f"共 {len(plans)} 个可用计划")
    if not plans:
        print("  (读取电源计划失败，界面会跳过该项)")

    print("-" * 60)
    print("界面依赖         : " + ("tkinter 可用" if tk is not None else "tkinter 缺失"))
    if tk is None:
        ok = False
    print("=" * 60)
    print("自检结果：" + ("全部通过" if ok else "存在问题，见上面的 !! 标记"))
    return 0 if ok else 1


def report() -> int:
    m = get_memory_status()
    print(f"内存：共 {m['total'] / 2**30:.2f} GB，已用 {m['used'] / 2**30:.2f} GB"
          f"（{m['percent']}%），可用 {m['avail'] / 2**30:.2f} GB，"
          f"系统缓存 {m['cache'] / 2**30:.2f} GB")
    print(f"管理员：{is_admin()}")
    opt = Optimizer(log=lambda *_: None)
    procs = collect_processes()
    closable = [p for p in procs if opt.is_closable(p)]
    closable.sort(key=lambda p: (p["mem"] or 0), reverse=True)
    print(f"\n可关闭的后台应用（{len(closable)} 个，合计 "
          f"{sum((p['mem'] or 0) for p in closable) / 2**20:.0f} MB）：")
    for p in closable:
        tier = "安全" if p["name"].lower() in SAFE_NAMES else "可选"
        print(f"  [{tier}] {p['name']:<34} PID {p['pid']:<7} {(p['mem'] or 0) / 2**20:8.1f} MB")
    return 0



if __name__ == "__main__":
    # 直接运行本模块时沿用原版命令行入口
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--report" in sys.argv:
        sys.exit(report())
    print("用法: python mem.py [--selftest|--report]")
