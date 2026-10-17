# -*- coding: utf-8 -*-
"""第三方清理规则的下载与生成。

**这个模块是手写的**（不属于切分器生成的 app/core/mem.py / junk.py）。
命令行工具 tools/update_rules.py 与软件里的「更新规则」按钮都调它，
保证只有一份实现。

数据源（均为开源、活跃维护）：
    Winapp2.ini            github.com/MoscaDotTo/Winapp2            CC-BY-SA-4.0
    Winapp3.ini            github.com/MoscaDotTo/Winapp2 (Winapp3/) CC-BY-SA-4.0
    Winapp3/Archived entries.ini  同上                              CC-BY-SA-4.0
    BleachBit              github.com/bleachbit/bleachbit           GPL-3.0-or-later

    ⚠ Winapp3.ini 的许可里额外写了一句「若要修改 / 分发 / 托管，请先联系作者」。
      纯自用没问题；要公开发布本工具的话请先跟对方打招呼，
      或者用 include_winapp3=False 生成不含它的规则。

## 联网方式（踩过坑，别退回去）

**一律走仓库 tarball（`/repos/<repo>/tarball/HEAD`），不要用 blob / trees 接口。**

原因：GitHub 未认证 API 限额 60 次/小时，**blob 和 trees 接口都算在里面**，
而 **tarball 接口会 302 跳到 codeload.github.com，那条路不占 API 限额**。
实测过：API 限额已经 0/60（blob 请求全 403）的情况下，
tarball 照样能把 3.5 MB 的仓库完整下下来。

以前的写法是「Winapp2/Winapp3 用 blob 逐个取」，后果是限额一用完
**两个主规则源同时报废**，只剩 BleachBit 的几十条 —— 表现在用户那儿
就是「点了检查并更新，什么都没发生」。改成 tarball 之后这个失效模式消失。

顺带的好处：Archived entries.ini 和那些 ini 在同一个仓库里，
一次下载全都有，**零额外请求**。

tarball 里同名文件有多份副本（仓库根、Non-CCleaner/、Assembler/ 各一份），
**必须按完整相对路径取，绝不能按 basename 取** —— 按 basename 会随机抓到
构建产物那份。

下载内容缓存在 config/rule_cache/ 下，`CACHE_TTL_DAYS` 天内不重复下载。
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
        "tier": None,               # 按规则内容分档（上游主规则集，尊重它的分类）
        "tar": "winapp2",
    },
    "winapp3": {
        "repo": "MoscaDotTo/Winapp2",
        "path": "Winapp3/Winapp3.ini",
        "license": "CC-BY-SA-4.0（额外要求：分发前先联系作者）",
        "url": "https://github.com/MoscaDotTo/Winapp2/tree/master/Winapp3",
        "tier": None,
        "tar": "winapp2",
    },
    "winapp3_archived": {
        "repo": "MoscaDotTo/Winapp2",
        "path": "Winapp3/Archived entries.ini",
        "license": "CC-BY-SA-4.0（额外要求：分发前先联系作者）",
        "url": "https://github.com/MoscaDotTo/Winapp2/tree/master/Winapp3",
        # 上游自己把这些条目从主文件里**移除**了 —— 文件开头写明原因是
        # 「目标软件版本过时 / 厂商已下架 / 服务已关闭」，并说「条目仍可用，
        # 适合还在跑旧软件的系统」。**「已归档」是作者给出的降级信号**，
        # 所以整份文件一律进 caution（默认不勾），不按内容分档 ——
        # 那等于把作者做的降级决定抹掉。
        "tier": "caution",
        "tar": "winapp2",
    },
    "multron": {
        "repo": "winball501/MultronWcleaner-Database",
        "path": "database.txt",
        "license": "MIT",
        "url": "https://github.com/winball501/MultronWcleaner-Database",
        # 这份库**只当补充**：我们只从里面收「上游自己标了推荐(true)
        # **且**路径是缓存类」的目录，而且全部进 caution（默认不勾）。
        # 详见 parse_multron 的说明 —— 这份库里有一半条目上游自己标了
        # false（pagefile.sys / 系统还原点 / Windows.old / ESD …），
        # 那正是绝不该默认删的东西。
        "tier": "caution",
        "tar": "multron",
    },
}

# 要下载的仓库（tarball）。多个 SOURCES 共用同一个仓库时**只下一次**。
TARBALLS = {
    "winapp2": {"repo": "MoscaDotTo/Winapp2", "file": "winapp2.tar.gz",
                "label": "Winapp2 / Winapp3 规则库"},
    "bleachbit": {"repo": "bleachbit/bleachbit", "file": "bleachbit.tar.gz",
                  "label": "BleachBit 规则库"},
    "multron": {"repo": "winball501/MultronWcleaner-Database",
                "file": "multron.tar.gz",
                "label": "MultronWcleaner 数据库"},
}

CACHE_DIRNAME = "rule_cache"

# 缓存多少天内不重复下载。
# 用户定的是「BleachBit 缓存 7 天过期」，这里对所有仓库统一 7 天 ——
# 这些规则库本来就按周更新，每点一次按钮都重下 3.5 MB 没意义。
# 要强制拉最新用 force=True（界面上的「强制重新下载」）。
CACHE_TTL_DAYS = 7

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


def cached_age_days(path: str) -> float:
    """文件是多少天前写的。不存在返回 inf。"""
    if not os.path.exists(path):
        return float("inf")
    return (time.time() - os.path.getmtime(path)) / 86400.0


def _age_text(days: float) -> str:
    if days == float("inf"):
        return "不存在"
    if days < 1 / 24:
        return f"{days * 1440:.0f} 分钟前"
    if days < 1:
        return f"{days * 24:.0f} 小时前"
    return f"{days:.1f} 天前"


def fetch_tarball(key: str, offline: bool = False, force: bool = False,
                  log=None) -> tuple[str | None, str]:
    """下载（或复用缓存）某个仓库的 tarball，返回 (本地路径, 给人看的说明)。

    **这是本项目唯一该用的下载方式。** tarball 会 302 跳到
    codeload.github.com，**不占 GitHub API 的 60 次/小时限额**，
    而且一个仓库只要 1 次请求 —— 见模块开头「联网方式」那段。
    """
    def say(msg):
        if log:
            log(msg)

    cfg = TARBALLS[key]
    dest = os.path.join(cache_dir(), cfg["file"])
    age = cached_age_days(dest)

    if age <= CACHE_TTL_DAYS and not force:
        size = os.path.getsize(dest) // 1024
        return dest, (f"{cfg['label']}：用 {_age_text(age)}的缓存（{size} KB，"
                      f"{CACHE_TTL_DAYS} 天内不重复下载）")

    if offline:
        if os.path.exists(dest):
            size = os.path.getsize(dest) // 1024
            return dest, (f"{cfg['label']}：离线，用 {_age_text(age)}的缓存"
                          f"（{size} KB）")
        return None, f"{cfg['label']}：离线模式且无缓存"

    say(f"正在下载 {cfg['label']}（{cfg['repo']}，整个仓库打包）…")
    url = f"https://api.github.com/repos/{cfg['repo']}/tarball/HEAD"
    try:
        # 超时给足：tarball 要跳一次 codeload，实测 91 秒是正常值，
        # 给太小会把能成功的下载判死。
        data = http_get(url, timeout=180)
    except Exception as e:                                  # noqa: BLE001
        if os.path.exists(dest):
            size = os.path.getsize(dest) // 1024
            return dest, (f"{cfg['label']}：下载失败，退回 {_age_text(age)}的缓存"
                          f"（{size} KB）—— {e}")
        return None, f"{cfg['label']}：下载失败且无缓存（{e}）"

    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)       # 原子替换，避免下到一半被打断留下坏包
    return dest, f"{cfg['label']}：已下载 {len(data) // 1024} KB"


def extract_from_tarball(tar_path: str, wanted: dict[str, str]
                         ) -> tuple[dict[str, bytes], list[str]]:
    """从 tarball 里按**完整相对路径**取出指定文件。

    wanted: {来源 key: 仓库内相对路径}，例如
            {"winapp2": "Non-CCleaner/CCleaner7/Winapp2.ini"}

    ⚠ 必须比对完整相对路径，**绝不能只比对 basename**：
    Winapp2 仓库里有 6 份不同的 Winapp2.ini（仓库根一份、Non-CCleaner/ 下 5 份），
    按 basename 取会随机拿到构建产物那份，规则内容不一定一样。
    """
    tails = {k: "/" + v.replace("\\", "/").lstrip("/")
             for k, v in wanted.items()}
    out: dict[str, bytes] = {}
    with tarfile.open(tar_path, "r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            name = "/" + m.name.replace("\\", "/")
            for k, tail in tails.items():
                if k in out or not name.endswith(tail):
                    continue
                fh = tf.extractfile(m)
                if fh is not None:
                    out[k] = fh.read()
    return out, [k for k in wanted if k not in out]


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



def fetch_winapp_ini_files(offline: bool = False, include_winapp3: bool = True,
                           force: bool = False, log=None
                           ) -> tuple[dict[str, tuple[bytes, str]], str]:
    """一次 tarball 拿下 Winapp2.ini / Winapp3.ini / Archived entries.ini。

    返回 ({来源 key: (内容, 说明)}, tarball 说明)。

    为什么改成一次拿整个仓库，而不是像以前那样逐个文件取：
      · 逐个取走的是 blob / trees 接口，**占用 GitHub 那 60 次/小时的限额**；
        限额一用完两个主规则源就同时报废 —— 用户看到的现象就是
        「点了检查并更新，什么都没发生」
      · tarball 走 codeload，**不占限额**（实测限额 0/60 时照样能下）
      · Archived entries.ini 就在同一个包里，等于白送，零额外请求
    """
    wanted = {"winapp2": SOURCES["winapp2"]["path"]}
    if include_winapp3:
        wanted["winapp3"] = SOURCES["winapp3"]["path"]
        wanted["winapp3_archived"] = SOURCES["winapp3_archived"]["path"]

    tar_path, note = fetch_tarball("winapp2", offline=offline,
                                   force=force, log=log)
    if not tar_path:
        return {}, note

    try:
        raw, missing = extract_from_tarball(tar_path, wanted)
    except Exception as e:                                  # noqa: BLE001
        return {}, f"{note}；解包失败：{e}"

    out = {k: (v, f"{len(v) // 1024} KB") for k, v in raw.items()}
    if missing:
        note += f"；包里缺 {'、'.join(missing)}"
    return out, note


def fetch_bleachbit(offline: bool = False, force: bool = False,
                    log=None) -> tuple[list[tuple[str, bytes]], str]:
    """取 BleachBit 的所有 cleaner XML。

    用 tarball 一次拿整个仓库：100 多个 cleaner 逐个请求既慢又撞限额
    （实测只下到 42 个就被限流），而且走的 blob 接口**占用**那 60 次/小时，
    tarball 不占。
    """
    tar_path, note = fetch_tarball("bleachbit", offline=offline,
                                   force=force, log=log)
    if not tar_path:
        return [], note

    try:
        out = []
        with tarfile.open(tar_path, "r:gz") as tf:
            for m in tf.getmembers():
                if not m.isfile() or not m.name.endswith(".xml"):
                    continue
                # <repo>-<sha>/cleaners/xxx.xml
                # 用「是否包含 /cleaners/」判断，而不是按 "/" 切下标 ——
                # 包里哪天多一层或少一层目录，下标法会全落空。
                if "/cleaners/" not in "/" + m.name.replace("\\", "/"):
                    continue
                fh = tf.extractfile(m)
                if fh is not None:
                    out.append((os.path.basename(m.name), fh.read()))
        if not out:
            return [], f"{note}；但包里没找到 cleaners/*.xml"
        return out, f"{note}；解出 {len(out)} 个 cleaner"
    except Exception as e:                                  # noqa: BLE001
        return [], f"{note}；解包失败：{e}"


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


def translate_for_exclude(raw: str) -> str | None:
    """把 ExcludeKey 的路径转成占位符模板 —— **不做隐私/禁止段过滤**。

    这是与 translate() 唯一但关键的区别。ExcludeKey 说的是「别删这个」，
    它越是落在隐私目录里，我们越要听它；拿隐私名单去滤排除项，等于把
    最该听的排除项丢掉。实测踩到过：`%AppData%\\Microsoft\\Office\\Recent`
    因为含隐私段被 translate() 拒绝 → 排除项消失 → 模板
    `{ROAMING}\\Microsoft\\Office` 照删，用户的 Office 最近文档列表被清空，
    而上游明文写了排除。

    根映射失败（`%ProgramFiles%` 这类我们本来就不清理的根）仍返回 None ——
    那种路径下不可能有存活模板，忽略无害。也不限制通配符个数：排除项
    常常比模板更具体（如 `...\\Cache\\videoconverter*\\MSparkle\\*\\`），
    而匹配走的是字符串前缀，通配符在多也没关系。
    """
    p = (raw or "").strip().strip('"')
    if not p or "%" not in p:
        return None
    low = p.lower()
    if any(low.startswith(b) for b in BAD_ROOTS):
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
    return "{%s}\\" % name + rest


# ExcludeKeyN=TYPE|路径|文件规格      TYPE ∈ {FILE, PATH, REG}
# 语义：「这条路径虽然命中了上面的 FileKey，但它**不是垃圾，别删**」——
# 规则作者明文写下的排除清单。
_EXCLUDE_RE = re.compile(r"ExcludeKey\d+=(.+)$", re.I)
_FILEKEY_RE = re.compile(r"FileKey\d+=(.+)$", re.I)


def _normalize(path: str) -> str:
    return path.replace("/", "\\").rstrip("\\").lower()


def _is_under(child: str, parent: str) -> bool:
    """child 是否等于 parent，或位于 parent 之下。"""
    c, p = _normalize(child), _normalize(parent)
    return c == p or c.startswith(p + "\\")


def _section_excludes(body: list[str]) -> list[str]:
    """取出一段里所有 ExcludeKey 的**文件系统路径**模板。

    格式是 TYPE|路径|文件规格，要排除的是第二段。REG 类型（注册表）
    本项目根本不碰，直接跳过。

    注意用的是 translate_for_exclude，**不是** translate ——
    排除项不能被隐私名单滤掉，理由见该函数的 docstring。
    """
    out = []
    for line in body:
        m = _EXCLUDE_RE.match(line)
        if not m:
            continue
        parts = m.group(1).split("|")
        if parts[0].strip().upper() == "REG":
            continue
        raw = parts[1].strip() if len(parts) > 1 else parts[0].strip()
        tpl = translate_for_exclude(raw)
        if tpl:
            out.append(tpl)
    return out


def iter_sections(text: str):
    """把 ini 拆成 (段名, [行, ...])，保留出现顺序，丢掉注释与空行。"""
    name: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(";"):
            continue
        if s.startswith("[") and s.endswith("]"):
            if name is not None:
                yield name, body
            name, body = s[1:-1], []
            continue
        if name is not None:
            body.append(s)
    if name is not None:
        yield name, body


def parse_ini(text: str, counters: Counter, safe: dict, caution: dict,
              frules: dict, tier: str | None = None,
              caution_files: dict | None = None) -> None:
    """解析一份 winapp2 格式的 ini。

    tier 不为 None 时，本份文件的**所有**结果强制进那一档
    （Archived entries.ini 传 "caution"）—— 上游把条目归档就是它给出的
    降级信号，不能再按规则内容把它拱回 safe。

    ⚠ 必须按「段」而不是按「行」解析：ExcludeKey 的作用范围就是**段**，
    它排除的是同一段里 FileKey 命中的路径。以前只按行扫 FileKey，
    ExcludeKey 从来没人读过 —— 等于把规则作者写的排除清单整份丢掉，
    Winapp2 86 条 + Winapp3 1024 条 + Archived 31 条全被无视。
    """
    for name, body in iter_sections(text):
        if denied(name):
            counters["隐私条目(跳过)"] += 1
            continue
        excl = _section_excludes(body)
        if excl:
            counters["ExcludeKey 读到"] += len(excl)

        for line in body:
            m = _FILEKEY_RE.match(line)
            if not m:
                continue
            counters["FileKey 总数"] += 1
            parts = m.group(1).split("|")
            tpl = translate(parts[0].strip())
            if not tpl:
                counters["路径不合格(丢弃)"] += 1
                continue

            # 排除项落在这个模板之下 → **整条丢弃**。
            # 我们的模板是整目录粒度，没法表达「删这个目录，但留着里面
            # 某个子目录 / 某个文件」，所以唯一忠实的做法是不删。
            # 宁可少删，也不能违背规则作者写下的排除清单。
            if any(_is_under(x, tpl) for x in excl):
                counters["上游写了排除项(丢弃)"] += 1
                continue

            files = parts[1].strip() if len(parts) > 1 else ""
            base = os.path.basename(tpl)
            demoted = tier == "caution"

            if "*" in base:
                core = base.replace("*", "").replace("?", "").strip()
                if len(core) < 3 or not re.search(
                        r"cache|log|temp|dump|thumb|shader|crash|notif",
                        core, re.I):
                    counters["裸通配(拒绝)"] += 1
                    continue
                (caution if demoted else safe)[tpl] = 1
                counters["谨慎-整目录" if demoted else "安全-通配目录"] += 1
            elif files == "*" or not files:
                if SAFE_RE.match(base):
                    (caution if demoted else safe)[tpl] = 1
                    counters["谨慎-整目录" if demoted else "安全-整目录"] += 1
                elif CAUTION_RE.match(base):
                    caution[tpl] = 1
                    counters["谨慎-整目录"] += 1
                else:
                    counters["名字不像缓存(丢弃)"] += 1
            else:
                ok = [x.strip() for x in files.split(";")
                      if x.strip()
                      and x.strip().lower() in SAFE_FILE_PATTERNS]
                if ok:
                    fd = (caution_files if demoted and caution_files is not None
                          else frules)
                    fd.setdefault(tpl, set()).update(ok)
                    counters["按模式清理(谨慎档)" if demoted
                             and caution_files is not None
                             else "按模式清理"] += 1
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


# --------------------------------------------- MultronWcleaner（自有格式）
# database.txt 不是 ini，是它自己的格式：
#
#     {=分类名                ← 开块。⚠ 这一行**没有右花括号**
#     名称=路径=true|false    ← 规则行，分隔符是单个 = 且无空格
#     }                       ← 闭块，独占一行
#
# 还有二级结构（73 个分类用到）：
#
#     #profile#=<绝对路径>=true        ← 声明其后 #profileget# 的根
#     名称=#profileget#=\子路径=true   ← 相对上面那个根
#
# 末尾 true/false 的语义**有权威定义**（不是我们猜的）：主程序源码
# `MultronWcleaner/Processes/Load.cs` 把该字段读进 `LoadEntry.Recommended`，
# 然后 L748-750：
#     bool isChecked = selections.TryGetValue(entry.Path, out bool saved)
#                      ? saved : entry.Recommended;
#     main.databaseDefaults[entry.Path] = entry.Recommended;
# 也就是**上游建议的默认勾选状态**。
#
# 实测 5132 条里 true 2812 / false 2320。标 false 的正是
# pagefile.sys、hiberfil.sys、系统还原点、Windows.old、C:\ESD、
# Config.Msi、$WinREAgent、MSOCache、found.000 这些**绝不该默认删**的，
# 还有 Prefetch、D3DSCache、事件日志这类"看着像缓存其实不是"的。
#
# 所以我们的收法很紧：**只收 true **且** 路径是缓存类** 的目录，
# 并且全部进 caution（默认不勾）。两道信号都为真才要 ——
# 这份库对我们是锦上添花，宁可少收。
_MULTRON_RULE_RE = re.compile(r"^([^=]+)=(.+?)=(true|false)$", re.I)
_MULTRON_PROFILE_RE = re.compile(r"^#profile#=(.+?)=(?:true|false)$", re.I)

# 绝对路径 → 占位符。**只认这几个根**。
# 其余（C:\Windows\*、C:\Program Files\*、以及盘符根下的 pagefile.sys /
# hiberfil.sys / Windows.old / ESD / Config.Msi / $WinREAgent 等）一律
# 映射失败、被 translate() 丢掉 —— 那些本来就不该删，丢掉正合意。
_MULTRON_ROOTS = (
    ("c:\\users\\{##}", "%USERPROFILE%"),
    ("c:\\users\\public", "%PUBLIC%"),
    ("c:\\programdata", "%PROGRAMDATA%"),
)


def multron_to_template(raw: str) -> str | None:
    """把 MultronWcleaner 的绝对路径转成我们的 {占位符} 模板。"""
    p = (raw or "").strip().strip('"').replace("/", "\\")
    low = p.lower()
    for pre, var in _MULTRON_ROOTS:
        if low.startswith(pre):
            p = var + p[len(pre):]
            break
    else:
        return None
    return translate(p)


def _multron_looks_like_file(base: str) -> bool:
    """这一眼看去是文件而不是目录吗。

    通配符一律算文件（MultronWcleaner 的通配语义没有文档，不猜）；
    带扩展名的也算，但 `.cache` 这种「点开头」的不是。
    """
    if "*" in base or "?" in base:
        return True
    m = re.search(r"\.[A-Za-z0-9]{1,5}$", base)
    return bool(m) and m.start() > 0


def _multron_cacheish(tpl: str) -> bool:
    """模板里有没有一段是缓存/日志/临时。

    整条路径任何一段命中 SAFE_RE 就算 —— 因为 `...\\Cache\\Data` 这种
    末段是 Data、上一层才是 Cache 的很常见。
    """
    for seg in tpl.split("\\"):
        seg = seg.strip("{}")
        if seg and SAFE_RE.match(seg):
            return True
    return False


def parse_multron(text: str, counters: Counter, caution: dict) -> None:
    """解析 MultronWcleaner 的 database.txt，只往 caution 里放缓存目录。"""
    profile: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line == "}" or line.startswith("{="):
            profile = None              # 换分类就忘掉上一块的 profile 根
            continue

        m = _MULTRON_PROFILE_RE.match(line)
        if m:
            profile = m.group(1).strip().rstrip("\\")
            continue

        m = _MULTRON_RULE_RE.match(line)
        if not m:
            counters["Multron 无法解析的行(跳过)"] += 1
            continue
        path = m.group(2).strip()
        state = m.group(3).lower()
        counters["Multron 条目总数"] += 1

        # ① 上游自己标了不推荐的，一律不要
        if state != "true":
            counters["Multron 上游标为不推荐(丢弃)"] += 1
            continue

        # ② 二级结构：路径挂在上面声明的 profile 根下面。
        #    我们不知道用户机器上那个 profile 目录叫什么名字，
        #    用 * 占位 —— 模板本来就是在现场展开的。
        low = path.lower()
        if low.startswith("#profileget#"):
            # 是 `#profileget#=\cache2` 这种形式，中间的 = 是分隔符不是路径
            sub = path[len("#profileget#"):].replace("/", "\\").lstrip("=")
            if not profile:
                counters["Multron 缺 profile 根(丢弃)"] += 1
                continue
            path = profile + "\\*" + sub

        # 隐私/禁止段先判，好把账记清楚。
        # 注意 translate() 内部也会做这个判断并返回 None，若不先判，
        # 这些条目会被记成「路径不合格」，账就对不上了。
        if denied(path):
            counters["Multron 隐私条目(跳过)"] += 1
            continue

        tpl = multron_to_template(path)
        if not tpl:
            counters["Multron 路径不合格(丢弃)"] += 1
            continue

        base = tpl.rsplit("\\", 1)[-1]
        if _multron_looks_like_file(base):
            counters["Multron 疑似文件(丢弃)"] += 1
            continue
        # ③ 必须是缓存类
        if not _multron_cacheish(tpl):
            counters["Multron 不是缓存类(丢弃)"] += 1
            continue

        caution[tpl] = 1
        counters["Multron 收录(谨慎档)"] += 1


def fetch_multron(offline: bool = False, force: bool = False,
                  log=None) -> tuple[str | None, str]:
    """取 MultronWcleaner 的 database.txt，返回 (文本, 说明)。

    与其它来源一样走 tarball（不占 API 限额）。这个仓库很小
    （tarball 约 57 KB），7 天缓存一次完全不亏。
    """
    cfg = TARBALLS["multron"]
    tar, note = fetch_tarball("multron", offline=offline, force=force, log=log)
    if not tar:
        return None, note
    got, missing = extract_from_tarball(
        tar, {"multron": SOURCES["multron"]["path"]})
    if "multron" not in got:
        return None, f"{note}；包里没有 {SOURCES['multron']['path']}（{missing}）"
    data = got["multron"]
    return data.decode("utf-8", errors="replace"), f"{note}（{len(data)} 字节）"


# ----------------------------------------------------------------- 主流程
def build_text(offline: bool = False, include_winapp3: bool = True,
               refresh: bool = False, log=None) -> tuple[str, dict]:
    """下载并生成规则文件内容，返回 (文本, 统计)。不写文件。

    refresh=True 时**无视缓存**、强制重新下载。默认用 CACHE_TTL_DAYS
    天内的缓存，避免每点一次按钮都重下几 MB。
    """
    def say(msg):
        if log:
            log(msg)

    counters = Counter()
    provenance = {}
    safe, caution, frules = {}, {}, {}
    caution_files: dict[str, set[str]] = {}

    # Winapp2 / Winapp3 / Archived entries 都在同一个仓库里，
    # **一次 tarball 全拿到** —— 见 fetch_winapp_ini_files 的说明。
    got, note = fetch_winapp_ini_files(offline=offline,
                                       include_winapp3=include_winapp3,
                                       force=refresh, log=log)
    say(f"  {note}")
    keys = ["winapp2"] + ([] if not include_winapp3
                          else ["winapp3", "winapp3_archived"])
    for key in keys:
        src = SOURCES[key]
        if key not in got:
            say(f"  !! 没拿到 {key}（{src['path']}）")
            continue
        data, size = got[key]
        text = data.decode("utf-8", errors="replace")
        m = re.search(r";\s*Version:\s*(\S+)", text)
        n = re.search(r"# of (?:archived entries|entries):\s*([\d,]+)", text)
        provenance[key] = {
            "url": src["url"], "path": src["path"], "license": src["license"],
            "version": m.group(1) if m else "?",
            "entries": n.group(1) if n else "?",
            "tier": src["tier"] or "按内容分档",
        }
        say(f"  {src['path']}（{size}）—— 版本 "
            f"{provenance[key]['version']} / 条目 {provenance[key]['entries']}"
            f" / {provenance[key]['tier']}")
        parse_ini(text, counters, safe, caution, frules,
                  tier=src["tier"], caution_files=caution_files)

    say("正在获取 BleachBit 规则…")
    files, note = fetch_bleachbit(offline, refresh, log)
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

    # MultronWcleaner 是**补充来源**：只收「上游标了推荐 + 是缓存类」的
    # 目录，全部进 caution。没拿到不影响主流程（见 parse_multron）。
    say("正在获取 MultronWcleaner 数据库…")
    mtext, mnote = fetch_multron(offline, refresh, log)
    say(f"  {mnote}")
    if mtext:
        before = len(caution)
        parse_multron(mtext, counters, caution)
        provenance["multron"] = {
            "url": SOURCES["multron"]["url"],
            "path": SOURCES["multron"]["path"],
            "license": SOURCES["multron"]["license"],
            "version": time.strftime("%Y-%m-%d"),
            "entries": str(counters.get("Multron 条目总数", 0)),
            "tier": "caution",
        }
        say(f"  收录 {len(caution) - before} 条缓存目录"
            f"（全部进谨慎档，默认不勾选）")
    else:
        say("  !! 没拿到 MultronWcleaner 数据库，本次跳过这一来源")

    sorted_safe = sorted(safe, key=lambda t: t.lower())
    sorted_caution = sorted(caution, key=lambda t: t.lower())
    sorted_files = sorted(frules.items(), key=lambda x: x[0].lower())
    sorted_caution_files = sorted(caution_files.items(),
                                  key=lambda x: x[0].lower())

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
        '四档：',
        '  THIRD_PARTY_SAFE_DIRS          纯缓存，删了自动重建',
        '  THIRD_PARTY_CAUTION_DIRS       可重建但有可见副作用（默认不勾选）',
        '  THIRD_PARTY_FILE_RULES         按文件名模式清理，不清空目录',
        '  THIRD_PARTY_CAUTION_FILE_RULES 同上，但来源被上游降过级（默认不勾选）',
        '',
        '占位符：{LOCAL} {ROAMING} {PROFILE} {WINDIR} {PROGRAMDATA} {TEMP}',
        '        {SYSTEMDRIVE} {PUBLIC}',
        '',
        '已读入 ExcludeKey（规则作者明文写的「这条路径别删」）——',
        '排除项落在某个目录模板之下时，**整条模板丢弃**：我们的粒度是',
        '整目录，表达不了「删目录但留着某个子目录」，宁可少删也不违背它。',
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
    lines += [']', '', 'THIRD_PARTY_CAUTION_FILE_RULES = [']
    lines += [f"    ({t!r}, {sorted(p)!r})," for t, p in sorted_caution_files]
    lines += [']', '']

    stats = {
        "safe": len(sorted_safe),
        "caution": len(sorted_caution),
        "files": len(sorted_files),
        "caution_files": len(sorted_caution_files),
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
           refresh: bool = False, log=None) -> dict:
    """完整流程：下载 → 生成 → 写入 out_path。返回统计。

    force   —— 绕过「结果太少」的安全闸（**别拿它当刷新用**）
    refresh —— 绕过下载缓存，强制拉最新

    写入前有两道保险：
      1. 结果太少（< MIN_SAFE_DIRS）直接报错、**不写**，原有规则保持不变
      2. 写之前把原文件备份成 .bak
    """
    text, stats = build_text(offline=offline, include_winapp3=include_winapp3,
                             refresh=refresh, log=log)

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
