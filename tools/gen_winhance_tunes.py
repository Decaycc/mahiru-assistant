#!/usr/bin/env python3
"""Deterministic, offline generator for ``app/core/tunes_winhance.py``.

Parses the Winhance C# ``GamingAndPerformanceOptimizations.cs`` and the Chinese
localization ``zh-Hans.json``, then emits a pure-data Python module (a single list
``TUNES``) for the mahiru-assistant Windows cleanup/optimization app.

Run from the repo root with the project venv:

    D:\\Envs\\mahiru-assistant\\Scripts\\python.exe tools\\gen_winhance_tunes.py

The output is byte-for-byte deterministic and idempotent for identical inputs and
requires no network access.  Uses only the standard library (regex/text parsing;
no Roslyn, no third-party packages).
"""

import ast
import importlib.util
import json
import os
import re
import sys
from collections import Counter

# ---------------------------------------------------------------------------
# Input / output paths
# ---------------------------------------------------------------------------

CS_PATH = (
    r"C:\Users\陈耿峰\Documents\deepseek-harness\default-workspace\winhance-repo"
    r"\Winhance-main\src\Winhance.Core\Features\Optimize\Models"
    r"\GamingAndPerformanceOptimizations.cs"
)
JSON_PATH = (
    r"C:\Users\陈耿峰\Documents\deepseek-harness\default-workspace\winhance-repo"
    r"\Winhance-main\src\Winhance.UI\Features\Common\Localization\zh-Hans.json"
)
OUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "core", "tunes_winhance.py",
)

# ---------------------------------------------------------------------------
# C# string / value scanning (string- and comment-aware)
# ---------------------------------------------------------------------------

_WS = " \t\r\n"


def skip_ws(text, pos):
    while pos < len(text) and text[pos] in _WS:
        pos += 1
    return pos


def parse_verbatim(text, pos):
    """Parse a C# verbatim string ``@"..."`` starting at pos (pos points at ``@``).
    Returns ``(value, end_pos)``.  ``""`` inside a verbatim string is an escaped quote.
    """
    assert text.startswith('@"', pos)
    i = pos + 2
    out = []
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            if i + 1 < n and text[i + 1] == '"':
                out.append('"')
                i += 2
                continue
            return "".join(out), i + 1
        out.append(c)
        i += 1
    return "".join(out), n


def parse_regular(text, pos):
    """Parse a C# regular string ``"..."`` starting at pos (pos points at ``"``).
    Returns ``(value, end_pos)``.
    """
    assert text[pos] == '"'
    i = pos + 1
    out = []
    n = len(text)
    simple = {
        '"': '"', "\\": "\\", "n": "\n", "t": "\t",
        "r": "\r", "0": "\0", "'": "'",
    }
    while i < n:
        c = text[i]
        if c == "\\":
            if i + 1 < n:
                nxt = text[i + 1]
                out.append(simple.get(nxt, nxt))
                i += 2
                continue
            out.append("\\")
            i += 1
            continue
        if c == '"':
            return "".join(out), i + 1
        out.append(c)
        i += 1
    return "".join(out), n


def parse_string_at(text, pos):
    """Parse a string literal at/after pos (whitespace skipped). Returns (value, end)."""
    pos = skip_ws(text, pos)
    if pos >= len(text):
        return None, pos
    if text.startswith('@"', pos):
        return parse_verbatim(text, pos)
    if text[pos] == '"':
        return parse_regular(text, pos)
    return None, pos


def parse_value_at(text, pos):
    """Parse a C# scalar value (null / bool / int / hex / string) at/after pos."""
    pos = skip_ws(text, pos)
    if pos >= len(text):
        return None, pos
    if text.startswith("null", pos):
        return None, pos + 4
    if text.startswith("true", pos):
        return True, pos + 4
    if text.startswith("false", pos):
        return False, pos + 5
    if text.startswith('@"', pos):
        return parse_verbatim(text, pos)
    if text[pos] == '"':
        return parse_regular(text, pos)
    m = re.match(r"[-+]?0[xX][0-9a-fA-F]+|[-+]?\d+", text[pos:])
    if m:
        tok = m.group(0)
        if tok.lower().startswith("0x"):
            return int(tok, 16), pos + len(tok)
        return int(tok, 10), pos + len(tok)
    return None, pos


def split_top_level(s, sep=","):
    """Split s on sep, ignoring separators inside string literals."""
    parts = []
    i = 0
    n = len(s)
    cur = []
    while i < n:
        c = s[i]
        if s.startswith('@"', i):
            _, end = parse_verbatim(s, i)
            cur.append(s[i:end])
            i = end
            continue
        if c == '"':
            _, end = parse_regular(s, i)
            cur.append(s[i:end])
            i = end
            continue
        if c == sep:
            parts.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    parts.append("".join(cur))
    return parts


def find_matching_brace(text, open_pos):
    """open_pos points at ``{``.  Return the index of its matching ``}`` (or -1).
    String literals and //, /* */ comments are skipped so braces inside them don't count.
    """
    depth = 0
    i = open_pos
    n = len(text)
    while i < n:
        c = text[i]
        if text.startswith('@"', i):
            _, i = parse_verbatim(text, i)
            continue
        if c == '"':
            _, i = parse_regular(text, i)
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def block_after(text, match_end):
    """Return the balanced ``{...}`` content following match_end (whitespace skipped),
    as a tuple (inner_text, end_pos).  Returns (None, match_end) if no brace.
    """
    pos = skip_ws(text, match_end)
    if pos >= len(text) or text[pos] != "{":
        return None, match_end
    end = find_matching_brace(text, pos)
    if end == -1:
        return None, match_end
    return text[pos + 1:end], end + 1


# ---------------------------------------------------------------------------
# Field extractors
# ---------------------------------------------------------------------------

def extract_string_field(content, name):
    m = re.search(r"\b" + re.escape(name) + r"\s*=\s*", content)
    if not m:
        return None
    value, _ = parse_string_at(content, m.end())
    return value


def extract_bool_field(content, name):
    m = re.search(r"\b" + re.escape(name) + r"\s*=\s*(true|false)\b", content)
    if not m:
        return None
    return m.group(1) == "true"


def extract_int_field(content, name):
    m = re.search(r"\b" + re.escape(name) + r"\s*=\s*(0[xX][0-9a-fA-F]+|-?\d+)\b", content)
    if not m:
        return None
    tok = m.group(1)
    return int(tok, 16) if tok.lower().startswith("0x") else int(tok, 10)


def extract_input_type(content):
    m = re.search(r"\bInputType\s*=\s*InputType\.(\w+)", content)
    return m.group(1).lower() if m else None


def extract_detection_type(content):
    m = re.search(r"\bDetectionType\s*=\s*DetectionType\.(\w+)", content)
    return m.group(1).lower() if m else None


def extract_array_field(content, name):
    m = re.search(r"\b" + re.escape(name) + r"\s*=\s*\[", content)
    if not m:
        return None
    close = content.find("]", m.end())
    if close == -1:
        close = len(content)
    inner = content[m.end():close]
    values = []
    for part in split_top_level(inner, ","):
        part = part.strip()
        if part == "":
            continue
        value, _ = parse_value_at(part, 0)
        values.append(value)
    return values


# ---------------------------------------------------------------------------
# Nested structure extraction
# ---------------------------------------------------------------------------

def split_child_blocks(text, marker):
    """Find every ``new <marker> { ... }`` balanced block; return inner-texts."""
    blocks = []
    for m in re.finditer(r"new\s+" + re.escape(marker) + r"\b", text):
        inner, _ = block_after(text, m.end())
        if inner is not None:
            blocks.append(inner)
    return blocks


_VALUE_TYPE_MAP = {"DWord": "dword", "String": "string", "Binary": "binary"}


def extract_registry_settings(content):
    m = re.search(r"RegistrySettings\s*=\s*new\s+List<RegistrySetting>", content)
    if not m:
        return []
    list_inner, _ = block_after(content, m.end())
    if list_inner is None:
        return []
    regs = []
    for rb in split_child_blocks(list_inner, "RegistrySetting"):
        reg = {
            "key_path": extract_string_field(rb, "KeyPath"),
            "value_name": None,
            "recommended": None,
            "default": None,
            "enabled": None,
            "disabled": None,
            "value_type": "dword",
            "is_primary": False,
            "bitmask": None,
            "binary_byte_index": None,
            "modify_byte_only": False,
            "per_interface": False,
            "per_monitor": False,
            "group_policy": False,
        }
        vn = re.search(r"\bValueName\s*=\s*", rb)
        if vn:
            val, _ = parse_value_at(rb, vn.end())
            reg["value_name"] = val
        rv = re.search(r"\bRecommendedValue\s*=\s*", rb)
        if rv:
            reg["recommended"], _ = parse_value_at(rb, rv.end())
        dv = re.search(r"\bDefaultValue\s*=\s*", rb)
        if dv:
            reg["default"], _ = parse_value_at(rb, dv.end())
        reg["enabled"] = extract_array_field(rb, "EnabledValue")
        reg["disabled"] = extract_array_field(rb, "DisabledValue")
        vt = re.search(r"\bValueType\s*=\s*RegistryValueKind\.(\w+)", rb)
        if vt:
            reg["value_type"] = _VALUE_TYPE_MAP.get(vt.group(1), "dword")
        reg["is_primary"] = extract_bool_field(rb, "IsPrimary") is True
        reg["bitmask"] = extract_int_field(rb, "BitMask")
        reg["binary_byte_index"] = extract_int_field(rb, "BinaryByteIndex")
        reg["modify_byte_only"] = extract_bool_field(rb, "ModifyByteOnly") is True
        reg["per_interface"] = extract_bool_field(rb, "ApplyPerNetworkInterface") is True
        reg["per_monitor"] = extract_bool_field(rb, "ApplyPerMonitor") is True
        reg["group_policy"] = extract_bool_field(rb, "IsGroupPolicy") is True
        regs.append(reg)
    return regs


def extract_dict_entries(block, field_name, dict_kind):
    """Extract ``field_name = new Dictionary<..., dict_kind> { ["k"] = v, ... }``."""
    m = re.search(
        r"\b" + re.escape(field_name) + r"\s*=\s*new\s+Dictionary<[^>]+>\s*",
        block,
    )
    if not m:
        return None
    inner, _ = block_after(block, m.end())
    if inner is None:
        return None
    result = {}
    for em in re.finditer(r'\[\s*"([^"]*)"\s*\]\s*=\s*', inner):
        key = em.group(1)
        value, _ = parse_value_at(inner, em.end())
        result[key] = value
    return result


_SCRIPT_MAP = {"None": None, "Enabled": "enabled", "Disabled": "disabled"}


def extract_combo_options(content):
    m = re.search(r"ComboBox\s*=\s*new\s+ComboBoxMetadata\b", content)
    if not m:
        return []
    combo_inner, _ = block_after(content, m.end())
    if combo_inner is None:
        return []
    om = re.search(r"\bOptions\s*=\s*new(\[\])?\s*", combo_inner)
    if not om:
        return []
    options_inner, _ = block_after(combo_inner, om.end())
    if options_inner is None:
        return []
    opts = []
    for ob in split_child_blocks(options_inner, "ComboBoxOption"):
        option = {
            "display": extract_string_field(ob, "DisplayName"),
            "simple_value": None,
            "command_value": None,
            "value_mappings": None,
            "script": None,
            "script_vars": None,
            "is_default": False,
            "is_recommended": False,
            "warning": None,
        }
        option["simple_value"] = extract_int_field(ob, "SimpleValue")
        option["command_value"] = extract_bool_field(ob, "CommandValue")
        option["value_mappings"] = extract_dict_entries(ob, "ValueMappings", "object?")
        sc = re.search(r"\bScript\s*=\s*ScriptOption\.(\w+)", ob)
        if sc:
            option["script"] = _SCRIPT_MAP.get(sc.group(1), None)
        option["script_vars"] = extract_dict_entries(ob, "ScriptVariables", "string")
        option["is_default"] = extract_bool_field(ob, "IsDefault") is True
        option["is_recommended"] = extract_bool_field(ob, "IsRecommended") is True
        option["warning"] = extract_string_field(ob, "Warning")
        opts.append(option)
    return opts


def extract_scheduled(content):
    m = re.search(r"ScheduledTaskSettings\s*=\s*new\s+List<ScheduledTaskSetting>", content)
    if not m:
        return []
    list_inner, _ = block_after(content, m.end())
    if list_inner is None:
        return []
    tasks = []
    for tb in split_child_blocks(list_inner, "ScheduledTaskSetting"):
        tasks.append({
            "id": extract_string_field(tb, "Id"),
            "task_path": extract_string_field(tb, "TaskPath"),
            "recommended": extract_bool_field(tb, "RecommendedState"),
            "default": extract_bool_field(tb, "DefaultState"),
        })
    return tasks


# ---------------------------------------------------------------------------
# Setting block splitting
# ---------------------------------------------------------------------------

def split_setting_blocks(text):
    blocks = []
    for m in re.finditer(r"new\s+SettingDefinition\b", text):
        inner, _ = block_after(text, m.end())
        if inner is not None:
            blocks.append((inner, m.start()))
    return blocks


def parse_setting_block(content, line_no):
    issues = []
    sid = extract_string_field(content, "Id")
    if not sid:
        issues.append("line %d: missing or empty Id" % line_no)
        sid = ""
    raw = {
        "_line": line_no,
        "id": sid,
        "name": extract_string_field(content, "Name") or "",
        "desc": extract_string_field(content, "Description") or "",
        "group": extract_string_field(content, "GroupName"),
        "input_type": extract_input_type(content) or "toggle",
        "requires_restart": extract_bool_field(content, "RequiresRestart") is True,
        "subjective": extract_bool_field(content, "IsSubjectivePreference") is True,
        "requires_confirmation": extract_bool_field(content, "RequiresConfirmation") is True,
        "recommended_toggle_state": extract_bool_field(content, "RecommendedToggleState"),
        "default_toggle_state": extract_bool_field(content, "DefaultToggleState"),
        "reg": extract_registry_settings(content),
        "options": extract_combo_options(content),
        "scheduled": extract_scheduled(content),
        "detection_type": extract_detection_type(content),
    }
    return raw, issues


# ---------------------------------------------------------------------------
# Localization + recommended/default resolution (mirrors SettingDefinitionToggleState.cs)
# ---------------------------------------------------------------------------

_LOC_KEY_PREFIXES = ("Template_", "Setting_", "PowerPlan_", "ServiceOption_")


def is_localization_key(value):
    return bool(value) and value.startswith(_LOC_KEY_PREFIXES)


def resolve_group_cn(group_name, loc):
    if not group_name:
        return None
    compact = "SettingGroup_" + group_name.replace(" ", "").replace("&", "")
    if compact in loc:
        return loc[compact]
    snake = group_name.replace(" & ", "_").replace(" ", "_").replace("&", "_")
    while "__" in snake:
        snake = snake.replace("__", "_")
    key = "SettingGroup_" + snake
    if key in loc:
        return loc[key]
    return None


def resolve_option_display(display_name, setting_id, index, loc):
    if display_name is None:
        return None
    if is_localization_key(display_name):
        return loc.get(display_name) or display_name
    key = "Setting_%s_Option_%d" % (setting_id, index)
    return loc.get(key) or display_name


def resolve_option_warning(english_warning, setting_id, index, loc):
    if not english_warning:
        return None
    key = "Setting_%s_OptionWarning_%d" % (setting_id, index)
    return loc.get(key) or english_warning


def values_equal(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if a == b:
        return True
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return str(a).lower() == str(b).lower()


def array_contains(array, target):
    if not array:
        return False
    return any(values_equal(v, target) for v in array)


def array_contains_null(array):
    return bool(array) and any(v is None for v in array)


def toggle_target_state(target, enabled, disabled):
    if target is None:
        if array_contains_null(enabled):
            return True
        if array_contains_null(disabled):
            return False
        return None
    if array_contains(enabled, target):
        return True
    if array_contains(disabled, target):
        return False
    return None


def is_key_existence_toggle(reg):
    return (
        reg["value_name"] is None
        and reg["enabled"] is None
        and reg["disabled"] is None
    )


def resolve_toggle_state_internal(reg, target, derive_from_key_absent):
    if target is None and not derive_from_key_absent:
        return None
    if target is None and derive_from_key_absent and is_key_existence_toggle(reg):
        return True
    return toggle_target_state(target, reg["enabled"], reg["disabled"])


def primary_reg(regs):
    for r in regs:
        if r["is_primary"]:
            return r
    return regs[0] if regs else None


def resolve_recommended(raw):
    if raw["recommended_toggle_state"] is not None:
        return raw["recommended_toggle_state"]
    reg = primary_reg(raw["reg"])
    if reg is not None:
        state = resolve_toggle_state_internal(reg, reg["recommended"], False)
        if state is not None:
            return state
    for ts in raw["scheduled"]:
        if ts["recommended"] is not None:
            return ts["recommended"]
    return None


def resolve_default(raw):
    if raw["default_toggle_state"] is not None:
        return raw["default_toggle_state"]
    reg = primary_reg(raw["reg"])
    if reg is not None:
        state = resolve_toggle_state_internal(reg, reg["default"], True)
        if state is not None:
            return state
    for ts in raw["scheduled"]:
        if ts["default"] is not None:
            return ts["default"]
    return None


# ---------------------------------------------------------------------------
# Python literal emitter (deterministic, ASCII-safe, real Unicode, no BOM)
# ---------------------------------------------------------------------------

def py_literal(value, indent):
    pad = " " * indent
    if value is None:
        return "None"
    if value is True:
        return "True"
    if value is False:
        return "False"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        child = indent + 4
        parts = [" " * child + py_literal(v, child) for v in value]
        return "[\n" + ",\n".join(parts) + ",\n" + pad + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        child = indent + 4
        parts = [
            " " * child + repr(k) + ": " + py_literal(v, child)
            for k, v in value.items()
        ]
        return "{\n" + ",\n".join(parts) + ",\n" + pad + "}"
    raise TypeError("unsupported literal type: %r" % (value,))


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build_tunes(raw_settings, issues, loc):
    tunes = []
    for raw in raw_settings:
        sid = raw["id"]
        reg = []
        for r in raw["reg"]:
            reg.append({
                "key_path": r["key_path"],
                "value_name": r["value_name"],
                "recommended": r["recommended"],
                "default": r["default"],
                "enabled": r["enabled"],
                "disabled": r["disabled"],
                "value_type": r["value_type"],
                "is_primary": r["is_primary"],
                "bitmask": r["bitmask"],
                "binary_byte_index": r["binary_byte_index"],
                "modify_byte_only": r["modify_byte_only"],
                "per_interface": r["per_interface"],
                "per_monitor": r["per_monitor"],
                "group_policy": r["group_policy"],
            })

        options = []
        for i, o in enumerate(raw["options"]):
            options.append({
                "display": resolve_option_display(o["display"], sid, i, loc),
                "simple_value": o["simple_value"],
                "command_value": o["command_value"],
                "value_mappings": o["value_mappings"],
                "script": o["script"],
                "script_vars": o["script_vars"],
                "is_default": o["is_default"],
                "is_recommended": o["is_recommended"],
                "warning": resolve_option_warning(o["warning"], sid, i, loc),
            })

        scheduled = [dict(s) for s in raw["scheduled"]]

        group = raw["group"]
        tune = {
            "id": sid,
            "name_cn": loc.get("Setting_%s_Name" % sid) or raw["name"],
            "desc_cn": loc.get("Setting_%s_Description" % sid) or raw["desc"],
            "group": group,
            "group_cn": resolve_group_cn(group, loc),
            "input_type": raw["input_type"],
            "requires_restart": raw["requires_restart"],
            "subjective": raw["subjective"],
            "requires_confirmation": raw["requires_confirmation"],
            "recommended": resolve_recommended(raw),
            "default": resolve_default(raw),
            "reg": reg,
            "options": options,
            "scheduled": scheduled,
            "detection_type": raw["detection_type"],
        }
        tunes.append(tune)

    tunes.sort(key=lambda t: t["id"])
    return tunes


_DOCSTRING = (
    '"""Winhance gaming & performance tunes -- GENERATED DATA. DO NOT HAND-EDIT.\n'
    "\n"
    "Regenerate with:\n"
    "    python tools/gen_winhance_tunes.py\n"
    "\n"
    "This module is a static data snapshot derived from the Winhance project,\n"
    "Copyright 2025 Marco du Plessis, licensed under PolyForm Shield 1.0.0 -- a\n"
    "source-available license that includes a non-compete clause.  Review that\n"
    "license before redistributing or reusing this data.\n"
    "\n"
    "The registry writes encoded here apply verbatim from the Winhance source.\n"
    "This module is data only: it performs no I/O of its own.\n"
    '"""'
)


def build_module_text(tunes, issues):
    chunks = [_DOCSTRING, "", "", "TUNES = " + py_literal(tunes, 0), ""]
    if issues:
        chunks.append("")
        chunks.append("## PARSE ISSUES")
        for issue in issues:
            chunks.append("# " + issue)
        chunks.append("")
    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# Verification + summary
# ---------------------------------------------------------------------------

def verify_module(out_path):
    with open(out_path, "r", encoding="utf-8") as fh:
        source = fh.read()
    ast.parse(source)
    spec = importlib.util.spec_from_file_location("tunes_winhance", out_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TUNES


def main():
    if not os.path.exists(CS_PATH):
        print("ERROR: C# source not found: %s" % CS_PATH, file=sys.stderr)
        return 1
    if not os.path.exists(JSON_PATH):
        print("ERROR: localization JSON not found: %s" % JSON_PATH, file=sys.stderr)
        return 1

    with open(CS_PATH, "r", encoding="utf-8") as fh:
        cs_text = fh.read()
    with open(JSON_PATH, "r", encoding="utf-8-sig") as fh:
        loc = json.load(fh)

    blocks = split_setting_blocks(cs_text)
    raw_settings = []
    issues = []
    for content, start in blocks:
        line_no = cs_text.count("\n", 0, start) + 1
        raw, block_issues = parse_setting_block(content, line_no)
        raw_settings.append(raw)
        issues.extend(block_issues)

    tunes = build_tunes(raw_settings, issues, loc)

    # Determinism / sanity: ensure unique ids.
    ids = [t["id"] for t in tunes]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        issues.append("duplicate setting ids: %s" % ", ".join(dupes))

    module_text = build_module_text(tunes, issues)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(module_text)

    verified_tunes = verify_module(OUT_PATH)
    if len(verified_tunes) != len(tunes):
        print("ERROR: verified TUNES length mismatch", file=sys.stderr)
        return 1

    by_type = Counter(t["input_type"] for t in tunes)
    restart_count = sum(1 for t in tunes if t["requires_restart"])
    option_count = sum(len(t["options"]) for t in tunes)
    reg_count = sum(len(t["reg"]) for t in tunes)
    out_bytes = os.path.getsize(OUT_PATH)

    print("Winhance tunes generated: %s" % OUT_PATH)
    print("  settings:            %d" % len(tunes))
    print("  input types:         %s" % dict(sorted(by_type.items())))
    print("  requires_restart:    %d" % restart_count)
    print("  selection options:   %d" % option_count)
    print("  registry settings:   %d" % reg_count)
    print("  parse issues:        %d" % len(issues))
    print("  output bytes:        %d" % out_bytes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
