# -*- coding: utf-8 -*-
"""第三方清理规则的下载与生成。

**这个模块是手写的**（不属于切分器生成的 app/core/mem.py / junk.py）。
命令行工具 tools/update_rules.py 与软件里的「更新规则」按钮都调它，
保证只有一份实现。

数据源（均为开源、活跃维护）：
    Winapp2.ini    github.com/MoscaDotTo/Winapp2                CC-BY-SA-4.0
    Winapp3.ini    github.com/MoscaDotTo/Winapp2 (Winapp3/)     CC-BY-SA-4.0
    BleachBit      github.com/bleachbit/bleachbit               GPL-3.0-or-later

    ⚠ Winapp3.ini 的许可里额外写了一句「若要修改 / 分发 / 托管，请先联系作者」。
      纯自用没问题；要公开发布本工具的话请先跟对方打招呼，
      或者用 include_winapp3=False 生成不含它的规则。

## 联网方式（踩过坑）

GitHub 未认证 API 限额 60 次/小时。BleachBit 有 100 多个 cleaner，
逐个请求会在下到一半时被限流（实测只拿到 42 个）。所以：
  · Winapp2 / Winapp3  → blob 接口逐个取（文件少，2 次请求）
  · BleachBit          → **tarball 接口一次拿整个仓库**（1 次请求，再本地解包）
另外 raw.githubusercontent.com 在部分网络下解析不了、codeload 会超时，
所以统一走 api.github.com。下载内容缓存在 config/rule_cache/ 下。
"""
import io
import json
import os
import re
import sys
import tarfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter

# 允许「直接运行本模块」与「作为包导入」两种方式
try:
    from app.paths import config_dir as _config_dir
except ImportError:                                         # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    from app.paths import config_dir as _config_dir

UA = {"User-Agent": "mahiru-assistant-rule-updater",
      "Accept": "application/vnd.github.raw"}

SOURCES = {
    "winapp2": {
        "repo": "MoscaDotTo/Winapp2",
        "path": "Non-CCleaner/CCleaner7/Winapp2.ini",
        "license": "CC-BY-SA-4.0",
        "url": "https://github.com/MoscaDotTo/Winapp2",
    },
    "winapp3": {
        "repo": "MoscaDotTo/Winapp2",
        "path": "Winapp3/Winapp3.ini",
        "license": "CC-BY-SA-4.0（额外要求：分发前先联系作者）",
        "url": "https://github.com/MoscaDotTo/Winapp2/tree/master/Winapp3",
    },
}

CACHE_DIRNAME = "rule_cache"

# 生成结果的合理性下限。
# 正常情况（Winapp2 + Winapp3 + BleachBit）至少几千条安全规则。
# 低于这个数说明上游**全部没拿到**（断网、限流、仓库改名…）。
#
# 为什么要有这道闸：踩过一次 —— 离线模式没找到缓存，工具照样写文件，
# 把 288 KB 的可用规则覆盖成了 1 KB 的空列表。**失败的更新绝不能
# 覆盖可用的规则。**
MIN_SAFE_DIRS = 500

# ----------------------------------------------------------------- 过滤规则
VARS = {
    "%localappdata%": "LOCAL", "%appdata%": "ROAMING",
    "%userprofile%": "PROFILE", "%windir%": "WINDIR",
    "%systemroot%": "WINDIR", "%programdata%": "PROGRAMDATA",
    "%commonappdata%": "PROGRAMDATA", "%temp%": "TEMP", "%tmp%": "TEMP",
    "%systemdrive%": "SYSTEMDRIVE", "%public%": "PUBLIC",
}
BAD_ROOTS = ("%localappdatalow%", "%allusersprofile%")

SAFE_RE = re.compile(
    r"^("
    r"cache[\w ]*|[\w ]*cache|[\w ]*caches|"
    r"log|logs|[\w ]*logs|"
    r"temp|tmp|tempstate|tempcache|temporary[\w ]*|"
    r"dump|dumps|crash|crashpad|crashlogs|crashdumps|crash reports|"
    r"thumbnails|thumbnail cache|"
    r"gpucache|gpu cache|code cache|media cache|shader cache|shadercache|"
    r"grshadercache|dawn[\w]*cache|graphite[\w]*cache|dxcache|vkcache|glcache|"
    r"cachestorage|blob_storage|gcm store|"
    r"setupmetrics|videodecodestats|meipreload|budgetdatabase|"
    r"download service|downloadservice|"
    r"jumplisticons[\w]*|optimization[\w]*|"
    r"firstpartysetspreloaded|privacysandbox[\w]*|"
    r"probabilisticrevealtokenregistry|trusttokenkeycommitments|"
    r"component_crx_cache|extensions_crx_cache|webappcache|webservicecache"
    r")$", re.I)

CAUTION_RE = re.compile(
    r"^(service worker|widevinecdm|mediafoundationcdmstore|"
    r"platform notifications)$", re.I)

DENY_SEGMENTS = {
    "ac", "file system", "webstorage", "local storage", "indexeddb",
    "databases", "session storage", "sessions", "cookies", "inetcookies",
    "history", "inethistory", "login data", "web data", "bookmarks",
    "favorites", "transportsecurity", "clientcertificates",
    "network persistent state", "safe browsing", "safe browsing network",
    "avatars", "preferences", "formhistory", "autofill", "credentials",
    "sessionstore", "recent", "userdata",
}
DENY_SUBSTR = ("cookie", "password", "passwd", "bookmark", "credential",
               "formhistory", "autofill", "logindata", "webdata")
ANTICHEAT = ("anticheat", "anti_cheat", "anti-cheat", "easyanticheat",
             "battleye", "beclient", "tenprotect", "tp3", "sguard",
             "vanguard", "ace-guard", "aceguard", "ace_guard")
SAFE_FILE_PATTERNS = {"log", "log.old", "debug.log", "*.log", "*.tmp",
                      "*.temp", "*.dmp", "*.old", "*-journal",
                      "*_shutdown_ms.txt", "*.old.log", "*.exe.tmp"}


class RateLimited(RuntimeError):
    """GitHub API 限额用完了。"""


def cache_dir() -> str:
    p = os.path.join(_config_dir(), CACHE_DIRNAME)
    os.makedirs(p, exist_ok=True)
    return p


# ----------------------------------------------------------------- 网络
def http_get(url: str, timeout: int = 300) -> bytes:
    headers = dict(UA)
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 403 and "rate limit" in str(e).lower():
            raise RateLimited(
                "GitHub API 速率限制已用完（未认证为 60 次/小时）。"
                "等一小时后再试，或设置环境变量 GITHUB_TOKEN 提高额度。") from e
        raise RuntimeError(f"HTTP {e.code}: {e.reason}") from e
    except Exception as e:                                  # noqa: BLE001
        raise RuntimeError(f"{type(e).__name__}: {e}") from e


def fetch_blob(repo: str, path: str, cache_name: str,
               offline: bool = False, log=None) -> tuple[bytes | None, str]:
    """取仓库里某个文件。优先用缓存；联网失败也退回缓存。"""
    cached = os.path.join(cache_dir(), cache_name)

    if offline:
        if os.path.exists(cached):
            with open(cached, "rb") as f:
                return f.read(), f"缓存 {os.path.getsize(cached) // 1024} KB"
        return None, "离线模式且无缓存"

    sha, err = None, ""
    try:
        tree = json.loads(http_get(
            f"https://api.github.com/repos/{repo}/git/trees/HEAD?recursive=1"))
        entry = next((e for e in tree.get("tree", [])
                      if e.get("path") == path), None)
        if entry is None:
            return None, f"仓库里找不到 {path}"
        sha = entry["sha"]
    except Exception as e:                                  # noqa: BLE001
        err = str(e)

    meta_path = cached + ".meta"
    if sha and os.path.exists(cached) and os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                if json.load(f).get("sha") == sha:
                    with open(cached, "rb") as f:
                        return f.read(), f"未变化 (sha {sha[:8]})"
        except Exception:                                   # noqa: BLE001
            pass

    # 拿不到 sha（限流/断网）时必须回退缓存 —— 缓存的全部意义就在这
    if sha is None:
        if os.path.exists(cached):
            with open(cached, "rb") as f:
                return f.read(), \
                    f"联网失败，用缓存（{os.path.getsize(cached) // 1024} KB）"
        return None, f"取 sha 失败且无缓存：{err}"

    try:
        data = http_get(f"https://api.github.com/repos/{repo}/git/blobs/{sha}")
    except Exception as e:                                  # noqa: BLE001
        if os.path.exists(cached):
            with open(cached, "rb") as f:
                return f.read(), f"下载失败，用缓存（{e}）"
        return None, f"下载失败：{e}"

    with open(cached, "wb") as f:
        f.write(data)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"sha": sha, "path": path, "repo": repo,
                   "time": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
    return data, f"已更新 {len(data) // 1024} KB (sha {sha[:8]})"


def fetch_bleachbit(offline: bool = False) -> tuple[list[tuple[str, bytes]], str]:
    """取 BleachBit 的所有 cleaner XML。

    用 tarball 接口一次拿整个仓库：100 多个文件逐个请求会撞上
    60 次/小时的限额（实测只下到 42 个），tarball 只算 1 次。
    """
    tar_path = os.path.join(cache_dir(), "bleachbit.tar.gz")

    if not offline:
        # 先看限额：还有额度才值得联网，否则直接走缓存，
        # 免得在 codeload 上白等几分钟（见 rate_limit 的说明）
        rl = rate_limit()
        if rl.get("ok") and (rl.get("remaining") or 0) <= 2:
            import datetime as _dt
            when = ""
            if rl.get("reset"):
                when = _dt.datetime.fromtimestamp(rl["reset"]).strftime("%H:%M")
            say(f"GitHub 接口额度已用完（{rl.get('remaining')}/"
                f"{rl.get('limit')}，{when} 重置）—— 改用本地缓存重建")
            say("缓存里没有的部分会跳过，等额度恢复后再更新即可")
            offline = True
        elif rl.get("ok"):
            say(f"接口额度 {rl.get('remaining')}/{rl.get('limit')}，开始联网获取")
        else:
            say(f"查限额失败（{rl.get('error')}），仍尝试联网")

    try:
        data = http_get(
            "https://api.github.com/repos/bleachbit/bleachbit"
            "/tarball/HEAD", timeout=120)
        with open(tar_path, "wb") as f:
            f.write(data)
    except Exception:                                       # noqa: BLE001
        pass                                                # 下面用缓存
    if not os.path.exists(tar_path):
        return [], "离线模式且无 tarball 缓存" if offline else "tarball 获取失败"

    try:
        out = []
        with tarfile.open(tar_path, "r:gz") as tf:
            for m in tf.getmembers():
                if not m.isfile():
                    continue
                parts = m.name.split("/")
                if len(parts) < 3 or parts[1] != "cleaners" \
                        or not parts[-1].endswith(".xml"):
                    continue
                fh = tf.extractfile(m)
                if fh is not None:
                    out.append((parts[-1], fh.read()))
        if not out:
            return [], "tarball 里没找到 cleaners/*.xml"
        return out, (f"{len(out)} 个 cleaner"
                     f"（tarball {os.path.getsize(tar_path) // 1024} KB）")
    except Exception as e:                                  # noqa: BLE001
        return [], f"tarball 解包失败：{e}"


# ----------------------------------------------------------------- 解析
def denied(tpl: str) -> bool:
    """全段判定：任何一段命中禁止名 / 隐私 / 反作弊都拒绝。"""
    for seg in (s for s in tpl.replace("/", "\\").lower().split("\\") if s):
        if seg in DENY_SEGMENTS:
            return True
        if any(b in seg for b in ANTICHEAT):
            return True
        if any(b in seg for b in DENY_SUBSTR):
            return True
    return False


def translate(raw: str) -> str | None:
    """把规则库里的绝对路径转成占位符模板。"""
    p = (raw or "").strip().strip('"')
    if not p or "%" not in p:
        return None
    low = p.lower()
    if any(low.startswith(b) for b in BAD_ROOTS):
        return None
    if "\\windows\\" in low or low.startswith("%windir%\\system32"):
        return None
    if any(x in low for x in ("documents and settings", "local settings",
                              "\\security\\logs", "system.sav", "$recycle.bin",
                              "system volume information",
                              "\\config\\systemprofile")):
        return None
    hit = None
    for var, name in VARS.items():
        if low.startswith(var):
            hit = (var, name)
            break
    if not hit:
        return None
    var, name = hit
    rest = p[len(var):].lstrip("\\/").replace("/", "\\").rstrip("\\")
    if not rest:
        return None
    tpl = "{%s}\\" % name + rest
    if tpl.count("*") > 2 or denied(tpl):
        return None
    return tpl


def parse_ini(text: str, counters: Counter, safe: dict, caution: dict,
              frules: dict) -> None:
    skip = False
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            skip = denied(line[1:-1])
            if skip:
                counters["隐私条目(跳过)"] += 1
            continue
        m = re.match(r"FileKey\d+=(.+)$", line, re.I)
        if not m or skip:
            continue
        counters["FileKey 总数"] += 1
        parts = m.group(1).split("|")
        tpl = translate(parts[0].strip())
        if not tpl:
            counters["路径不合格(丢弃)"] += 1
            continue
        files = parts[1].strip() if len(parts) > 1 else ""
        base = os.path.basename(tpl)

        if "*" in base:
            core = base.replace("*", "").replace("?", "").strip()
            if len(core) < 3 or not re.search(
                    r"cache|log|temp|dump|thumb|shader|crash|notif", core, re.I):
                counters["裸通配(拒绝)"] += 1
                continue
            safe[tpl] = 1
            counters["安全-通配目录"] += 1
        elif files == "*" or not files:
            if SAFE_RE.match(base):
                safe[tpl] = 1
                counters["安全-整目录"] += 1
            elif CAUTION_RE.match(base):
                caution[tpl] = 1
                counters["谨慎-整目录"] += 1
            else:
                counters["名字不像缓存(丢弃)"] += 1
        else:
            ok = [x.strip() for x in files.split(";")
                  if x.strip() and x.strip().lower() in SAFE_FILE_PATTERNS]
            if ok:
                frules.setdefault(tpl, set()).update(ok)
                counters["按模式清理"] += 1
            else:
                counters["模式不够安全(丢弃)"] += 1


def parse_bleachbit(name: str, data: bytes, counters: Counter,
                    safe: dict, caution: dict) -> None:
    try:
        root = ET.fromstring(data)
    except Exception:                                       # noqa: BLE001
        return
    o = (root.get("os") or "").lower()
    if o and "windows" not in o:
        return
    for act in root.iter("action"):
        if act.get("command") != "delete":
            continue
        tpl = translate(act.get("path") or "")
        if not tpl or "*" in os.path.basename(tpl):
            continue
        base = os.path.basename(tpl)
        if SAFE_RE.match(base):
            safe.setdefault(tpl, 1)
            counters["BleachBit-安全"] += 1
        elif CAUTION_RE.match(base):
            caution.setdefault(tpl, 1)
            counters["BleachBit-谨慎"] += 1


# ----------------------------------------------------------------- 主流程
def build_text(offline: bool = False, include_winapp3: bool = True,
               log=None) -> tuple[str, dict]:
    """下载并生成规则文件内容，返回 (文本, 统计)。不写文件。"""
    def say(msg):
        if log:
            log(msg)

    counters = Counter()
    provenance = {}
    safe, caution, frules = {}, {}, {}

    wanted = ["winapp2"] + ([] if not include_winapp3 else ["winapp3"])
    for key in wanted:
        src = SOURCES[key]
        # 每一步之前都先说一句：界面靠日志显示进度，不报的话
        # 用户看到的就是「点了没反应」
        say(f"正在获取 {key}…")
        data, note = fetch_blob(src["repo"], src["path"], key + ".ini",
                                offline, log)
        say(f"  {src['path']} —— {note}")
        if not data:
            continue
        text = data.decode("utf-8", errors="replace")
        m = re.search(r";\s*Version:\s*(\S+)", text)
        n = re.search(r"# of entries:\s*([\d,]+)", text)
        provenance[key] = {
            "url": src["url"], "path": src["path"], "license": src["license"],
            "version": m.group(1) if m else "?",
            "entries": n.group(1) if n else "?",
        }
        say(f"  版本 {provenance[key]['version']}"
            f" / 条目 {provenance[key]['entries']}")
        parse_ini(text, counters, safe, caution, frules)

    say("正在获取 BleachBit 规则（整个仓库打包下载，约 2.6 MB）…")
    files, note = fetch_bleachbit(offline)
    say(f"  {note}")
    if not files:
        say("  !! 没拿到 BleachBit 规则，本次只更新 Winapp2/Winapp3")
    for name, data in files:
        parse_bleachbit(name, data, counters, safe, caution)
    provenance["bleachbit"] = {
        "url": "https://github.com/bleachbit/bleachbit",
        "path": "cleaners/*.xml", "license": "GPL-3.0-or-later",
        "version": time.strftime("%Y-%m-%d"), "entries": str(len(files)),
    }

    sorted_safe = sorted(safe, key=lambda t: t.lower())
    sorted_caution = sorted(caution, key=lambda t: t.lower())
    sorted_files = sorted(frules.items(), key=lambda x: x[0].lower())

    lines = [
        '# -*- coding: utf-8 -*-',
        '"""第三方清理规则库衍生数据',
        '（由软件里的「更新规则」按钮或 tools/update_rules.py 自动生成，勿手改）',
        '',
        '来源与许可：',
    ]
    for k, v in provenance.items():
        lines.append(f"  * {k:<10} {v['url']}")
        lines.append(f"              版本 {v['version']} / {v['entries']} 条"
                     f" / {v['license']}")
    lines += [
        '',
        f'生成时间：{time.strftime("%Y-%m-%d %H:%M:%S")}',
        '',
        '已过滤（按路径段全段判定，任何一段命中即拒绝）：',
        '  Cookie / 历史 / 密码 / 书签 / 表单 / 会话 / IndexedDB / localStorage /',
        '  File System / WebStorage / 传输安全状态 / 客户端证书 / 反作弊目录 /',
        '  裸通配目录名',
        '',
        '三档：',
        '  THIRD_PARTY_SAFE_DIRS     纯缓存，删了自动重建',
        '  THIRD_PARTY_CAUTION_DIRS  可重建但有可见副作用（默认不勾选）',
        '  THIRD_PARTY_FILE_RULES    按文件名模式清理，不清空目录',
        '',
        '占位符：{LOCAL} {ROAMING} {PROFILE} {WINDIR} {PROGRAMDATA} {TEMP}',
        '        {SYSTEMDRIVE} {PUBLIC}',
        '',
        '规则是**模板**，在本机现场解析、只保留真实存在的目录 ——',
        '所以同一份规则换台电脑也能用：装了哪个软件就命中哪个。',
        '"""',
        '',
        'THIRD_PARTY_SAFE_DIRS = [',
    ]
    lines += [f"    {t!r}," for t in sorted_safe]
    lines += [']', '', 'THIRD_PARTY_CAUTION_DIRS = [']
    lines += [f"    {t!r}," for t in sorted_caution]
    lines += [']', '', 'THIRD_PARTY_FILE_RULES = [']
    lines += [f"    ({t!r}, {sorted(p)!r})," for t, p in sorted_files]
    lines += [']', '']

    stats = {
        "safe": len(sorted_safe),
        "caution": len(sorted_caution),
        "files": len(sorted_files),
        "provenance": provenance,
        "counters": dict(counters),
    }
    return "\n".join(lines), stats


def write_rules(text: str, path: str) -> None:
    """原子写入：先写临时文件再替换，避免写一半被打断留下坏文件。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def update(out_path: str, *, offline: bool = False,
           include_winapp3: bool = True, force: bool = False,
           log=None) -> dict:
    """完整流程：下载 → 生成 → 写入 out_path。返回统计。

    写入前有两道保险：
      1. 结果太少（< MIN_SAFE_DIRS）直接报错、**不写**，原有规则保持不变
      2. 写之前把原文件备份成 .bak
    """
    text, stats = build_text(offline=offline, include_winapp3=include_winapp3,
                             log=log)

    if stats["safe"] < MIN_SAFE_DIRS and not force:
        raise RuntimeError(
            f"生成结果只有 {stats['safe']} 条安全规则，远低于正常的 "
            f"{MIN_SAFE_DIRS}+ 条，说明上游没拿到（断网/限流/仓库改名）。"
            f"**已放弃写入，原有规则保持不变**。"
            f"确认要写入请加 force=True。")

    if os.path.exists(out_path):
        try:
            import shutil
            shutil.copyfile(out_path, out_path + ".bak")
        except Exception:                                   # noqa: BLE001
            pass

    write_rules(text, out_path)
    stats["path"] = out_path
    stats["size"] = os.path.getsize(out_path)
    return stats


def migrate_legacy_cache() -> int:
    """把旧版放在 tools/.rule_cache 的缓存搬到 config/rule_cache。

    缓存目录从 tools/ 挪到 config/ 是为了打包后也能用（tools/ 不进 EXE）。
    不搬的话老缓存等于白下，还得重新联网抓一遍。
    """
    import shutil
    legacy = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "tools", ".rule_cache")
    if not os.path.isdir(legacy):
        return 0
    dest = cache_dir()
    moved = 0
    for name in os.listdir(legacy):
        src = os.path.join(legacy, name)
        dst = os.path.join(dest, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            try:
                shutil.copyfile(src, dst)
                moved += 1
            except Exception:                               # noqa: BLE001
                pass
    return moved


def rate_limit() -> dict:
    """查一次 API 限额（1 次请求，很快）。

    为什么要先查这个：限额用完时，各条下载路径的**失败速度差很远** ——
    blob 接口立刻 403，而 tarball 会先 302 跳到 codeload，
    那边如果连不通就会一直挂到超时（实测能挂几分钟）。
    表现就是「点了按钮一直没反应」。所以开跑前先问一句，
    限额没了就明确告诉用户改走缓存，别去撞那几分钟的超时。
    """
    try:
        d = json.loads(http_get("https://api.github.com/rate_limit",
                                timeout=15))
        c = d.get("resources", {}).get("core", {})
        return {"ok": True, "remaining": c.get("remaining"),
                "limit": c.get("limit"), "reset": c.get("reset")}
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def check_available(log=None) -> dict:
    """只查上游版本，不下载整个文件（省请求次数）。"""
    out = {}
    for key, src in SOURCES.items():
        try:
            tree = json.loads(http_get(
                f"https://api.github.com/repos/{src['repo']}"
                f"/git/trees/HEAD?recursive=1", timeout=60))
            entry = next((e for e in tree.get("tree", [])
                          if e.get("path") == src["path"]), None)
            out[key] = {"ok": True, "size": entry["size"] if entry else 0,
                        "sha": entry["sha"][:8] if entry else ""}
        except RateLimited as e:
            out[key] = {"ok": False, "error": str(e), "rate_limited": True}
        except Exception as e:                              # noqa: BLE001
            out[key] = {"ok": False, "error": str(e)}
    return out
