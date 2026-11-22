# -*- coding: utf-8 -*-
"""Windows 服务控制（SCM）。

为什么需要这个模块
------------------
"进程关不干净"最常见的原因**不是**权限不够，而是目标进程背后挂着一个
Windows 服务：

    结束 HipsDaemon.exe 的进程 → 服务控制管理器(SCM)判定服务异常退出
    → 按恢复策略把它重新拉起来 → 用户看到"关了又回来"。

正确的做法是**停服务**而不是杀进程：ControlService(STOP) 会让服务
正常退出，SCM 不会把它当作崩溃重启。对开机自启(AUTO)的服务，
如果只停不限制自启，下次触发或重启还会回来 —— 所以这里额外提供
"临时禁用"，并把原始启动类型记下来以便还原。

全部走 advapi32，不依赖 sc.exe 的输出格式（它会随系统语言变化）。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

# --- 常量 ---------------------------------------------------------------
SC_MANAGER_CONNECT = 0x0001
SC_MANAGER_ENUMERATE_SERVICE = 0x0004
SC_MANAGER_MODIFY_BOOT_CONFIG = 0x0020

SERVICE_QUERY_CONFIG = 0x0001
SERVICE_CHANGE_CONFIG = 0x0002
SERVICE_QUERY_STATUS = 0x0004
SERVICE_STOP = 0x0020
SERVICE_START = 0x0010

SERVICE_WIN32 = 0x00000030
SERVICE_STATE_ALL = 0x00000003

SERVICE_STOPPED = 0x00000001
SERVICE_START_PENDING = 0x00000002
SERVICE_STOP_PENDING = 0x00000003
SERVICE_RUNNING = 0x00000004

SERVICE_ACCEPT_STOP = 0x0001

SERVICE_CONTROL_STOP = 0x00000001

SERVICE_NO_CHANGE = 0xFFFFFFFF

SERVICE_BOOT_START = 0x00000000
SERVICE_SYSTEM_START = 0x00000001
SERVICE_AUTO_START = 0x00000002
SERVICE_DEMAND_START = 0x00000003
SERVICE_DISABLED = 0x00000004

SC_STATUS_PROCESS_INFO = 0

STATE_TEXT = {
    SERVICE_STOPPED: "已停止",
    SERVICE_START_PENDING: "正在启动",
    SERVICE_STOP_PENDING: "正在停止",
    SERVICE_RUNNING: "运行中",
}

START_TEXT = {
    SERVICE_BOOT_START: "引导启动",
    SERVICE_SYSTEM_START: "系统启动",
    SERVICE_AUTO_START: "自动",
    SERVICE_DEMAND_START: "手动",
    SERVICE_DISABLED: "已禁用",
}


class SERVICE_STATUS_PROCESS(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", wintypes.DWORD),
        ("dwCurrentState", wintypes.DWORD),
        ("dwControlsAccepted", wintypes.DWORD),
        ("dwWin32ExitCode", wintypes.DWORD),
        ("dwServiceSpecificExitCode", wintypes.DWORD),
        ("dwCheckPoint", wintypes.DWORD),
        ("dwWaitHint", wintypes.DWORD),
        ("dwProcessId", wintypes.DWORD),
        ("dwServiceFlags", wintypes.DWORD),
    ]


class ENUM_SERVICE_STATUS_PROCESSW(ctypes.Structure):
    _fields_ = [
        ("lpServiceName", wintypes.LPWSTR),
        ("lpDisplayName", wintypes.LPWSTR),
        ("ServiceStatusProcess", SERVICE_STATUS_PROCESS),
    ]


class QUERY_SERVICE_CONFIGW(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", wintypes.DWORD),
        ("dwStartType", wintypes.DWORD),
        ("dwErrorControl", wintypes.DWORD),
        ("lpBinaryPathName", wintypes.LPWSTR),
        ("lpLoadOrderGroup", wintypes.LPWSTR),
        ("dwTagId", wintypes.DWORD),
        ("lpDependencies", wintypes.LPWSTR),
        ("lpServiceStartName", wintypes.LPWSTR),
        ("lpDisplayName", wintypes.LPWSTR),
    ]


_k = ctypes


def _k32(name, restype, argtypes):
    f = getattr(advapi32, name)
    f.restype = restype
    f.argtypes = argtypes
    return f


OpenSCManagerW = _k32("OpenSCManagerW", wintypes.HANDLE,
                      [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD])
OpenServiceW = _k32("OpenServiceW", wintypes.HANDLE,
                    [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD])
CloseServiceHandle = _k32("CloseServiceHandle", wintypes.BOOL, [wintypes.HANDLE])
EnumServicesStatusExW = _k32(
    "EnumServicesStatusExW", wintypes.BOOL,
    [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, wintypes.DWORD,
     ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
     ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
     wintypes.LPCWSTR])
ControlService = _k32("ControlService", wintypes.BOOL,
                      [wintypes.HANDLE, wintypes.DWORD,
                       ctypes.POINTER(SERVICE_STATUS_PROCESS)])
QueryServiceStatusEx = _k32(
    "QueryServiceStatusEx", wintypes.BOOL,
    [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
     ctypes.POINTER(wintypes.DWORD)])
QueryServiceConfigW = _k32(
    "QueryServiceConfigW", wintypes.BOOL,
    [wintypes.HANDLE, ctypes.POINTER(QUERY_SERVICE_CONFIGW), wintypes.DWORD,
     ctypes.POINTER(wintypes.DWORD)])
ChangeServiceConfigW = _k32(
    "ChangeServiceConfigW", wintypes.BOOL,
    [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
     wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD),
     wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR])
StartServiceW = _k32("StartServiceW", wintypes.BOOL,
                     [wintypes.HANDLE, wintypes.DWORD,
                      ctypes.POINTER(wintypes.LPCWSTR)])


def _err_text(err: int) -> str:
    """把 Win32 错误码翻成用户看得懂的话。"""
    return {
        5: "需要管理员权限（用「以管理员重启」后再试）",
        87: "参数不正确",
        1051: "依赖的服务没有运行",
        1052: "该服务不接受这个控制指令",
        1053: "服务没有及时响应",
        1056: "服务已在运行",
        1060: "指定的服务不存在",
        1061: "服务当前无法接受控制指令（正在忙）",
        1072: "该服务已被标记为删除",
        1073: "服务已存在",
        1721: "资源不足，无法启动服务",
        1722: "RPC 服务器不可用",
    }.get(err, f"系统错误 {err}")


def _open_scm():
    h = OpenSCManagerW(None, None,
                       SC_MANAGER_CONNECT | SC_MANAGER_ENUMERATE_SERVICE)
    return h if h else None


def _status(hsvc) -> SERVICE_STATUS_PROCESS | None:
    st = SERVICE_STATUS_PROCESS()
    need = wintypes.DWORD()
    if QueryServiceStatusEx(hsvc, SC_STATUS_PROCESS_INFO,
                            ctypes.byref(st), ctypes.sizeof(st),
                            ctypes.byref(need)):
        return st
    return None


def enum_services() -> list[dict]:
    """枚举全部 Win32 服务，返回 name/display/state/start_mode/pid。"""
    hscm = _open_scm()
    if not hscm:
        return []
    out: list[dict] = []
    try:
        buf_size = 256 * 1024
        while True:
            buf = ctypes.create_string_buffer(buf_size)
            needed = wintypes.DWORD()
            returned = wintypes.DWORD()
            resume = wintypes.DWORD()
            ok = EnumServicesStatusExW(
                hscm, 0, SERVICE_WIN32, SERVICE_STATE_ALL,
                ctypes.cast(buf, ctypes.c_void_p), buf_size,
                ctypes.byref(needed), ctypes.byref(returned),
                ctypes.byref(resume), None)
            if not ok:
                err = ctypes.get_last_error()
                # ERROR_MORE_DATA = 234，缓冲区不够，按提示扩容重来
                if err == 234 and needed.value > buf_size:
                    buf_size = int(needed.value * 1.3)
                    continue
                break
            arr = ctypes.cast(
                buf, ctypes.POINTER(ENUM_SERVICE_STATUS_PROCESSW))
            for i in range(returned.value):
                it = arr[i]
                sp = it.ServiceStatusProcess
                out.append({
                    "name": it.lpServiceName or "",
                    "display": it.lpDisplayName or "",
                    "state": sp.dwCurrentState,
                    "state_text": STATE_TEXT.get(sp.dwCurrentState, "未知"),
                    "pid": sp.dwProcessId,
                    "accept_stop": bool(sp.dwControlsAccepted
                                        & SERVICE_ACCEPT_STOP),
                })
            break
    finally:
        CloseServiceHandle(hscm)

    # 补上启动类型（Enum 不返回，只能逐个查）
    for svc in out:
        svc["start_mode"] = start_type(svc["name"])
    return out


def service_map() -> dict[int, list[dict]]:
    """PID -> 该 PID 承载的服务列表。

    一个 svchost.exe 可能同时承载多个服务，所以值是列表。
    """
    m: dict[int, list[dict]] = {}
    for s in enum_services():
        pid = s.get("pid") or 0
        if pid:
            m.setdefault(pid, []).append(s)
    return m


def start_type(name: str) -> int | None:
    """服务的启动类型（AUTO / DEMAND / DISABLED…）。"""
    hscm = _open_scm()
    if not hscm:
        return None
    try:
        hsvc = OpenServiceW(hscm, name, SERVICE_QUERY_CONFIG)
        if not hsvc:
            return None
        try:
            cfg = QUERY_SERVICE_CONFIGW()
            need = wintypes.DWORD()
            if QueryServiceConfigW(hsvc, ctypes.byref(cfg),
                                   ctypes.sizeof(cfg), ctypes.byref(need)):
                return cfg.dwStartType
            # 缓冲区不够时按 need 再来一次
            raw = ctypes.create_string_buffer(max(need.value, 1024))
            if QueryServiceConfigW(
                    hsvc, ctypes.cast(raw, ctypes.POINTER(QUERY_SERVICE_CONFIGW)),
                    len(raw), ctypes.byref(need)):
                cfg2 = ctypes.cast(
                    raw, ctypes.POINTER(QUERY_SERVICE_CONFIGW)).contents
                return cfg2.dwStartType
            return None
        finally:
            CloseServiceHandle(hsvc)
    finally:
        CloseServiceHandle(hscm)


def stop_service(name: str, timeout: float = 10.0) -> tuple[bool, str]:
    """停止服务并等待真正停下。

    返回 ``(是否成功, 说明)``。已停止视为成功。
    """
    import time

    hscm = _open_scm()
    if not hscm:
        return False, "无法连接服务控制管理器（需要管理员权限）"
    try:
        hsvc = OpenServiceW(hscm, name,
                            SERVICE_QUERY_STATUS | SERVICE_STOP)
        if not hsvc:
            err = ctypes.get_last_error()
            return False, f"无法打开服务：{_err_text(err)}"
        try:
            st = _status(hsvc)
            if st is None:
                return False, "无法查询服务状态"
            if st.dwCurrentState == SERVICE_STOPPED:
                return True, "服务已是停止状态"
            if not (st.dwControlsAccepted & SERVICE_ACCEPT_STOP):
                return False, ("该服务不接受「停止」指令"
                               "（驱动/内核类服务，需在设备管理器处理）")

            stc = SERVICE_STATUS_PROCESS()
            if not ControlService(hsvc, SERVICE_CONTROL_STOP, ctypes.byref(stc)):
                err = ctypes.get_last_error()
                # 1061 = 服务现在无法接受控制指令（正在忙），等一下重试
                if err == 1061:
                    time.sleep(0.5)
                    if not ControlService(hsvc, SERVICE_CONTROL_STOP,
                                          ctypes.byref(stc)):
                        return False, (f"发送停止指令失败："
                                          f"{_err_text(ctypes.get_last_error())}")
                else:
                    return False, f"发送停止指令失败：{_err_text(err)}"

            deadline = time.time() + timeout
            while time.time() < deadline:
                st = _status(hsvc)
                if st is None:
                    return False, "停止过程中无法查询状态"
                if st.dwCurrentState == SERVICE_STOPPED:
                    return True, "服务已停止"
                time.sleep(0.2)
            return False, "等待超时，服务仍在停止中"
        finally:
            CloseServiceHandle(hsvc)
    finally:
        CloseServiceHandle(hscm)


def set_start_type(name: str, mode: int) -> tuple[bool, str]:
    """修改服务启动类型（用于"临时禁用"）。"""
    hscm = _open_scm()
    if not hscm:
        return False, "无法连接服务控制管理器（需要管理员权限）"
    try:
        hsvc = OpenServiceW(hscm, name, SERVICE_CHANGE_CONFIG)
        if not hsvc:
            return False, f"无法打开服务：{_err_text(ctypes.get_last_error())}"
        try:
            ok = ChangeServiceConfigW(hsvc, SERVICE_NO_CHANGE, mode,
                                      SERVICE_NO_CHANGE, None, None, None,
                                      None, None, None, None)
            if not ok:
                return False, f"修改失败：{_err_text(ctypes.get_last_error())}"
            return True, "已修改启动类型"
        finally:
            CloseServiceHandle(hsvc)
    finally:
        CloseServiceHandle(hscm)


def start_service(name: str, timeout: float = 10.0) -> tuple[bool, str]:
    """启动服务（用于还原）。"""
    import time

    hscm = _open_scm()
    if not hscm:
        return False, "无法连接服务控制管理器（需要管理员权限）"
    try:
        hsvc = OpenServiceW(hscm, name,
                            SERVICE_QUERY_STATUS | SERVICE_START)
        if not hsvc:
            return False, f"无法打开服务：{_err_text(ctypes.get_last_error())}"
        try:
            st = _status(hsvc)
            if st is not None and st.dwCurrentState == SERVICE_RUNNING:
                return True, "服务已在运行"
            if not StartServiceW(hsvc, 0, None):
                err = ctypes.get_last_error()
                if err == 1056:            # 已在运行
                    return True, "服务已在运行"
                return False, f"启动失败：{_err_text(err)}"
            deadline = time.time() + timeout
            while time.time() < deadline:
                st = _status(hsvc)
                if st is None:
                    break
                if st.dwCurrentState == SERVICE_RUNNING:
                    return True, "服务已启动"
                time.sleep(0.2)
            return False, "启动超时"
        finally:
            CloseServiceHandle(hsvc)
    finally:
        CloseServiceHandle(hscm)


# ---------------------------------------------------------------------------
# 打游戏时建议停掉的系统服务
#
# 只收「停了不影响系统稳定、且确实占资源」的项。每项都写明停了会失去什么，
# 由用户自己决定 —— 不替用户判断。
# ---------------------------------------------------------------------------
GAMING_SERVICES: dict[str, str] = {
    "Spooler": "打印后台处理（不用打印机可停）",
    "WSearch": "Windows 搜索索引（索引时很吃 CPU/磁盘）",
    "SysMain": "SuperFetch 预读（机械盘有用，SSD 上收益有限）",
    "DiagTrack": "连接用户体验和遥测",
    "dmwappushservice": "WAP 推送消息路由",
    "MapsBroker": "下载的地图管理",
    "Fax": "传真",
    "RemoteRegistry": "远程注册表访问（有安全风险，建议停）",
    "WMPNetworkSvc": "Windows Media Player 网络共享",
    "XblAuthManager": "Xbox 身份验证（不玩 Xbox 游戏可停）",
    "XblGameSave": "Xbox 游戏存档",
    "XboxNetApiSvc": "Xbox Live 网络",
    "XboxGipSvc": "Xbox 配件管理",
    "RetailDemo": "零售演示模式",
    "PhoneSvc": "电话服务",
    "TabletInputService": "触摸键盘与手写面板",
}
