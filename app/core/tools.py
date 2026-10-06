# -*- coding: utf-8 -*-
"""小功能：启动项管理、硬件与磁盘健康、大文件查找、重复文件查找。

**这个模块是手写的**（不属于切分器生成的那两个核心文件），因为它只服务
新版界面，旧版 tkinter 工具没有这些功能。

安全约定（四项共同点：只读为主，写操作都可还原）：

* 「大文件查找」「重复文件查找」**全程不删任何东西**，只列出来
* 「启动项管理」的禁用是**移动/改名**，不是删除，可一键还原
* 「硬件信息」纯只读

调用 PowerShell 取 WMI 数据时统一用 CREATE_NO_WINDOW：
打包成 windowed EXE 后没有控制台，不设的话每查一次就会闪一个黑框。
"""
import ctypes
import hashlib
import os
import re
import subprocess
import sys

# 允许「直接运行本模块」与「作为包导入」两种方式
try:
    from app.paths import config_dir as _config_dir       # noqa: F401
except ImportError:                                         # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    from app.paths import config_dir as _config_dir       # noqa: F401

IS_WINDOWS = os.name == "nt"

# 盘符类型常量。DRIVE_FIXED 是 **3**（2 是可移动）—— 写错过一次，
# 代价是所有固定磁盘被跳过，这里明确写出来免得再记反。
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5

# 不跟随重解析点（符号链接/联接），否则会绕出扫描范围甚至成环
FILE_ATTRIBUTE_REPARSE_POINT = 0x0400

# 明确不碰的目录名（扫描时跳过，省时间也避免误入系统区）
_SKIP_DIRS = {
    "$recycle.bin", "system volume information", "windows", "winsxs",
    "installer", "driverstore", "recovery", "servicing", "assembly",
    "$windows.~bt", "$windows.~ws", "node_modules", "__pycache__",
    ".git", ".svn", ".hg", "appdata",
}

CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


# ===========================================================================
# 通用：跑 PowerShell 取 JSON
# ===========================================================================
def _ps_json(script: str, timeout: int = 25):
    """执行 PowerShell 并把输出当 JSON 解析。

    强制 UTF-8 输出，否则中文 Windows 上会按 GBK 出来变乱码。
    返回 (数据, 错误说明)；数据可能是 dict 或 list。
    """
    if not IS_WINDOWS:
        return None, "仅支持 Windows"
    prelude = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
               "$ProgressPreference='SilentlyContinue';")
    cmd = ["powershell", "-NoProfile", "-NonInteractive",
           "-ExecutionPolicy", "Bypass", "-Command", prelude + script]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return None, f"查询超时（{timeout}s）"
    except Exception as e:                                  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"

    raw = (r.stdout or b"").decode("utf-8", errors="replace").strip()
    if not raw:
        err = (r.stderr or b"").decode("utf-8", errors="replace").strip()
        return None, err[:300] or "没有输出"
    try:
        import json
        return json.loads(raw), ""
    except Exception as e:                                  # noqa: BLE001
        return None, f"解析失败 {e}: {raw[:200]}"


# ===========================================================================
# 一、启动项管理
# ===========================================================================
# 禁用方式：把值从 Run 键**移动到**同级的 *-Disabled 键里（Autoruns 也是
# 这个思路）。不删除，所以随时能还原；即使本工具没了，用户自己也能看明白。
RUN_KEYS = [
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
    ("HKLM", r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
]
_DISABLED_SUFFIX = "-DisabledByMahiru"


def _startup_folders() -> list[tuple[str, str]]:
    out = []
    appdata = os.environ.get("APPDATA") or ""
    programdata = os.environ.get("PROGRAMDATA") or ""
    if appdata:
        out.append(("用户启动文件夹",
                    os.path.join(appdata, "Microsoft", "Windows",
                                 "Start Menu", "Programs", "Startup")))
    if programdata:
        out.append(("公共启动文件夹",
                    os.path.join(programdata, "Microsoft", "Windows",
                                 "Start Menu", "Programs", "Startup")))
    return [(n, p) for n, p in out if os.path.isdir(p)]


def _exe_from_command(cmd: str) -> str:
    """从启动命令里抠出可执行文件路径。

    命令形如：
        "C:\\Program Files\\X\\x.exe" --minimized
        C:\\Windows\\System32\\y.exe -a
        rundll32.exe foo.dll,Entry
    """
    s = (cmd or "").strip()
    if not s:
        return ""
    if s.startswith('"'):
        end = s.find('"', 1)
        return s[1:end] if end > 0 else s[1:]
    # 没引号：取到第一个 .exe 为止
    m = re.match(r"^(.*?\.exe)\b", s, re.I)
    if m:
        return m.group(1).strip()
    return s.split(" ")[0].strip()


def _version_info(path: str) -> dict:
    """读文件的版本信息（厂商 / 产品名）。读不到返回空。

    用 ctypes 直接问 Windows，不额外起进程 —— 启动项可能有几十条，
    每条都 spawn 一次 PowerShell 太慢。
    """
    if not path or not os.path.isfile(path):
        return {}
    try:
        import ctypes
        from ctypes import wintypes
        ver = ctypes.WinDLL("version", use_last_error=True)
        ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
        ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                            wintypes.DWORD, ctypes.c_void_p]
        ver.GetFileVersionInfoW.restype = wintypes.BOOL
        ver.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                       ctypes.POINTER(ctypes.c_void_p),
                                       ctypes.POINTER(ctypes.c_uint)]
        ver.VerQueryValueW.restype = wintypes.BOOL

        dummy = wintypes.DWORD()
        size = ver.GetFileVersionInfoSizeW(path, ctypes.byref(dummy))
        if not size:
            return {}
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(path, 0, size, buf):
            return {}

        def query(sub: str) -> str:
            p = ctypes.c_void_p()
            n = ctypes.c_uint()
            if ver.VerQueryValueW(buf, sub, ctypes.byref(p), ctypes.byref(n)):
                if p.value and n.value:
                    return ctypes.wstring_at(p.value, n.value).strip("\x00 ")
            return ""

        # 语言页要先问出来才能取 CompanyName
        trans = query(r"\VarFileInfo\Translation")
        lang = "040904b0"
        if len(trans) >= 4:
            lang = f"{ord(trans[0]):04x}{ord(trans[1]):04x}"
        out = {}
        comp = query(rf"\StringFileInfo\{lang}\CompanyName")
        prod = query(rf"\StringFileInfo\{lang}\ProductName")
        if comp:
            out["company"] = comp
        if prod:
            out["product"] = prod
        return out
    except Exception:                                       # noqa: BLE001
        return {}


# 明确**建议保留**的：关掉会影响系统或其他软件正常工作
_KEEP_HINTS = (
    "securityhealth", "windowsdefender", "msmpeng", "mpcmdrun",
    "ctfmon", "inputmethod", "ime", "sogou", "qqpinyin",
    "rtkaudioservice", "realtekaudio", "audiosrv",
    "explorer", "sihost", "dwm", "taskhostw",
    "oneldrive", "onedrive",
)

# 安全软件单独一类。
# 判成「可以关」是错的 —— 关掉杀软自启等于降低防护，
# 用户看到「可按需关闭」很可能会顺手关掉，这个建议必须更谨慎。
_SECURITY_HINTS = (
    "sysdiag", "hrsword", "huorong", "360tray", "360safe", "zhudongfangyu",
    "qqpcmgr", "kxe", "kav", "avp", "avast", "avg", "nod32", "ekrn",
    "mcafee", "nortonsecurity", "bitdefender", "malwarebytes",
    "sophos", "kaspersky", "pcmanager", "mspcmanager",
)


def _expand(path: str) -> str:
    """展开命令里的环境变量。

    必须做：注册表 Run 键里常常写 `%ProgramFiles%\\...` 这种形式，
    不展开就会当成「文件不存在」，于是把 Windows Defender 这种
    系统组件误判成「已失效、可以关」—— 这个建议是错的。
    """
    try:
        return os.path.expandvars(path) if path else ""
    except Exception:                                       # noqa: BLE001
        return path or ""


def assess_startup(item: dict) -> dict:
    """判断一个启动项适不适合关掉。

    原则：**只给判断依据，不替用户下结论**。分类尽量保守 ——
    拿不准的一律归到「可按需关闭」而不是「建议关闭」。
    """
    cmd = item.get("command") or ""
    is_folder_item = item.get("kind") == "启动文件夹"

    # 启动文件夹里的「命令」就是文件本身，**不要去做路径解析** ——
    # 文件名里带空格时（比如「发送至 OneNote.lnk」）按空格切会截断，
    # 于是被判成「文件不存在、已失效」。这个坑踩过。
    if is_folder_item:
        path = _expand(cmd.strip().strip('"'))
        if path.lower().endswith(".lnk"):
            return {
                "path": path, "exists": os.path.isfile(path),
                "company": "", "product": "",
                "level": "unknown", "verdict": "快捷方式",
                "reason": "这是个快捷方式，关掉只是不再自启，"
                          "随时能在启动文件夹里还原",
            }
    else:
        path = _expand(_exe_from_command(cmd))

    info = _version_info(path)
    low = (path or "").lower()
    exists = bool(path) and os.path.isfile(path)

    # 判断依据要同时看**可执行文件名**和**注册表项名** ——
    # 有些软件项名是缩写（火绒的项名是 Sysdiag，exe 却是 HipsTray.exe），
    # 只看 exe 名会漏判，把它当成普通第三方程序建议「可以关」。
    hay = f"{os.path.basename(low)} {item.get('name', '').lower()}"

    out = {
        "path": path,
        "exists": exists,
        "company": info.get("company", ""),
        "product": info.get("product", ""),
    }

    if is_folder_item and not exists:
        out.update(level="broken", verdict="已失效",
                   reason="这个文件已经不在了，关掉不会有任何影响")
        return out

    if not path:
        out.update(level="unknown", verdict="看不出目标",
                   reason="这条命令不是常见的 exe 形式，建议先留着")
        return out

    if not exists:
        out.update(level="broken", verdict="已失效",
                   reason="程序已经卸载或移动了，留着只会拖慢开机，可以关")
        return out

    if any(h in hay for h in _SECURITY_HINTS):
        out.update(level="keep", verdict="安全软件，建议保留",
                   reason="关掉会降低防护。真要关请去它自己的设置里关，"
                          "别在启动项里直接禁")
        return out

    if any(h in hay for h in _KEEP_HINTS):
        out.update(level="keep", verdict="建议保留",
                   reason="属于系统组件或输入法这类基础功能，关掉会有副作用")
        return out

    if low.startswith(os.environ.get("WINDIR", "C:\\Windows").lower() + "\\"):
        out.update(level="keep", verdict="建议保留",
                   reason="位于 Windows 目录，多半是系统或驱动组件")
        return out

    # 自己的程序绝不该被自己关掉
    try:
        from app.paths import app_root
        if low.startswith(str(app_root()).lower()):
            out.update(level="keep", verdict="本程序，别关",
                       reason="这是 mahiru小助手 自己")
            return out
    except Exception:                                       # noqa: BLE001
        pass

    size = 0
    try:
        size = os.path.getsize(path)
    except OSError:
        pass

    out.update(
        level="optional", verdict="可按需关闭",
        reason=f"第三方程序（{info.get('company') or '厂商未知'}）"
               f"，关掉不影响系统，只是它不再开机自启")
    out["size"] = size
    return out


def list_startup_items() -> dict:
    """列出所有启动项（注册表 Run 键 + 启动文件夹）。

    每一项都带一个可用的 `id`，供 set_startup_enabled() 操作。
    返回 {"items": [...], "errors": [...]}
    """
    items, errors = [], []

    try:
        import winreg
    except ImportError:
        return {"items": [], "errors": ["当前环境没有 winreg"]}

    hives = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}

    for hive_name, sub in RUN_KEYS:
        hive = hives[hive_name]
        for suffix, enabled in (("", True), (_DISABLED_SUFFIX, False)):
            try:
                with winreg.OpenKey(hive, sub + suffix) as k:
                    n = winreg.QueryInfoKey(k)[1]
                    for i in range(n):
                        try:
                            name, value, _ = winreg.EnumValue(k, i)
                        except OSError:
                            continue
                        items.append({
                            "id": f"reg|{hive_name}|{sub}|{name}",
                            "kind": "注册表",
                            "scope": hive_name,
                            "name": name,
                            "command": str(value),
                            "enabled": enabled,
                        })
            except FileNotFoundError:
                continue
            except PermissionError:
                errors.append(f"{hive_name}\\{sub}{suffix}：需要管理员权限")
            except OSError as e:
                errors.append(f"{hive_name}\\{sub}{suffix}：{e}")

    for label, folder in _startup_folders():
        try:
            for entry in os.scandir(folder):
                if not entry.is_file(follow_symlinks=False):
                    continue
                # desktop.ini 是文件夹的显示配置，不是启动程序
                if entry.name.lower() == "desktop.ini":
                    continue
                disabled = entry.name.lower().endswith(".disabled")
                items.append({
                    "id": f"file|{folder}|{entry.name}",
                    "kind": "启动文件夹",
                    "scope": label,
                    "name": entry.name,
                    "command": entry.path,
                    "enabled": not disabled,
                })
        except OSError as e:
            errors.append(f"{label}：{e}")

    # 逐条评估「适不适合关」—— 界面要展示，别让用户自己猜
    for it in items:
        try:
            it.update(assess_startup(it))
        except Exception as e:                              # noqa: BLE001
            it.update(level="unknown", verdict="评估失败",
                      reason=f"{type(e).__name__}: {e}")

    # 排序：已失效、可以关的排前面（用户最可能处理它们），
    # 建议保留的沉底；同一类里先显示启用中的。
    rank = {"broken": 0, "optional": 1, "unknown": 2, "keep": 3}
    items.sort(key=lambda x: (not x["enabled"],
                              rank.get(x.get("level"), 9),
                              x["name"].lower()))
    return {"items": items, "errors": errors}


def set_startup_enabled(item_id: str, enabled: bool) -> tuple[bool, str]:
    """启用/禁用某个启动项。**不删除任何东西**，只做移动或改名。"""
    try:
        import winreg
    except ImportError:
        return False, "当前环境没有 winreg"

    parts = item_id.split("|")
    if len(parts) < 3:
        return False, "无效的启动项 id"

    if parts[0] == "reg":
        if len(parts) != 4:
            return False, "无效的注册表启动项 id"
        _, hive_name, sub, name = parts
        hive = {"HKCU": winreg.HKEY_CURRENT_USER,
                "HKLM": winreg.HKEY_LOCAL_MACHINE}.get(hive_name)
        if hive is None:
            return False, f"未知的注册表根 {hive_name}"

        # 启用中的项在 sub；禁用中的项在 sub + _DISABLED_SUFFIX。
        # 「设为启用」= 从禁用区搬回活动键；「设为禁用」= 从活动键搬进禁用区。
        #
        # 这里**写反过一次**：原来写的是
        #     src = sub + ("" if enabled else SUFFIX)
        # 于是「禁用」变成去禁用区里找那个值 —— 那里当然是空的，
        # 于是每次都报「找不到（可能已被其他程序改动）」。
        if enabled:
            src, dst = sub + _DISABLED_SUFFIX, sub
        else:
            src, dst = sub, sub + _DISABLED_SUFFIX

        try:
            with winreg.OpenKey(hive, src, 0,
                                winreg.KEY_READ | winreg.KEY_WRITE) as k:
                value, vtype = winreg.QueryValueEx(k, name)
        except FileNotFoundError:
            where = "禁用区" if enabled else "启用区"
            return False, f"在{where}里找不到「{name}」，可能已被别的程序改动"
        except PermissionError:
            return False, "需要管理员权限才能改这一项"

        try:
            with winreg.CreateKeyEx(hive, dst, 0, winreg.KEY_WRITE) as k:
                winreg.SetValueEx(k, name, 0, vtype, value)
        except PermissionError:
            return False, "需要管理员权限"

        # 先写成功再删原值，避免中间失败导致两边都没有
        try:
            with winreg.OpenKey(hive, src, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, name)
        except OSError as e:
            return False, f"已复制到禁用区但删除原值失败：{e}"

        return True, ("已启用" if enabled else "已禁用") + f"「{name}」（可在本页还原）"

    if parts[0] == "file":
        folder = parts[1]
        fname = "|".join(parts[2:])
        src = os.path.join(folder, fname)
        if enabled:
            if not fname.lower().endswith(".disabled"):
                return False, "该项本来就是启用状态"
            dst = src[:-len(".disabled")]
        else:
            if fname.lower().endswith(".disabled"):
                return False, "该项本来就是禁用状态"
            dst = src + ".disabled"
        if not os.path.exists(src):
            return False, "文件已经不在了"
        if os.path.exists(dst):
            return False, f"目标已存在：{os.path.basename(dst)}"
        try:
            os.rename(src, dst)
        except PermissionError:
            return False, "需要管理员权限"
        except OSError as e:
            return False, f"改名失败：{e}"
        return True, ("已启用" if enabled else "已禁用") + f"「{fname}」"

    return False, f"未知的启动项类型 {parts[0]}"


# ===========================================================================
# 二、硬件与磁盘健康
# ===========================================================================
def hardware_info() -> dict:
    """CPU / 内存条 / 显卡 / 主板。只读。"""
    cpu_ps = (
        "Get-CimInstance Win32_Processor | Select-Object -First 1 "
        "Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,"
        "L3CacheSize | ConvertTo-Json -Compress"
    )
    mem_ps = (
        "Get-CimInstance Win32_PhysicalMemory | "
        "Select-Object Capacity,Speed,Manufacturer,PartNumber,DeviceLocator | "
        "ConvertTo-Json -Compress"
    )
    gpu_ps = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterRAM,DriverVersion,VideoModeDescription | "
        "ConvertTo-Json -Compress"
    )
    board_ps = (
        "Get-CimInstance Win32_BaseBoard | Select-Object -First 1 "
        "Manufacturer,Product | ConvertTo-Json -Compress"
    )
    os_ps = (
        "Get-CimInstance Win32_OperatingSystem | "
        "Select-Object Caption,Version,BuildNumber,OSArchitecture,"
        "LastBootUpTime | ConvertTo-Json -Compress"
    )

    out = {"cpu": None, "memory": [], "gpu": [], "board": None, "os": None,
           "errors": []}

    data, err = _ps_json(cpu_ps)
    if data:
        out["cpu"] = data
    elif err:
        out["errors"].append(f"CPU：{err}")

    data, err = _ps_json(mem_ps)
    if data:
        out["memory"] = data if isinstance(data, list) else [data]
    elif err:
        out["errors"].append(f"内存：{err}")

    data, err = _ps_json(gpu_ps)
    if data:
        out["gpu"] = data if isinstance(data, list) else [data]
    elif err:
        out["errors"].append(f"显卡：{err}")

    data, err = _ps_json(board_ps)
    if data:
        out["board"] = data

    data, err = _ps_json(os_ps)
    if data:
        out["os"] = data

    return out


def disk_health() -> dict:
    """物理磁盘 + 分区占用 + 失败预测。

    SMART 细节（通电时长、重分配扇区数）需要管理员权限且各家厂商格式不同，
    这里取 Windows 自己能给的：**失败预测**（MSStorageDriver_FailurePredictStatus）
    与磁盘状态。拿不到就如实说拿不到，不编造。
    """
    phys_ps = (
        "Get-CimInstance Win32_DiskDrive | "
        "Select-Object Index,Model,InterfaceType,Size,MediaType,Status,"
        "SerialNumber | ConvertTo-Json -Compress"
    )
    pred_ps = (
        "try { Get-CimInstance -Namespace root\\wmi "
        "-ClassName MSStorageDriver_FailurePredictStatus -ErrorAction Stop | "
        "Select-Object InstanceName,PredictFailure,Reason | "
        "ConvertTo-Json -Compress } catch { '[]' }"
    )
    vol_ps = (
        "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | "
        "Select-Object DeviceID,Size,FreeSpace,FileSystem,VolumeName | "
        "ConvertTo-Json -Compress"
    )

    out = {"physical": [], "volumes": [], "predict": [], "errors": [],
           "predict_available": False}

    data, err = _ps_json(phys_ps)
    if data:
        out["physical"] = data if isinstance(data, list) else [data]
    elif err:
        out["errors"].append(f"物理磁盘：{err}")

    data, err = _ps_json(vol_ps)
    if data:
        out["volumes"] = data if isinstance(data, list) else [data]
    elif err:
        out["errors"].append(f"分区：{err}")

    data, err = _ps_json(pred_ps)
    if isinstance(data, list) and data:
        out["predict"] = data
        out["predict_available"] = True
    else:
        # 这个类需要管理员权限，普通权限下拿不到是正常的
        out["errors"].append(
            "失败预测（SMART）需要管理员权限，当前读不到 —— "
            "以管理员身份重启后再看")

    return out


# ===========================================================================
# 三、大文件查找（只列不删）
# ===========================================================================
def _walk_files(roots, cancel, progress, min_size, on_file, visited_cap=400000):
    """在 roots 下遍历文件，对每个 >= min_size 的文件调 on_file。

    跳过重解析点（符号链接/联接），否则可能绕出范围或成环。
    """
    seen = 0
    for root in roots:
        if cancel is not None and cancel.is_set():
            return
        stack = [root]
        while stack:
            if cancel is not None and cancel.is_set():
                return
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for e in it:
                        seen += 1
                        if seen > visited_cap:
                            return
                        if seen % 800 == 0 and progress is not None:
                            progress(f"已检查 {seen} 项…")
                        try:
                            if e.is_dir(follow_symlinks=False):
                                if e.name.lower() in _SKIP_DIRS:
                                    continue
                                st = e.stat(follow_symlinks=False)
                                if getattr(st, "st_file_attributes", 0) & \
                                        FILE_ATTRIBUTE_REPARSE_POINT:
                                    continue
                                stack.append(e.path)
                            elif e.is_file(follow_symlinks=False):
                                st = e.stat(follow_symlinks=False)
                                if st.st_size >= min_size:
                                    on_file(e.path, st.st_size)
                        except OSError:
                            continue
            except OSError:
                continue


def _min_bytes(min_mb) -> int:
    """把「最小 MB」换算成字节。

    下限 **1 MB**：找大文件/重复文件时把阈值放到 1MB 以下是没意义的
    —— 全盘几百万个小文件，扫到天荒地老还都是些碎图。
    注意用 `int(float(x))` 而不是 `int(x)`：直接 int() 会把 0.5 变成 0，
    再被下限兜成 1，用户以为设了 0.5 其实设了 1。
    """
    try:
        mb = float(min_mb)
    except (TypeError, ValueError):
        mb = 1.0
    return max(1, int(mb)) * 1048576


def find_large_files(roots, min_mb=200, limit=300, cancel=None,
                     progress=None) -> dict:
    """找大文件。**只列出来，不删除任何东西。**"""
    min_size = _min_bytes(min_mb)
    found = []

    def on_file(path, size):
        found.append({"path": path, "size": size})

    _walk_files(roots, cancel, progress, min_size, on_file)

    found.sort(key=lambda x: -x["size"])
    total = sum(x["size"] for x in found)
    truncated = len(found) > limit
    return {
        "files": found[:limit],
        "count": len(found),
        "total": total,
        "truncated": truncated,
        "min_mb": min_mb,
    }


# ===========================================================================
# 四、重复文件查找（只列不删）
# ===========================================================================
def _hash_file(path, chunk=1048576) -> str | None:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
    except OSError:
        return None
    return h.hexdigest()


def find_duplicates(roots, min_mb=1, limit=200, cancel=None,
                    progress=None) -> dict:
    """找重复文件。

    三步走，避免一上来就全盘哈希：
      1. 按**文件大小**分组 —— 大小不同的不可能是重复文件
      2. 只对「同尺寸且多于一个」的文件算**前 64KB 哈希**做快速排除
      3. 剩下的算**完整哈希**确认

    **只列出来，不删除任何东西。**
    """
    min_size = _min_bytes(min_mb)
    by_size: dict[int, list[str]] = {}

    def on_file(path, size):
        by_size.setdefault(size, []).append(path)

    _walk_files(roots, cancel, progress, min_size, on_file)

    candidates = {s: p for s, p in by_size.items() if len(p) > 1}
    if progress is not None:
        progress(f"{len(by_size)} 种尺寸，其中 {len(candidates)} 种有重复嫌疑")

    groups = []
    checked = 0
    for size, paths in sorted(candidates.items(), reverse=True):
        if cancel is not None and cancel.is_set():
            break
        # 第二步：前 64KB 哈希
        head: dict[str, list[str]] = {}
        for p in paths:
            try:
                with open(p, "rb") as f:
                    part = f.read(65536)
            except OSError:
                continue
            head.setdefault(hashlib.sha256(part).hexdigest(), []).append(p)

        for _, same_head in head.items():
            if len(same_head) < 2:
                continue
            # 第三步：完整哈希
            full: dict[str, list[str]] = {}
            for p in same_head:
                if cancel is not None and cancel.is_set():
                    break
                checked += 1
                if progress is not None and checked % 20 == 0:
                    progress(f"已校验 {checked} 个文件…")
                d = _hash_file(p)
                if d:
                    full.setdefault(d, []).append(p)

            for digest, same in full.items():
                if len(same) < 2:
                    continue
                groups.append({
                    "hash": digest[:16],
                    "size": size,
                    "count": len(same),
                    "wasted": size * (len(same) - 1),
                    "paths": sorted(same),
                })

    groups.sort(key=lambda g: -g["wasted"])
    total_wasted = sum(g["wasted"] for g in groups)
    truncated = len(groups) > limit
    return {
        "groups": groups[:limit],
        "group_count": len(groups),
        "wasted": total_wasted,
        "truncated": truncated,
        "min_mb": min_mb,
    }


# ===========================================================================
# 扫描根目录
# ===========================================================================
def default_roots() -> list[str]:
    """默认扫描根：所有**固定**磁盘的根目录。

    盘符类型的取值（Win32 GetDriveType）：
        0 未知 / 1 无根目录 / **2 可移动** / **3 固定** / 4 网络 / 5 光驱 / 6 内存盘

    这里踩过一次：把固定磁盘当成 2 了（2 其实是可移动），结果 C: 和 D:
    全被跳过、扫描根只剩个兜底值。常量直接复用 junk 里那份，别再各写一遍。
    """
    if not IS_WINDOWS:
        return [os.path.expanduser("~")]
    roots = []
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetLogicalDrives.restype = ctypes.c_uint
        k32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
        k32.GetDriveTypeW.restype = ctypes.c_uint

        mask = k32.GetLogicalDrives()
        for i in range(26):
            if not (mask >> i) & 1:
                continue
            root = f"{chr(ord('A') + i)}:\\"
            if k32.GetDriveTypeW(root) == DRIVE_FIXED:
                roots.append(root)
    except Exception:                                       # noqa: BLE001
        pass
    return roots or ["C:\\"]
