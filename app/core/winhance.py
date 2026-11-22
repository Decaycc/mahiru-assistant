# -*- coding: utf-8 -*-
"""WinHance 游戏与性能调校后端。

把 Winhance 的「游戏和性能」设置（见 ``tunes_winhance.py``，116 条）接到
mahiru 里。这里做四件事：

  1. 把设置元数据（名称/描述/选项/推荐值/默认值）暴露给前端
  2. 按 Winhance 的语义把一条设置真正写进注册表 / 计划任务 / PowerShell
  3. 每次写之前把旧值备份到 ``config/winhance_config.json``，方便日后还原
  4. 读注册表里每条设置的真实当前值，回填前端的开关/下拉状态

语义与 Winhance 的 C# 源码逐条对齐（``WindowsRegistryService.ApplySetting``、
``SettingOperationExecutor``、``SettingDefinitionToggleState``）。关键点：

  * ``enabled``/``disabled`` 数组里的 ``None`` 是「删除该值」（键缺失 = 开/关）
  * ``value_type`` 只可能是 ``dword`` / ``string`` / ``binary``
  * 视觉效果的 ``binary`` 项走「按位掩码置位/清位」，不是整值覆盖
  * ``gaming-dns-server`` 与 ``system-restore-protection`` 没有注册表项，
    只能跑 PowerShell 脚本（生成器没带脚本正文，这里硬编码）
"""
import base64
import json
import os
import re
import subprocess

import winreg

from app.paths import config_dir
from app.core import tunes_winhance as tunes

CONFIG_PATH = os.path.join(config_dir(), "winhance_config.json")

# 生成器只抽了 reg/options/scheduled/detection_type，PowerShell 脚本正文在
# Winhance 源码里，这里按源语义硬编码（见 GamingAndPerformanceOptimizations.cs
# 的 gaming-dns-server 与 system-restore-protection 两条）。
DNS_SET_SCRIPT = (
    "Get-NetAdapter | ForEach-Object { "
    "Set-DnsClientServerAddress -InterfaceIndex $_.InterfaceIndex "
    "-ServerAddresses @('{{primary}}','{{secondary}}') }"
)
DNS_RESET_SCRIPT = (
    "Get-NetAdapter | ForEach-Object { "
    "Set-DnsClientServerAddress -InterfaceIndex $_.InterfaceIndex "
    "-ResetServerAddresses }"
)
SYSTEMRESTORE_ENABLE = "Enable-ComputerRestore -Drive 'C:\\'"
SYSTEMRESTORE_DISABLE = "Disable-ComputerRestore -Drive 'C:\\'"

_ROOT_MAP = {
    "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
    "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
}

# 显式 None 哨兵：selection 的 value_mappings 里 None 表示「删除值」，
# 不能和「没传 specific_value」混为一谈。
_UNSET = object()

_CREATE_NO_WINDOW = 0x08000000


# ---------------------------------------------------------------------------
# 基础：路径解析 + 注册表读写
# ---------------------------------------------------------------------------

def _split_key(key_path: str):
    """把 ``HKEY_XXX\\a\\b`` 拆成 ``(winreg 根, 子键)``。"""
    head, sep, tail = key_path.partition("\\")
    root = _ROOT_MAP.get(head.upper())
    if root is None:
        raise ValueError(f"未知根键：{head}")
    return root, tail if sep else ""


def _reg_type(value_type: str):
    """把生成器里的 value_type 映射到 winreg 常量。"""
    return {
        "dword": winreg.REG_DWORD,
        "string": winreg.REG_SZ,
        "binary": winreg.REG_BINARY,
    }[value_type]


def _coerce(value, value_type):
    """写注册表前把值转成 winreg 能接受的原生类型。"""
    if value_type == "dword":
        return int(value)
    if value_type == "string":
        return str(value)
    if value_type == "binary":
        return bytes(value)
    return value


def _read_raw(key_path: str, value_name: str):
    """读单个注册表值，返回 ``(值, 类型)``；键/值不存在返回 ``(None, None)``。"""
    try:
        root, sub = _split_key(key_path)
        with winreg.OpenKey(root, sub, 0, winreg.KEY_READ) as key:
            val, typ = winreg.QueryValueEx(key, value_name)
            return val, typ
    except FileNotFoundError:
        return None, None
    except Exception:                                       # noqa: BLE001
        return None, None


def _write_value(key_path: str, value_name: str, value, value_type: str) -> bool:
    """写一个注册表值（自动建键）。``value`` 传 None 表示删除。"""
    try:
        root, sub = _split_key(key_path)
        if value is None:
            with winreg.OpenKey(root, sub, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, value_name)
            return True
        with winreg.CreateKey(root, sub) as key:
            winreg.SetValueEx(key, value_name, 0, _reg_type(value_type),
                              _coerce(value, value_type))
        return True
    except FileNotFoundError:
        return True                                        # 本就没有，视为成功
    except Exception:                                       # noqa: BLE001
        return False


def _delete_value(key_path: str, value_name: str) -> bool:
    return _write_value(key_path, value_name, None, "dword")


def _delete_key(key_path: str) -> bool:
    """删除整把子键（键存在性开关的「关」分支）。"""
    try:
        root, sub = _split_key(key_path)
        winreg.DeleteKey(root, sub)
        return True
    except FileNotFoundError:
        return True
    except Exception:                                       # noqa: BLE001
        return False


def _create_key(key_path: str) -> bool:
    try:
        root, sub = _split_key(key_path)
        winreg.CreateKey(root, sub).Close()
        return True
    except Exception:                                       # noqa: BLE001
        return False


def _sub_keys(key_path: str):
    """列出一把键的直接子键名（逐接口/逐显示器写值用）。"""
    try:
        root, sub = _split_key(key_path)
        with winreg.OpenKey(root, sub, 0, winreg.KEY_READ) as key:
            count = winreg.QueryInfoKey(key)[0]
            return [winreg.EnumKey(key, i) for i in range(count)]
    except Exception:                                       # noqa: BLE001
        return []


# ---------------------------------------------------------------------------
# 备份
# ---------------------------------------------------------------------------

def _load_backup() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                       # noqa: BLE001
        return {}


def _save_backup(data: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:                                       # noqa: BLE001
        pass


def _snapshot(tune: dict) -> None:
    """写之前把该设置所有注册表值的当前状态存进备份文件。

    binary 值 base64 编码（JSON 装不下 bytes）。只备份 ``reg`` 条目，
    计划任务与 PowerShell 脚本不备份（没有可逆的旧值）。
    """
    entries = []
    for reg in tune.get("reg") or []:
        if reg.get("per_interface") or reg.get("per_monitor"):
            # 逐接口/逐显示器：备份每个子键下的同名值
            for sk in _sub_keys(reg["key_path"]):
                full = reg["key_path"] + "\\" + sk
                val, _typ = _read_raw(full, reg["value_name"])
                entries.append(_backup_entry(full, reg["value_name"], val))
        else:
            val, _typ = _read_raw(reg["key_path"], reg["value_name"])
            entries.append(_backup_entry(reg["key_path"], reg["value_name"], val))

    data = _load_backup()
    data[tune["id"]] = entries
    _save_backup(data)


def _backup_entry(key_path: str, value_name: str, value) -> dict:
    entry = {"key_path": key_path, "value_name": value_name}
    if isinstance(value, bytes):
        entry["value"] = base64.b64encode(value).decode("ascii")
        entry["binary"] = True
    elif value is None:
        entry["existed"] = False
    else:
        entry["value"] = value
    return entry


# ---------------------------------------------------------------------------
# 写值语义（对齐 WindowsRegistryService.ApplySetting）
# ---------------------------------------------------------------------------

def _first_non_null(values):
    """``GetWriteValue``：数组里第一个非 null 元素；全 null/空 返回 None。"""
    for v in values or []:
        if v is not None:
            return v
    return None


def _parent_disable(disabled):
    """``GetParentDisableValue``：``[1, null]`` 取 index1（父级级联禁用=删值）。"""
    if disabled is None:
        return None
    if len(disabled) > 1:
        return disabled[1]
    return _first_non_null(disabled)


def _modify_binary_bit(key_path: str, value_name: str, byte_index: int,
                       bit_mask: int, set_bit: bool) -> bool:
    """按位掩码置位/清位（视觉效果的 UserPreferencesMask）。"""
    try:
        current = _read_raw(key_path, value_name)[0]
        if not isinstance(current, bytes):
            current = bytes(max(12, byte_index + 1))
        if len(current) <= byte_index:
            current = current + bytes(byte_index + 1 - len(current))
        data = bytearray(current)
        if set_bit:
            data[byte_index] |= bit_mask
        else:
            data[byte_index] &= ~bit_mask & 0xFF
        return _write_value(key_path, value_name, bytes(data), "binary")
    except Exception:                                       # noqa: BLE001
        return False


def _modify_binary_byte(key_path: str, value_name: str, byte_index: int,
                        new_value: int) -> bool:
    try:
        current = _read_raw(key_path, value_name)[0]
        if not isinstance(current, bytes):
            current = bytes(max(12, byte_index + 1))
        if len(current) <= byte_index:
            current = current + bytes(byte_index + 1 - len(current))
        data = bytearray(current)
        data[byte_index] = new_value & 0xFF
        return _write_value(key_path, value_name, bytes(data), "binary")
    except Exception:                                       # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# 复合字符串（composite string）值
#
# ``HKCU\Software\Microsoft\DirectX\UserGpuPreferences`` 的
# ``DirectXUserGlobalSettings`` 是一条 ``Key=Value;Key=Value;`` 的多段字符串，
# 三条游戏设置（SwapEffectUpgradeEnable / VRROptimizeEnable / AutoHDREnable）
# 共用它。若不按子键拆开读写的后果：点一个开关会把整串改写成 "1"/"0"，
# 另外两条设置跟着一起变，而且用户原有的其它子键（GpuPreference 等）会被抹掉。
#
# 语义与 Winhance 的 ``WindowsRegistryService.ParseCompositeString`` /
# ``BuildCompositeString`` / ``ApplySetting`` 逐行对齐。
# ---------------------------------------------------------------------------

def _parse_composite(text):
    """``"a=1;b=2;"`` -> ``{"a": "1", "b": "2"}``（键大小写不敏感）。"""
    pairs = {}
    if not text:
        return pairs
    for entry in str(text).split(";"):
        if not entry:
            continue
        eq = entry.find("=")
        if eq > 0:
            key = entry[:eq].strip()
            if key:
                pairs[key.lower()] = (key, entry[eq + 1:])
    # 统一返回 {小写键: (原始键名, 值)}
    return pairs


def _build_composite(pairs):
    """``{"a": "1"}`` -> ``"a=1;"``（保留传入顺序，末尾带分号）。"""
    if not pairs:
        return ""
    return "".join(f"{k}={v};" for k, v in pairs.items())


def _composite_get(text, sub_key):
    """取子键值；不存在返回 ``None``（与「值为空串」区分开）。"""
    hit = _parse_composite(text).get((sub_key or "").lower())
    return None if hit is None else hit[1]


def _composite_set(text, sub_key, value):
    """设置子键值；``value`` 为 None 时删除该子键。其余子键原样保留。"""
    parsed = _parse_composite(text)
    low = (sub_key or "").lower()
    if value is None:
        parsed.pop(low, None)
    else:
        # 已存在就沿用原来的键名大小写，避免无意义的大小写抖动
        orig = parsed[low][0] if low in parsed else sub_key
        parsed[low] = (orig, str(value))
    return _build_composite({orig: val for _low, (orig, val) in parsed.items()})


def _apply_composite(reg: dict, enable: bool, specific_value=_UNSET,
                     use_default: bool = False) -> bool:
    """只改写自己那一段子键，整串其它内容原样写回。"""
    sub = reg["composite_string_key"]
    current, _typ = _read_raw(reg["key_path"], reg["value_name"])
    current = current if isinstance(current, str) else ""

    if use_default:
        new = reg.get("default")
    elif specific_value is not _UNSET:
        new = specific_value
    else:
        new = _first_non_null(reg.get("enabled") if enable else reg.get("disabled"))

    merged = _composite_set(current, sub, new)
    return _write_value(reg["key_path"], reg["value_name"], merged, "string")


def _read_composite_state(tune: dict, reg: dict):
    """读一条 composite 设置的真实开/关，返回 ``True/False/None``。

    子键缺失时**不能当成「关」**：VRR 的 DefaultValue 是 "1"（默认开），
    按 Winhance 的 ``IsRegistryValueInEnabledState``，缺失时拿 DefaultValue
    去和 EnabledValue 比；没有 DefaultValue 就是 "None == 1" → 关。
    只有整条注册表值读不出来（键/值不存在）才返回 None。
    """
    sub = reg["composite_string_key"]
    current, _typ = _read_raw(reg["key_path"], reg["value_name"])
    if current is None:
        return None
    val = _composite_get(current if isinstance(current, str) else "", sub)
    if val is None:
        val = reg.get("default")
    enabled = _first_non_null(reg.get("enabled"))
    if enabled is None:
        return None
    if val is None:
        return False
    return _values_equal(val, enabled)


def _apply_reg(reg: dict, enable: bool, specific_value=_UNSET,
               use_default: bool = False) -> bool:
    """复刻 ``ApplySetting`` 的分支顺序，返回是否成功。

    specific_value 用 ``_UNSET`` 哨兵区分「没传」和「显式传了 None（删值）」。
    """
    if reg.get("per_interface") or reg.get("per_monitor"):
        subkeys = _sub_keys(reg["key_path"])
        if not subkeys:
            return True
        results = []
        for sk in subkeys:
            child = dict(reg)
            child["key_path"] = reg["key_path"] + "\\" + sk
            child["per_interface"] = False
            child["per_monitor"] = False
            results.append(_apply_reg(child, enable, specific_value, use_default))
        return all(results)

    # 键存在性开关（ValueName 为空）：开=建键，关=删键
    if not reg.get("value_name"):
        return _create_key(reg["key_path"]) if enable else _delete_key(reg["key_path"])

    bitmask = reg.get("bitmask")
    byte_index = reg.get("binary_byte_index")
    if bitmask is not None and byte_index is not None:
        set_bit = (bool(specific_value) if specific_value is not _UNSET
                   else enable)
        return _modify_binary_bit(reg["key_path"], reg["value_name"],
                                  byte_index, bitmask, set_bit)

    # 复合字符串（DirectXUserGlobalSettings）：只改自己那一段子键
    if reg.get("composite_string_key"):
        return _apply_composite(reg, enable, specific_value, use_default)

    if reg.get("modify_byte_only") and byte_index is not None:
        new_value = (int(specific_value) if specific_value is not _UNSET
                     else (1 if enable else 0))
        return _modify_binary_byte(reg["key_path"], reg["value_name"],
                                   byte_index, new_value)

    # 常规分支
    if use_default:
        value_to_set = _parent_disable(reg.get("disabled"))
    elif specific_value is not _UNSET:
        value_to_set = specific_value
    else:
        values = reg.get("enabled") if enable else reg.get("disabled")
        value_to_set = _first_non_null(values)

    return _write_value(reg["key_path"], reg["value_name"], value_to_set,
                        reg["value_type"])


# ---------------------------------------------------------------------------
# 计划任务 / PowerShell
# ---------------------------------------------------------------------------

def _run_schtasks(task_path: str, enable: bool) -> bool:
    action = "/Enable" if enable else "/Disable"
    try:
        r = subprocess.run(
            ["schtasks", "/Change", "/TN", task_path, action],
            capture_output=True, text=True, timeout=60,
            creationflags=_CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:                                       # noqa: BLE001
        return False


# 计划任务的定义文件放在这里，含 <Enabled>false</Enabled>。
# 直接读 XML 比 `schtasks /Query` 稳：不受系统语言影响，也不用为 17 条任务
# 各开一个进程。
_TASKS_DIR = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                          "System32", "Tasks")


def _read_task_enabled(task_path: str):
    """读计划任务是否启用，返回 ``True/False/None``（读不到给 None）。"""
    try:
        full = os.path.join(_TASKS_DIR, task_path.lstrip("\\"))
        with open(full, "r", encoding="utf-16", errors="ignore") as f:
            xml = f.read()
    except Exception:                                       # noqa: BLE001
        return None
    # <Settings><Enabled>false</Enabled></Settings>；缺省即为启用
    m = re.search(r"<Enabled>\s*(true|false)\s*</Enabled>", xml, re.IGNORECASE)
    if not m:
        return True
    return m.group(1).lower() == "true"


def _run_powershell(script: str) -> bool:
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            capture_output=True, text=True, timeout=120,
            creationflags=_CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:                                       # noqa: BLE001
        return False


def _apply_scheduled(tune: dict, enable: bool) -> bool:
    results = []
    for task in tune.get("scheduled") or []:
        results.append(_run_schtasks(task["task_path"], enable))
    return all(results) if results else True


def _apply_dns(option: dict) -> bool:
    """DNS 服务器：Automatic 选项跑重置脚本，其余按 script_vars 填 IP。"""
    if option.get("script") == "disabled":
        return _run_powershell(DNS_RESET_SCRIPT)
    vars_ = option.get("script_vars") or {}
    script = DNS_SET_SCRIPT
    for key, val in vars_.items():
        script = script.replace("{{" + key + "}}", str(val))
    return _run_powershell(script)


# ---------------------------------------------------------------------------
# 对外：查 / 应用
# ---------------------------------------------------------------------------

def _find(tune_id: str):
    for t in tunes.TUNES:
        if t["id"] == tune_id:
            return t
    return None


def _recommended_label(tune: dict) -> str:
    """推荐值对应的状态文案（toggle 给开/关，selection 给选项名）。"""
    if tune["input_type"] == "toggle":
        if tune.get("recommended") is None:
            return "无推荐值"
        return "开" if tune["recommended"] else "关"
    for o in tune.get("options") or []:
        if o.get("is_recommended"):
            return o["display"]
    return "无推荐值"


def _default_label(tune: dict) -> str:
    """默认值对应的状态文案（toggle 给开/关，selection 给选项名）。"""
    if tune["input_type"] == "toggle":
        if tune.get("default") is None:
            return "无默认值"
        return "开" if tune["default"] else "关"
    for o in tune.get("options") or []:
        if o.get("is_default"):
            return o["display"]
    return "无默认值"


def list_tunes() -> list:
    """所有设置的元数据（不含当前值，避免 116 条注册表读慢启动）。

    每条附 ``value_hint`` / ``default_hint``：只给面向普通用户的状态文案
    （开/关/选项名），不带 DWORD、字符串这类技术术语（用户明确要求）。
    """
    items = []
    for t in tunes.TUNES:
        items.append({
            "id": t["id"],
            "name": t["name_cn"],
            "desc": t["desc_cn"],
            "group": t["group_cn"] or "其他",
            "input_type": t["input_type"],
            "requires_restart": t["requires_restart"],
            "subjective": t["subjective"],
            "recommended": t["recommended"],
            "default": t["default"],
            "value_hint": _recommended_label(t),
            "default_hint": _default_label(t),
            "options": [{
                "display": o["display"],
                "is_default": o.get("is_default"),
                "is_recommended": o.get("is_recommended"),
                "warning": o.get("warning"),
            } for o in t.get("options") or []],
        })
    return items


def _primary_reg(tune: dict):
    """取主注册表项（is_primary 优先，否则第一条）；无注册表项返回 None。"""
    regs = tune.get("reg") or []
    for r in regs:
        if r.get("is_primary"):
            return r
    return regs[0] if regs else None


def _values_equal(a, b) -> bool:
    """数值比较兜底：字符串/数字按 Convert.ToInt64 语义对齐。"""
    if a is None or b is None:
        return a is b
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return a == b


def _read_toggle_state(tune: dict, reg: dict):
    """读一个 toggle 的真实开/关，返回 ``True/False/None``。

    分三种写法，缺一不可（否则界面上的开关永远停在"关"，看不出真实状态）：
      * 复合字符串子键（DirectXUserGlobalSettings）→ 只比对自己那一段
      * 按位掩码（UserPreferencesMask）→ 看对应字节的那一位
      * 常规整值 → 拿当前值和 enabled/disabled 数组比较

    对齐 ``IsRegistryValueInEnabledState``：值不存在时不能一律当"关"，
    而是拿 DefaultValue 去和 EnabledValue 比（VRR 默认就是开的）。
    只有「读不到注册表」（如需要管理员权限的 HKLM 项）才返回 None，
    让界面显示"未知"而不是谎报成"关"。
    """
    # 复合字符串：只读自己那一段
    if reg.get("composite_string_key"):
        return _read_composite_state(tune, reg)

    # 键存在性开关（ValueName 为空）：开=键存在
    if not reg.get("value_name"):
        return None

    val, typ = _read_raw(reg["key_path"], reg["value_name"])

    # 按位掩码：值是否存在 == 这一位是否置位
    bitmask = reg.get("bitmask")
    byte_index = reg.get("binary_byte_index")
    if bitmask is not None and byte_index is not None:
        if not isinstance(val, bytes) or len(val) <= byte_index:
            return False
        return (val[byte_index] & int(bitmask)) == int(bitmask)

    enabled = reg.get("enabled") or []
    disabled = reg.get("disabled") or []

    def matches(candidates):
        for c in candidates:
            if c is None:
                if val is None:
                    return True
            elif val is not None and _values_equal(val, c):
                return True
        return False

    if matches(enabled):
        return True
    if matches(disabled):
        return False

    # 值不存在：按默认值推断（对齐 C# 的 valueExists 分支）
    if val is None:
        default = reg.get("default")
        enabled_vals = [c for c in enabled if c is not None]
        if default is not None and enabled_vals:
            return any(_values_equal(default, c) for c in enabled_vals)
        # 显式 None 哨兵表示"键缺失 = 开"
        if None in enabled:
            return True
        return False

    # 值存在但既不是开也不是关（例如辅助功能的多位标志组合）：按"非开即关"，
    # 与上游一致，避免界面留下永远不动的开关。
    return False


def _read_selection_state(tune: dict, reg: dict):
    """读一个 selection 的当前选中项，返回选项序号或 None。

    对齐 ``ComboBoxResolver.ResolveRawValuesToIndex``：
      * 逐个选项比对**全部**映射键（原来只比第一个键就 return，多键项会误判）
      * 值缺失时用该项的 ``default`` 兜底参与比对，而不是直接放弃
      * 全都匹配不上时退回 ``is_default`` 选项，界面不会留下空白下拉
    """
    options = tune.get("options") or []

    current = {}
    for r in tune.get("reg") or []:
        name = r.get("value_name")
        if not name or name in current:
            continue
        val, _typ = _read_raw(r["key_path"], name)
        current[name] = val if val is not None else r.get("default")

    for i, o in enumerate(options):
        mappings = o.get("value_mappings") or {}
        if not mappings:
            continue
        if all(_values_equal(current.get(k), v) for k, v in mappings.items()):
            return i

    # 全部注册表值都不存在 = 系统原始默认状态
    for i, o in enumerate(options):
        if o.get("is_default"):
            return i
    return None


def read_states() -> dict:
    """批量读 116 条的当前真实状态。

    返回 ``{id: {state, label}}``：toggle 的 state 是 bool（可能 None=无法判定），
    selection 的 state 是选项序号（可能 None）。计划任务按定义文件里的
    ``<Enabled>`` 读，PowerShell 类（DNS / 系统还原）读不到，state 为 None。
    任何异常都不抛，缺失即 None。
    """
    out = {}
    for t in tunes.TUNES:
        reg = _primary_reg(t)
        entry = {"state": None, "label": None}
        try:
            if t["input_type"] == "toggle":
                if reg is not None:
                    st = _read_toggle_state(t, reg)
                else:
                    st = _read_scheduled_state(t)
                entry["state"] = st
                entry["label"] = None if st is None else ("开" if st else "关")
            elif t["input_type"] == "selection" and reg is not None:
                idx = _read_selection_state(t, reg)
                entry["state"] = idx
                if idx is not None:
                    try:
                        entry["label"] = t["options"][idx]["display"]
                    except (IndexError, TypeError):
                        entry["label"] = None
        except Exception:                                     # noqa: BLE001
            pass
        out[t["id"]] = entry
    return out


def _read_scheduled_state(tune: dict):
    """纯计划任务类 toggle：任一条任务被禁用即视为"已优化"。

    这是这批设置唯一的可观测状态（它们没有注册表项）。
    """
    tasks = tune.get("scheduled") or []
    if not tasks:
        return None
    vals = []
    for task in tasks:
        en = _read_task_enabled(task.get("task_path") or "")
        if en is not None:
            vals.append(en)
    if not vals:
        return None
    return not all(vals)


def _apply_toggle(tune: dict, enable: bool) -> tuple[bool, str]:
    if tune["detection_type"] == "systemrestore":
        ok = _run_powershell(SYSTEMRESTORE_ENABLE if enable
                             else SYSTEMRESTORE_DISABLE)
        return ok, ("已启用系统还原点" if enable else "已禁用系统还原点"
                    if ok else "系统还原设置失败（可能需要管理员权限）")

    _snapshot(tune)
    ok = True
    for reg in tune.get("reg") or []:
        ok = _apply_reg(reg, enable) and ok
    ok = _apply_scheduled(tune, enable) and ok
    state = "开" if enable else "关"
    return ok, (f"「{tune['name_cn']}」已设为{state}"
                if ok else f"「{tune['name_cn']}」写入失败（部分项可能需要管理员权限）")


def _apply_selection(tune: dict, index: int) -> tuple[bool, str]:
    if tune["detection_type"] == "dnsserver":
        try:
            opt = tune["options"][index]
        except (IndexError, TypeError):
            return False, "选项序号无效"
        ok = _apply_dns(opt)
        return ok, (f"「{tune['name_cn']}」已应用「{opt['display']}」"
                    if ok else "DNS 设置失败（需要管理员权限）")

    try:
        opt = tune["options"][index]
    except (IndexError, TypeError):
        return False, "选项序号无效"

    value_mappings = opt.get("value_mappings") or {}
    if value_mappings:
        _snapshot(tune)
        ok = True
        for reg in tune.get("reg") or []:
            name = reg.get("value_name")
            if not name or name not in value_mappings:
                continue
            ok = _apply_reg(reg, True, specific_value=value_mappings[name]) and ok
        return ok, (f"「{tune['name_cn']}」已设为「{opt['display']}」"
                    if ok else f"「{tune['name_cn']}」写入失败")

    # 有脚本正文但生成器没带出来（非 DNS 的脚本选项）：目前无法执行
    if opt.get("script") is not None:
        return False, "该选项需要脚本执行，当前版本暂不支持"

    return False, "该设置没有可写入的值"


def _apply_by_state(tune: dict, use_default: bool) -> tuple[bool, str]:
    """推荐值/默认值共用：toggle 用 recommended/default 布尔，selection 找标志位。"""
    if tune["detection_type"] == "systemrestore":
        # recommended=True / default=True，二者等价
        return _apply_toggle(tune, True)

    if tune["input_type"] == "toggle":
        state = tune["default"] if use_default else tune["recommended"]
        if state is None:
            return False, "该设置没有可用的推荐/默认状态"
        return _apply_toggle(tune, bool(state))

    # selection：找 is_recommended / is_default 的选项
    key = "is_default" if use_default else "is_recommended"
    for i, o in enumerate(tune.get("options") or []):
        if o.get(key):
            return _apply_selection(tune, i)
    return False, "该设置没有可用的推荐/默认选项"


def apply_tune(tune_id: str, value) -> tuple[bool, str]:
    """统一入口。toggle 传 bool；selection 传选项序号 int。"""
    tune = _find(tune_id)
    if tune is None:
        return False, f"未知设置：{tune_id}"
    if tune["input_type"] == "toggle":
        return _apply_toggle(tune, bool(value))
    try:
        idx = int(value)
    except (TypeError, ValueError):
        return False, "选项序号无效"
    return _apply_selection(tune, idx)


def apply_recommended(tune_id: str) -> tuple[bool, str]:
    tune = _find(tune_id)
    if tune is None:
        return False, f"未知设置：{tune_id}"
    return _apply_by_state(tune, use_default=False)


def apply_default(tune_id: str) -> tuple[bool, str]:
    tune = _find(tune_id)
    if tune is None:
        return False, f"未知设置：{tune_id}"
    return _apply_by_state(tune, use_default=True)
