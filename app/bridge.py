# -*- coding: utf-8 -*-
"""JS ↔ Python 接口。

这是前端能触达 Python 的**唯一通道**。收敛成一个类的好处：想审计「界面到底能
做什么」时，只需要读这一个文件，不用在几十个文件里翻。

约定：
  * 所有方法都返回 JSON 可序列化的基本类型（dict / list / str / int / bool）
  * 长任务一律「启动 + 轮询」两段式，不在方法里同步跑
  * 任何异常都就地转成 {"ok": False, "error": ...}，不让它穿到 JS 变成白屏
"""
import os
import shutil
import sys
import threading
import time

from . import elevation
from .core import junk, mem

APP_TITLE = "mahiru小助手"
APP_AUTHOR = "decaycc"
APP_VERSION = "1.0.0"


def _guard(fn):
    """把异常统一转成结构化错误，前端永远拿到能显示的东西。"""
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:                              # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


class Api:
    """所有方法都会在 JS 侧挂到 window.pywebview.api 上。"""

    def __init__(self, jobs):
        self.jobs = jobs
        # 由 main.py 注入：调用后关掉窗口、结束进程。
        # 提权重启必须真的把本进程关掉 —— 新进程已经在等本进程退出，
        # 不关就会留下两个窗口（一个普通权限、一个管理员权限），
        # 而且两者抢同一个 WebView2 用户数据目录。
        self._quit_hook = None

    def set_quit_hook(self, fn):
        self._quit_hook = fn

    @_guard
    def quit_app(self) -> dict:
        """关闭本程序。提权重启成功后由界面调用。

        为什么要这么绕：pywebview 的 `window.destroy()` 不是线程安全的，
        从后台线程调可能**静默无效**（实测就是这样 —— 调了 destroy，
        进程照样活着，于是留下两个窗口）。所以：

          1. 先回包，避免界面等一个永远不返回的 Promise
          2. 稍后尝试优雅关窗
          3. 再等一小会儿；还活着就 `os._exit(0)` 硬退出

        硬退出在这里是安全的：调用前配置已经落盘，退出路径上没有需要
        清理的状态。而提权重启**必须**保证旧进程真的消失 —— 新旧进程
        共用同一个 WebView2 用户数据目录，旧的赖着不走，新的会起不来。
        """
        if self._quit_hook is None:
            return {"ok": False, "error": "退出接口未接好"}

        def _do_quit():
            try:
                self._quit_hook()
            except Exception:                               # noqa: BLE001
                pass
            # 实测：destroy() 从后台线程调基本不生效，会走到这里。
            # 硬退出在这里是安全的 —— 调用前配置已落盘，退出路径上
            # 没有需要清理的状态；而提权重启必须保证旧进程真的消失。
            time.sleep(0.6)
            os._exit(0)

        threading.Timer(0.15, _do_quit).start()
        return {"ok": True}

    # ==================================================== 应用信息 / 权限
    @_guard
    def get_app_info(self) -> dict:
        """标题、版本、作者、是否打包运行、Python 版本。"""
        return {
            "ok": True,
            "title": APP_TITLE,
            "author": APP_AUTHOR,
            "version": APP_VERSION,
            "frozen": bool(getattr(sys, "frozen", False)),
            "python": sys.version.split()[0],
            "executable": sys.executable,
        }

    @_guard
    def is_admin(self) -> dict:
        """当前是否管理员权限。"""
        return {"ok": True, "admin": elevation.is_admin()}

    @_guard
    def relaunch_admin(self) -> dict:
        """以管理员身份重启。调用方应先把配置落盘，再调这个。"""
        ok, msg = elevation.relaunch()
        return {"ok": ok, "message": msg, "will_exit": ok}

    # ==================================================== 概览数据
    @_guard
    def get_overview(self) -> dict:
        """概览页要的全部实时数据：内存、磁盘、回收站、规则规模。"""
        st = mem.get_memory_status() or {}
        total = st.get("total") or st.get("total_phys") or 0
        avail = st.get("avail") or st.get("avail_phys") or 0
        used = max(0, total - avail)

        disks = []
        for root in junk.fixed_drives():
            try:
                u = shutil.disk_usage(root)
                disks.append({
                    "root": root,
                    "total": u.total,
                    "used": u.used,
                    "free": u.free,
                    "percent": round(u.used / u.total * 100, 1) if u.total else 0,
                })
            except Exception:                               # noqa: BLE001
                continue

        rb = {"items": 0, "size": 0, "ok": False}
        try:
            rb = junk.recycle_bin_info()
        except Exception:                                   # noqa: BLE001
            pass

        rules = len(junk.RULES)
        by_level = {}
        for r in junk.RULES:
            by_level[r["level"]] = by_level.get(r["level"], 0) + 1

        return {
            "ok": True,
            "admin": elevation.is_admin(),
            "memory": {
                "total": total,
                "avail": avail,
                "used": used,
                "percent": st.get("percent", 0),
                "cache": st.get("cache", 0),
            },
            "disks": disks,
            "recycle_bin": {"items": rb.get("items", 0),
                            "size": rb.get("size", 0),
                            "accessible": bool(rb.get("ok"))},
            "rules": {"total": rules, "by_level": by_level},
            "third_party_rules": _third_party_count(),
            "jobs_running": len(self.jobs.running()),
        }

    # ==================================================== 列表数据
    @_guard
    def list_processes(self, limit: int = 300) -> dict:
        """进程列表（带保护/可关闭/可整理分类）。

        只读：这里不做任何 trim 或 kill，分类只是把核心的判定结果读出来给界面用。
        """
        procs = mem.collect_processes() or []
        # 静默 log：这里只查询分类，不该往界面推日志
        opt = mem.Optimizer(lambda *_: None)
        rows = []
        for p in procs:
            name = p.get("name") or ""
            try:
                protected = opt.is_protected(p)
            except Exception:                               # noqa: BLE001
                protected = True
            try:
                closable = opt.is_closable(p)
            except Exception:                               # noqa: BLE001
                closable = False
            try:
                trimmable = opt.is_trimmable(p)
            except Exception:                               # noqa: BLE001
                trimmable = False
            rows.append({
                "pid": p.get("pid"),
                "name": name,
                "title": (p.get("title") or "")[:120],
                "mem": p.get("mem") or 0,
                "protected": bool(protected),
                "closable": bool(closable),
                "trimmable": bool(trimmable),
                "why": mem.describe(name) if protected else "",
            })
        rows.sort(key=lambda r: -(r["mem"] or 0))
        return {
            "ok": True,
            "total": len(rows),
            "shown": min(limit, len(rows)),
            "closable": sum(1 for r in rows if r["closable"]),
            "trimmable": sum(1 for r in rows if r["trimmable"]),
            "reclaimable": sum(r["mem"] for r in rows if r["trimmable"]),
            "processes": rows[:limit],
        }

    @_guard
    def list_rules(self) -> dict:
        """清理规则清单（只列出，不扫描）。

        扫描要遍历磁盘、耗时较长，走 start_scan + 轮询（M5）。
        这里只给界面渲染表格用，targets 是「本机真实存在的目标目录数」。
        """
        out = []
        for r in junk.RULES:
            try:
                targets = junk.expand_paths(r)
            except Exception:                               # noqa: BLE001
                targets = []
            out.append({
                "key": r.get("key", ""),
                "name": r.get("name", ""),
                "category": r.get("category", ""),
                "level": r.get("level", "safe"),
                "kind": r.get("kind", ""),
                "default": bool(r.get("default", r.get("level") == "safe")),
                "desc": r.get("desc", ""),
                "patterns": list(r.get("patterns") or []),
                "targets": len(targets),
                "sample": targets[:4],
            })
        out.sort(key=lambda x: ({"safe": 0, "caution": 1, "risky": 2}
                                .get(x["level"], 3), x["name"]))
        by = {}
        for r in out:
            by[r["level"]] = by.get(r["level"], 0) + 1
        return {"ok": True, "total": len(out), "by_level": by, "rules": out}

    # ==================================================== 内存优化动作
    #
    # 安全设计：界面**无法**让核心去动任意进程。
    # Optimizer 内部会对每个进程重新跑 is_protected / is_closable / is_trimmable，
    # 即使这里传进来的是任意 PID 列表，受保护的进程也会被逐个跳过。
    # 这是一道纵深防御：UI 的勾选状态不可信。
    @_guard
    def get_capabilities(self) -> dict:
        """当前权限下哪些功能可用。非管理员时界面要给出明确引导。"""
        admin = elevation.is_admin()
        return {
            "ok": True,
            "admin": admin,
            # 这几项需要管理员：清空待机列表、部分系统级进程的工作集
            "need_admin": ["standby"],
            "can_trim": True,           # 自己的进程总能整理，别人的需要权限
            "can_close": True,          # 非管理员只能关掉自己启动的应用
            "can_standby": admin,
            "closed_apps": len((mem.load_config() or {}).get("closed_apps") or []),
            "has_gamedvr_backup": bool(
                (mem.load_config() or {}).get("gamedvr_backup")),
        }

    @_guard
    def start_trim(self, pids: list) -> dict:
        """整理选中进程的工作集（把闲置内存还给系统）。"""
        pids = _as_pids(pids)
        if not pids:
            return {"ok": False, "error": "没有选中任何进程"}
        jid = self.jobs.start("trim", f"整理 {len(pids)} 个进程的工作集",
                              lambda job: _trim_worker(job, pids))
        return {"ok": True, "job_id": jid}

    @_guard
    def start_close(self, pids: list, graceful: bool = True) -> dict:
        """关闭选中的进程。graceful=True 时先发关闭消息，超时才强杀。"""
        pids = _as_pids(pids)
        if not pids:
            return {"ok": False, "error": "没有选中任何进程"}
        jid = self.jobs.start(
            "close",
            f"关闭 {len(pids)} 个进程" + ("（优雅）" if graceful else "（强制）"),
            lambda job: _close_worker(job, pids, graceful))
        return {"ok": True, "job_id": jid}

    @_guard
    def start_boost(self, opts: dict | None = None) -> dict:
        """一键加速：按 opts 组合执行完整优化流程。

        opts 可用键（缺省值见下）：
            kill_safe     关闭安全级后台应用   默认 True
            kill_optional 关闭可选级后台应用   默认 False
            trim          清理工作集           默认 True
            standby       清空待机内存列表     默认 True（需管理员）
            gamedvr       关闭 Xbox 后台录制   默认 False
            power         切到高性能电源计划   默认 False
        """
        o = {
            "kill_safe": True, "kill_optional": False, "trim": True,
            "standby": True, "gamedvr": False, "power": False,
        }
        if isinstance(opts, dict):
            for k in list(o):
                if k in opts:
                    o[k] = bool(opts[k])
        jid = self.jobs.start("boost", "一键加速",
                              lambda job: _boost_worker(job, o))
        return {"ok": True, "job_id": jid, "opts": o}

    @_guard
    def set_priority(self, pid: int, level: str) -> dict:
        """调整单个进程的优先级。

        级别接受英文键（idle/below/normal/above/high）或中文
        （低/低于正常/正常/高于正常/高），内部统一归一化。
        「实时」会被降级成「高」—— 实时优先级会把整个系统拖卡，不该开放。
        """
        lv = mem.norm_priority(level)
        if not lv:
            return {"ok": False, "error": f"未知优先级：{level}"}
        ok, msg = mem.set_priority(int(pid), lv)
        return {"ok": bool(ok), "message": msg, "level": lv}

    @_guard
    def list_power_plans(self) -> dict:
        """可用电源计划。"""
        cur_guid, cur_name = mem.active_power_plan()
        return {"ok": True, "current": {"guid": cur_guid, "name": cur_name},
                "plans": mem.available_plans()}

    @_guard
    def relaunch_closed(self) -> dict:
        """重启之前被本工具关闭的应用（记录在配置里）。"""
        jid = self.jobs.start("relaunch", "重启已关闭的应用",
                              lambda job: _relaunch_worker(job))
        return {"ok": True, "job_id": jid}

    @_guard
    def revert_system(self) -> dict:
        """还原被改动的系统设置（GameDVR 与电源计划）。"""
        jid = self.jobs.start("revert", "还原系统设置",
                              lambda job: _revert_worker(job))
        return {"ok": True, "job_id": jid}

    @_guard
    def memory_snapshot(self) -> dict:
        """轻量内存快照：动作执行前后刷新结果卡片用。"""
        st = mem.get_memory_status() or {}
        total = st.get("total") or 0
        avail = st.get("avail") or 0
        return {"ok": True, "total": total, "avail": avail,
                "used": max(0, total - avail), "percent": st.get("percent", 0),
                "cache": st.get("cache", 0)}

    # ==================================================== 游戏优先级
    #
    # 旧版 tkinter 有一个专门的「游戏优先级」面板：下拉列出正在运行的游戏，
    # 选个级别点应用。新版一开始只做了「对勾选的进程设优先级」，
    # 把「直接挑游戏」这个入口弄丢了 —— 而这个才是实际用法。
    # 这里按旧版的判据恢复：**有窗口标题的进程**才算游戏/应用。
    @_guard
    def list_games(self) -> dict:
        """列出有窗口的进程（真正在跑的游戏 / 应用），附带当前优先级。"""
        procs = mem.collect_processes() or []
        cfg = mem.load_config() or {}
        saved = {str(k).lower(): v for k, v in (cfg.get("priority_map") or {}).items()}

        rows = []
        for p in procs:
            title = (p.get("title") or "").strip()
            if not title:
                continue                       # 没有窗口 = 后台进程，不是"游戏"
            exe = (p.get("name") or "").lower()
            rows.append({
                "pid": p["pid"],
                "name": p.get("name") or "",
                "exe": exe,
                "title": title[:90],
                "mem": p.get("mem") or 0,
                "priority": mem.get_priority(p["pid"]) or "未知",
                "saved": saved.get(exe, ""),
            })
        rows.sort(key=lambda r: -(r["mem"] or 0))
        return {"ok": True, "games": rows, "saved": saved}

    @_guard
    def remember_priority(self, exe: str, level: str) -> dict:
        """记住某个程序该用的优先级（下次可一键应用）。

        传空的 level 表示取消记忆。存的是**程序名 -> 级别**，
        因为进程 PID 每次启动都变，只有程序名是稳定的。
        """
        exe = str(exe or "").strip().lower()
        if not exe:
            return {"ok": False, "error": "缺少程序名"}
        cfg = mem.load_config() or {}
        m = dict(cfg.get("priority_map") or {})
        lv = mem.norm_priority(level)
        if lv:
            m[exe] = lv
        else:
            m.pop(exe, None)
        cfg["priority_map"] = m
        mem.save_config(cfg)
        return {"ok": True, "map": m}

    @_guard
    def apply_saved_priorities(self) -> dict:
        """把记住的优先级一次性应用到当前正在运行的程序上。

        不做后台常驻监听 —— 那要一直扫进程，代价大于收益。
        游戏启动后点一下这个按钮就够了。
        """
        jid = self.jobs.start("prio", "应用已记住的优先级",
                              lambda job: _apply_saved_worker(job))
        return {"ok": True, "job_id": jid}

    @_guard
    def apply_saved_priorities_quick(self) -> dict:
        """同步版本：只应用一次，用于按钮的即时反馈（不做成任务）。"""
        cfg = mem.load_config() or {}
        m = {str(k).lower(): v for k, v in (cfg.get("priority_map") or {}).items()}
        if not m:
            return {"ok": False, "error": "还没有记住任何优先级"}
        done, failed, missed = [], [], []
        for p in (mem.collect_processes() or []):
            exe = (p.get("name") or "").lower()
            level = m.get(exe)
            if not level:
                continue
            ok, msg = mem.set_priority(p["pid"], mem.norm_priority(level))
            label = f"{p['name']} → {level}"
            (done if ok else failed).append(label)
        running = {(p.get("name") or "").lower()
                   for p in (mem.collect_processes() or [])}
        missed = [k for k in m if k not in running]
        return {"ok": True, "applied": done, "failed": failed,
                "not_running": missed, "total": len(m)}

    # ==================================================== 深度内存优化
    @_guard
    def deep_ops_info(self) -> dict:
        """7 项深度优化的元信息。

        名称与说明直接取自核心的 DEEP_OPS，避免界面和核心两处各写一份而对不上。
        """
        admin = elevation.is_admin()
        ops = []
        for key, name, desc in mem.DEEP_OPS:
            needs = _DEEP_NEEDS_ADMIN.get(key, True)
            ops.append({
                "key": key,
                "name": name,
                "desc": desc,
                "needs_admin": needs,
                # 非管理员时标注出来，但**不禁用** —— 直接禁用会掩盖真实能力，
                # 而且不同机器的权限策略可能不一样。失败了核心会说明原因。
                "blocked": needs and not admin,
                "warning": _DEEP_WARN.get(key, ""),
                "default": key != "combine",
            })
        return {"ok": True, "admin": admin, "ops": ops}

    @_guard
    def start_deep_optimize(self, opts: dict | None = None) -> dict:
        """执行深度内存优化。opts 的键就是 deep_ops_info 返回的 key。"""
        wanted = {}
        for key, _, _ in mem.DEEP_OPS:
            wanted[key] = bool((opts or {}).get(key, key != "combine"))
        if not any(wanted.values()):
            return {"ok": False, "error": "一项都没勾选"}
        jid = self.jobs.start("deep", "深度内存优化",
                              lambda job: _deep_worker(job, wanted))
        return {"ok": True, "job_id": jid, "opts": wanted}

    # ==================================================== 垃圾清理
    @_guard
    def start_scan(self, keys: list) -> dict:
        """扫描选中的规则，统计可释放空间。

        逐条规则串行扫描并上报进度。深扫（node_modules 之类）会遍历大量目录，
        所以核心的 progress 回调必须**节流**后再用，否则会把界面刷爆。
        """
        keys = _as_keys(keys)
        if not keys:
            return {"ok": False, "error": "没有选中任何规则"}
        jid = self.jobs.start("scan", f"扫描 {len(keys)} 条规则",
                              lambda job: _scan_worker(job, keys))
        return {"ok": True, "job_id": jid}

    @_guard
    def junk_detail(self, key: str) -> dict:
        """单条规则的路径明细。只做路径展开，不扫描磁盘。"""
        rule = _rule_by_key(key)
        if rule is None:
            return {"ok": False, "error": f"未知规则 {key}"}
        try:
            paths = junk.expand_paths(rule)
        except Exception as e:                              # noqa: BLE001
            return {"ok": False, "error": str(e)}
        return {
            "ok": True,
            "key": rule["key"], "name": rule["name"],
            "level": rule["level"], "kind": rule["kind"],
            "desc": rule.get("desc", ""),
            "patterns": list(rule.get("patterns") or []),
            "paths": paths,
            "exists": [p for p in paths if os.path.exists(p)],
        }

    @_guard
    def start_clean(self, keys: list) -> dict:
        """清理选中的规则。

        安全防线全在核心侧，这里**不做任何「我判断可以删」的决定**：
          · `_safe_target()` 对每个待删路径做前置校验（保护清单/隐私/个人目录）
          · reparse point（符号链接、目录联接）一律跳过，避免顺着链接误伤
          · 占用中的文件记为失败并跳过，**不做强制删除**
        """
        keys = _as_keys(keys)
        if not keys:
            return {"ok": False, "error": "没有选中任何规则"}
        jid = self.jobs.start("clean", f"清理 {len(keys)} 条规则",
                              lambda job: _clean_worker(job, keys))
        return {"ok": True, "job_id": jid}

    @_guard
    def empty_recycle_bin(self) -> dict:
        """清空回收站。交给系统的 SHEmptyRecycleBinW，不自行删除文件。"""
        jid = self.jobs.start("recycle", "清空回收站",
                              lambda job: _recycle_worker(job))
        return {"ok": True, "job_id": jid}

    @_guard
    def start_dism(self, reset_base: bool = False) -> dict:
        """DISM 组件清理。耗时很长（可能十几分钟），必须可取消。"""
        jid = self.jobs.start("dism", "DISM 组件清理",
                              lambda job: _dism_worker(job, bool(reset_base)))
        return {"ok": True, "job_id": jid}

    # ==================================================== 规则更新
    @_guard
    def rules_info(self) -> dict:
        """当前规则库的状态：来自哪里、本机命中多少。"""
        from .core import rule_update
        from .paths import config_dir, is_frozen, resource_root

        override = os.path.join(config_dir(), "third_party_rules.py")
        counts = {"safe": 0, "caution": 0, "files": 0}
        for key, bucket in (("third_party_apps", "safe"),
                            ("third_party_caution", "caution"),
                            ("third_party_logs", "files")):
            r = next((x for x in junk.RULES if x.get("key") == key), None)
            if r is not None:
                try:
                    counts[bucket] = len(junk.expand_paths(r))
                except Exception:                           # noqa: BLE001
                    pass

        # 生成文件头部写了来源与版本，读出来展示
        versions = []
        try:
            src = (override if os.path.isfile(override)
                   else os.path.join(resource_root(), "app", "core",
                                     "third_party_rules.py"))
            with open(src, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("  * ") or line.startswith("      "):
                        versions.append(line.strip())
                    elif versions:
                        break
        except Exception:                                   # noqa: BLE001
            pass

        return {
            "ok": True,
            "frozen": is_frozen(),
            "using_override": os.path.isfile(override),
            "override_path": override if os.path.isfile(override) else "",
            "cache_dir": rule_update.cache_dir(),
            "matched": counts,
            "matched_total": sum(counts.values()),
            "versions": versions,
        }

    @_guard
    def check_rule_update(self) -> dict:
        """只查上游有没有变化（少量请求，不下载正文）。"""
        from .core import rule_update
        res = rule_update.check_available()
        limited = any(v.get("rate_limited") for v in res.values())
        return {"ok": not limited, "sources": res,
                "error": "GitHub 限额用完了，过一小时再试" if limited else ""}

    @_guard
    def start_rule_update(self, offline: bool = False) -> dict:
        """下载并应用新规则。走后台任务（要联网，可能几十秒）。"""
        jid = self.jobs.start(
            "rules",
            "更新清理规则" + ("（离线缓存）" if offline else ""),
            lambda job: _rule_update_worker(job, bool(offline)))
        return {"ok": True, "job_id": jid}

    # ==================================================== 小功能
    @_guard
    def startup_items(self) -> dict:
        """启动项列表（注册表 Run 键 + 启动文件夹）。只读。"""
        from .core import tools
        d = tools.list_startup_items()
        d["admin"] = elevation.is_admin()
        return {"ok": True, **d}

    @_guard
    def set_startup(self, item_id: str, enabled: bool) -> dict:
        """启用/禁用启动项。**不删除**，只做移动或改名，可还原。"""
        from .core import tools
        ok, msg = tools.set_startup_enabled(str(item_id), bool(enabled))
        return {"ok": ok, "message": msg}

    @_guard
    def hardware(self) -> dict:
        """CPU / 内存条 / 显卡 / 主板 / 系统。只读。"""
        from .core import tools
        return {"ok": True, **tools.hardware_info()}

    @_guard
    def disk_health(self) -> dict:
        """物理磁盘状态 + 分区占用 + SMART 失败预测。只读。"""
        from .core import tools
        d = tools.disk_health()
        d["admin"] = elevation.is_admin()
        return {"ok": True, **d}

    @_guard
    def tools_roots(self) -> dict:
        """可选的扫描根目录。"""
        from .core import tools
        return {"ok": True, "roots": tools.default_roots()}

    @_guard
    def start_large_files(self, roots=None, min_mb: float = 200,
                          limit: int = 300) -> dict:
        """找大文件。**只列出来，不删除任何东西。**

        传进来的 roots 一律先用 tools_roots() 过滤一遍再信 ——
        界面同样不可信，不能让前端指定任意路径。
        """
        from .core import tools
        safe = _sanitize_roots(roots)
        if not safe:
            return {"ok": False, "error": "没有可扫描的磁盘"}
        jid = self.jobs.start(
            "large", f"查找 {min_mb:.0f} MB 以上的文件",
            lambda job: _large_files_worker(job, safe, min_mb, limit))
        return {"ok": True, "job_id": jid}

    @_guard
    def start_duplicates(self, roots=None, min_mb: float = 1,
                         limit: int = 200) -> dict:
        """找重复文件。**只列出来，不删除任何东西。**"""
        from .core import tools
        safe = _sanitize_roots(roots)
        if not safe:
            return {"ok": False, "error": "没有可扫描的磁盘"}
        jid = self.jobs.start(
            "dup", f"查找重复文件（≥{min_mb:.0f} MB）",
            lambda job: _dup_worker(job, safe, min_mb, limit))
        return {"ok": True, "job_id": jid}

    # ==================================================== 配置
    @_guard
    def load_config(self) -> dict:
        """读取界面配置（选中的规则、窗口设置等）。"""
        cfg = junk.load_config() or {}
        return {"ok": True, "config": cfg}

    @_guard
    def save_config(self, cfg: dict) -> dict:
        """写入界面配置。提权重启前必须调用它，否则状态会丢。"""
        if not isinstance(cfg, dict):
            return {"ok": False, "error": "配置必须是对象"}
        junk.save_config(cfg)
        return {"ok": True}

    # ==================================================== 任务
    @_guard
    def poll(self, job_id: str, since: int = 0) -> dict:
        """取任务快照。since 传上次拿到的 log_total，只回增量日志。"""
        return self.jobs.poll(job_id, since)

    @_guard
    def cancel(self, job_id: str) -> dict:
        """请求取消任务。核心会在安全点停手。"""
        return self.jobs.cancel(job_id)

    @_guard
    def running_jobs(self) -> dict:
        """当前在跑的任务列表。"""
        return {"ok": True, "jobs": [j["id"] for j in self.jobs.running()]}

    @_guard
    def start_diag(self) -> dict:
        """启动「环境自检」后台任务：摸清这台机器上的实际情况。

        这是 M2 用来验证「线程 + 进度 + 轮询 + 结果回传」整条链路的真实任务，
        不是玩具 —— 它的输出对后续排查问题有实际用处。
        """
        jid = self.jobs.start("diag", "环境自检", _diag_worker)
        return {"ok": True, "job_id": jid}

    # ==================================================== 杂项
    @_guard
    def open_in_explorer(self, path: str) -> dict:
        """在资源管理器里定位一个路径。只读操作，不删任何东西。"""
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return {"ok": False, "error": "路径不存在"}
        os.startfile(path)                                  # noqa: S606
        return {"ok": True}


# ------------------------------------------------------------------ 动作辅助
def _as_pids(pids) -> list[int]:
    """把前端传来的 PID 列表转成干净的正整数列表。"""
    out = []
    for p in (pids or []):
        try:
            n = int(p)
        except (TypeError, ValueError):
            continue
        if n > 4:                      # 0/4 是系统空闲与 System，永远不碰
            out.append(n)
    return out


def _resolve(pids: list[int]) -> list[dict]:
    """把 PID 还原成进程记录。找不到的（已退出）自然就丢了。"""
    wanted = set(pids)
    return [p for p in (mem.collect_processes() or [])
            if p.get("pid") in wanted]


def _logger(job):
    """让核心的日志同时驱动「日志面板」和「单行进度」。"""
    def log(msg):
        text = str(msg)
        job.log(text)
        stripped = text.strip()
        if stripped:
            job.set_progress(stripped[:90])
    return log


def _delta(before: dict, after: dict) -> dict:
    """系统层面的可用内存变化。

    注意与「工作集释放量」的区别：工作集被换出后，那些页进了待机/已修改列表，
    Windows 的 available 计数器不会等量增加。所以两个数字本来就不同，
    界面上要分别展示，不能混为一谈。
    键名统一用 avail_delta，避免和动作自己的 freed 撞名（撞过一次，见 ws_freed）。
    """
    b, a = before.get("avail", 0) or 0, after.get("avail", 0) or 0
    return {
        "before_avail": b,
        "after_avail": a,
        "avail_delta": a - b,
        "before_percent": before.get("percent", 0),
        "after_percent": after.get("percent", 0),
    }


def _trim_worker(job, pids: list[int]) -> dict:
    procs = _resolve(pids)
    if not procs:
        job.log("选中的进程都已经退出了")
        return {"trimmed": 0, "ws_freed": 0, "skipped": len(pids)}
    before = mem.get_memory_status()
    job.log(f"准备整理 {len(procs)} 个进程的工作集…")
    opt = mem.Optimizer(_logger(job))
    count, freed = opt.trim_all(procs)
    after = mem.get_memory_status()
    # ws_freed = 从进程工作集里换出的量（动作的直接效果）
    # avail_delta = 系统可用内存的实际变化（通常小于前者，见 _delta 注释）
    res = {"trimmed": count, "ws_freed": freed, "skipped": len(procs) - count}
    res.update(_delta(before, after))
    job.log(f"完成：整理 {count} 个进程，工作集释放 {freed / 1048576:.0f} MB"
            f"（系统可用内存 {res['avail_delta'] / 1048576:+.0f} MB）")
    return res


def _close_worker(job, pids: list[int], graceful: bool) -> dict:
    procs = _resolve(pids)
    if not procs:
        job.log("选中的进程都已经退出了")
        return {"closed": 0, "failed": 0}
    before = mem.get_memory_status()
    opt = mem.Optimizer(_logger(job))
    closed, failed = opt.close_processes(procs, graceful=graceful)
    after = mem.get_memory_status()
    res = {"closed": closed, "failed": failed}
    res.update(_delta(before, after))
    job.log(f"完成：关闭 {closed} 个，失败 {failed} 个")
    return res


def _boost_worker(job, opts: dict) -> dict:
    before = mem.get_memory_status()
    procs = mem.collect_processes() or []
    job.log(f"扫描到 {len(procs)} 个进程")
    opt = mem.Optimizer(_logger(job))
    opt.run_full(procs, opts)
    after = mem.get_memory_status()
    res = {"opts": opts}
    res.update(_delta(before, after))
    return res


def _relaunch_worker(job) -> dict:
    opt = mem.Optimizer(_logger(job))
    opt.relaunch_closed()
    return {"ok": True}


def _revert_worker(job) -> dict:
    opt = mem.Optimizer(_logger(job))
    opt.revert_system()
    return {"ok": True}


def _reload_third_party_rules() -> int:
    """更新规则后让它**立刻生效**，不用重启程序。

    做法：把已注册的三条第三方规则从 RULES 里摘掉，重置加载标记，
    再调一次注册。`_load_rules_module()` 每次都会重新执行
    config/ 下那份文件，所以拿到的就是新规则。
    """
    keys = {"third_party_apps", "third_party_caution", "third_party_logs"}
    junk.RULES[:] = [r for r in junk.RULES if r.get("key") not in keys]
    junk._THIRD_PARTY_LOADED = False
    return junk.register_third_party_rule()


def _rule_update_worker(job, offline: bool) -> dict:
    """后台任务：下载 → 生成 → 写到可写目录 → 立即生效。"""
    from .core import rule_update
    from .paths import config_dir

    target = os.path.join(config_dir(), "third_party_rules.py")
    job.log(f"目标文件 {target}")
    job.log("说明：更新写在可写目录里，**内置规则不受影响**；")
    job.log("      加载时优先用这份，删掉它就退回内置版本。")
    if offline:
        job.log("离线模式：只用本地缓存")
    else:
        job.log("联网获取中，首次可能要几十秒…")

    job.set_progress("正在获取规则…")
    try:
        stats = rule_update.update(
            target, offline=offline,
            log=lambda m: job.log("  " + m))
    except rule_update.RateLimited as e:
        job.log(f"!! {e}")
        return {"ok": False, "error": str(e)}
    except Exception as e:                                  # noqa: BLE001
        job.log(f"!! 更新失败：{e}")
        return {"ok": False, "error": str(e)}

    job.set_progress("正在应用新规则…")
    total = _reload_third_party_rules()
    job.log(f"已生效：本机命中 {total} 个目录")

    counts = {"safe": 0, "caution": 0, "files": 0}
    for key, bucket in (("third_party_apps", "safe"),
                        ("third_party_caution", "caution"),
                        ("third_party_logs", "files")):
        r = next((x for x in junk.RULES if x.get("key") == key), None)
        if r is not None:
            counts[bucket] = len(junk.expand_paths(r))
    job.log(f"分档：缓存 {counts['safe']} / 谨慎 {counts['caution']}"
            f" / 按模式 {counts['files']}")

    return {
        "safe": stats["safe"], "caution": stats["caution"],
        "files": stats["files"], "size": stats["size"],
        "matched": counts, "matched_total": total,
        "versions": stats.get("provenance", {}),
    }


def _sanitize_roots(roots) -> list[str]:
    """只保留「确实是本机固定磁盘根目录」的项。

    界面传进来的东西一律不可信：不能让前端指定任意路径去遍历
    （哪怕只是读，也没必要给它这个能力）。所以拿 tools 自己的探测结果
    做白名单，只认完全匹配的盘符根。
    """
    from .core import tools
    allowed = {r.lower() for r in tools.default_roots()}
    if not roots:
        return sorted(r.upper() for r in allowed)
    out = []
    for r in roots:
        s = str(r).strip().lower()
        if not s:
            continue
        if not s.endswith("\\"):
            s += "\\"
        if s in allowed:
            out.append(s.upper())
    return out or sorted(r.upper() for r in allowed)


def _large_files_worker(job, roots, min_mb, limit) -> dict:
    from .core import tools
    job.log(f"扫描范围：{'、'.join(roots)}")
    job.log(f"阈值：{min_mb:.0f} MB —— 只列出，不会删除任何文件")
    r = tools.find_large_files(
        roots, min_mb=min_mb, limit=limit, cancel=job.cancel,
        progress=lambda m: job.log(m))
    job.log(f"完成：{r['count']} 个文件，合计 {r['total'] / 1048576:.1f} MB")
    if r["truncated"]:
        job.log(f"（只显示最大的 {limit} 个）")
    return {"files": r["files"], "count": r["count"], "total": r["total"],
            "truncated": r["truncated"], "roots": roots,
            "min_mb": r["min_mb"]}


def _dup_worker(job, roots, min_mb, limit) -> dict:
    from .core import tools
    job.log(f"扫描范围：{'、'.join(roots)}")
    job.log("先按大小分组，再对同尺寸的算哈希 —— 不会一上来就全盘哈希")
    job.log("只列出，不会删除任何文件")
    r = tools.find_duplicates(
        roots, min_mb=min_mb, limit=limit, cancel=job.cancel,
        progress=lambda m: job.log(m))
    job.log(f"完成：{r['group_count']} 组重复，"
            f"可省 {r['wasted'] / 1048576:.1f} MB")
    if r["truncated"]:
        job.log(f"（只显示最占空间的 {limit} 组）")
    return {"groups": r["groups"], "group_count": r["group_count"],
            "wasted": r["wasted"], "truncated": r["truncated"],
            "roots": roots, "min_mb": r["min_mb"]}


def _apply_saved_worker(job) -> dict:
    cfg = mem.load_config() or {}
    m = {str(k).lower(): v for k, v in (cfg.get("priority_map") or {}).items()}
    if not m:
        job.log("还没有记住任何优先级")
        return {"applied": 0, "failed": 0, "not_running": []}
    job.log(f"记住的优先级有 {len(m)} 条")
    applied, failed = [], []
    for p in (mem.collect_processes() or []):
        exe = (p.get("name") or "").lower()
        level = m.get(exe)
        if not level:
            continue
        ok, msg = mem.set_priority(p["pid"], mem.norm_priority(level))
        label = f"{p['name']} (PID {p['pid']}) → {level}"
        if ok:
            applied.append(label)
            job.log("  [成功] " + label)
        else:
            failed.append(f"{label}：{msg}")
            job.log("  [失败] " + label + f" — {msg}")
    return {"applied": len(applied), "failed": len(failed)}


# 深度优化各项是否需要管理员。
# 这是**实测**结果：在普通权限下把 7 项逐个调用一遍记录下来，不是猜的。
_DEEP_NEEDS_ADMIN = {
    "empty_working_sets": True,
    "purge_standby": True,
    "purge_low_standby": True,
    "flush_modified": False,
    "file_cache": True,
    "registry": False,
    "combine": True,
}

# 需要特别提醒的项。放在这里而不是核心，是因为核心的说明是给日志看的，
# 这里要的是**界面上能一眼看到的风险**。
_DEEP_WARN = {
    "empty_working_sets":
        "它不区分进程：受保护程序与反作弊的工作集也会被清。"
        "如果正在游戏、或反作弊已启动，建议改用「整理内存」——"
        "那条路径是逐进程的，会跳过受保护与反作弊进程。",
    "combine":
        "收益中等，但极少数老驱动 / 虚拟化环境下兼容性较差，默认不勾选。",
    "flush_modified": "会产生一次磁盘写入。",
}


def _deep_worker(job, opts: dict) -> dict:
    before = mem.get_memory_status()
    job.log("深度优化直接调用内核接口，逐项执行。")
    if not elevation.is_admin():
        job.log("当前不是管理员：待机列表 / 工作集 / 文件缓存这几项会失败，"
                "属预期情况，不是程序出错。")
    res = mem.run_deep_optimize(opts, _logger(job))
    after = mem.get_memory_status()
    out = {"ok_count": res.get("ok", 0),
           "selected": sum(1 for v in opts.values() if v)}
    out.update(_delta(before, after))
    return out


# ------------------------------------------------------------------ 垃圾清理辅助
def _as_keys(keys) -> list[str]:
    """把前端传来的规则 key 列表转成干净字符串列表。"""
    out = []
    for k in (keys or []):
        s = str(k or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def _rule_by_key(key: str):
    return next((r for r in junk.RULES if r.get("key") == key), None)


def _rules_by_keys(keys: list[str]) -> list[dict]:
    """按 RULES 的原顺序取规则，保证扫描/清理顺序稳定且可预期。"""
    wanted = set(keys)
    return [r for r in junk.RULES if r.get("key") in wanted]


def _throttle(fn, interval: float = 0.2):
    """节流。

    深扫时核心的 progress 回调会以极高频触发（每 400 个文件一次），
    直接透传到界面会把 UI 刷爆，也会让轮询日志失去意义。
    这里限制成最快 interval 秒一次 —— 进度看起来是连续的，但不会淹没。
    """
    last = [0.0]

    def wrapped(value):
        now = time.time()
        if now - last[0] >= interval:
            last[0] = now
            try:
                fn(value)
            except Exception:                               # noqa: BLE001
                pass
    return wrapped


def _scan_worker(job, keys: list[str]) -> dict:
    rules = _rules_by_keys(keys)
    if not rules:
        job.log("没有匹配的规则")
        return {"rules": [], "total": 0, "files": 0}

    results = []
    total = files = 0
    n = len(rules)
    job.log(f"开始扫描 {n} 条规则…")

    for i, rule in enumerate(rules, 1):
        if job.cancel.is_set():
            job.log("已取消")
            break
        job.set_progress(f"[{i}/{n}] {rule['name']}")
        try:
            rep = junk.scan_rule(rule, job.cancel,
                                 progress=_throttle(job.set_progress))
        except Exception as e:                              # noqa: BLE001
            job.log(f"[{i}/{n}] {rule['name']} — 扫描失败：{e}")
            continue

        results.append({
            "key": rep.get("key"), "name": rep.get("name"),
            "level": rule["level"], "kind": rule["kind"],
            "size": rep.get("size", 0), "files": rep.get("files", 0),
            "dirs": rep.get("dirs", 0), "denied": rep.get("denied", 0),
            "exists": rep.get("exists", False),
        })
        total += rep.get("size", 0)
        files += rep.get("files", 0)
        if rep.get("size", 0) > 0:
            job.log(f"[{i}/{n}] {rule['name']}: "
                    f"{rep['size'] / 1048576:.1f} MB / {rep.get('files', 0)} 文件")
        else:
            job.log(f"[{i}/{n}] {rule['name']}: 未发现可清理项")

    job.log(f"扫描完成：合计 {total / 1048576:.1f} MB / {files} 个文件")
    return {"rules": results, "total": total, "files": files,
            "count": len(results)}


def _clean_worker(job, keys: list[str]) -> dict:
    rules = _rules_by_keys(keys)
    if not rules:
        job.log("没有匹配的规则")
        return {"freed": 0, "deleted": 0, "failed": []}

    before = junk.disk_free(junk.SYSTEM_ROOT_DIR) if junk.SYSTEM_ROOT_DIR else 0
    job.log(f"开始清理 {len(rules)} 条规则…")
    job.log("说明：占用中的文件会被跳过（不做强制删除）；"
            "符号链接与目录联接一律不跟随。")

    rep = junk.clean_rules(rules, job.cancel, log=job.log)
    after = junk.disk_free(junk.SYSTEM_ROOT_DIR) if junk.SYSTEM_ROOT_DIR else 0

    failed = rep.get("failed") or []
    job.log(f"清理完成：释放 {rep.get('freed', 0) / 1048576:.1f} MB，"
            f"删除 {rep.get('deleted', 0)} 项，跳过 {len(failed)} 项")
    return {
        "freed": rep.get("freed", 0),
        "deleted": rep.get("deleted", 0),
        "failed": [[p, why] for p, why in failed[:50]],
        "failed_count": len(failed),
        "disk_free_delta": max(0, (after or 0) - (before or 0)),
        "rules": [{"key": r.get("key"), "freed": r.get("freed", 0),
                   "deleted": r.get("deleted", 0),
                   "skipped": r.get("skipped", 0)}
                  for r in (rep.get("rules") or [])],
    }


def _recycle_worker(job) -> dict:
    info = junk.recycle_bin_info()
    job.log(f"回收站当前 {info.get('items', 0)} 项，"
            f"{info.get('size', 0) / 1048576:.1f} MB")
    if not info.get("items"):
        job.log("回收站已经是空的")
        return {"emptied": False, "items": 0, "freed": 0}
    job.set_progress("正在清空回收站…")
    ok, msg = junk.empty_recycle_bin()
    job.log(msg)
    return {"emptied": bool(ok), "items": info.get("items", 0),
            "freed": info.get("size", 0), "message": msg}


def _dism_worker(job, reset_base: bool) -> dict:
    job.log("DISM 组件清理会移除 WinSxS 中被取代的旧组件。")
    job.log("这一步耗时可能十几分钟，期间可以取消。")
    job.set_progress("正在执行 DISM…")
    ok, msg = junk.dism_component_cleanup(reset_base=reset_base)
    job.log(msg)
    return {"ok": bool(ok), "message": msg}


def _third_party_count() -> dict:
    """第三方规则库里本机真实命中的目录数（模板数没有意义，命中数才有）。"""
    out = {"safe": 0, "caution": 0, "files": 0}
    for key, bucket in (("third_party_apps", "safe"),
                        ("third_party_caution", "caution"),
                        ("third_party_logs", "files")):
        rule = next((r for r in junk.RULES if r["key"] == key), None)
        if rule is not None:
            try:
                out[bucket] = len(junk.expand_paths(rule))
            except Exception:                               # noqa: BLE001
                pass
    return out


def _diag_worker(job) -> dict:
    """环境自检的实际工作。每一步都报进度，方便看轮询是否真的在动。"""
    facts = {}
    steps = [
        ("读取内存状态", lambda: mem.get_memory_status()),
        ("枚举固定磁盘", lambda: junk.fixed_drives()),
        ("探测 Steam 库", lambda: junk.steam_libraries()),
        ("读取回收站", lambda: junk.recycle_bin_info()),
        ("统计本机进程", lambda: mem.collect_processes()),
        ("解析第三方规则", lambda: _third_party_count()),
    ]

    for i, (name, fn) in enumerate(steps):
        if job.cancel.is_set():
            job.log("已取消")
            return {"cancelled": True, "facts": facts}
        job.set_progress(name)
        job.log(f"[{i + 1}/{len(steps)}] {name}")
        try:
            facts[name] = fn()
        except Exception as e:                              # noqa: BLE001
            facts[name] = f"失败: {type(e).__name__}: {e}"
            job.log(f"    !! {e}")

    st = facts.get("读取内存状态") or {}
    disks = facts.get("枚举固定磁盘") or []
    procs = facts.get("统计本机进程") or []
    tp = facts.get("解析第三方规则") or {}

    job.log("—" * 30)
    job.log(f"内存      {(st.get('total') or 0) / 2**30:.2f} GB"
            f"（可用 {(st.get('avail') or 0) / 2**30:.2f} GB）")
    job.log(f"磁盘      {len(disks)} 个：{'、'.join(disks)}")
    job.log(f"进程      {len(procs)} 个")
    job.log(f"规则      {len(junk.RULES)} 条")
    job.log(f"社区规则  缓存 {tp.get('safe', 0)} / 谨慎 {tp.get('caution', 0)}"
            f" / 按模式 {tp.get('files', 0)} 个目录")
    job.log(f"权限      {'管理员' if elevation.is_admin() else '普通用户'}")

    return {
        "cancelled": False,
        "mem_total": st.get("total", 0),
        "mem_avail": st.get("avail", 0),
        "disks": disks,
        "processes": len(procs),
        "rules": len(junk.RULES),
        "third_party": tp,
        "admin": elevation.is_admin(),
        "finished_at": time.strftime("%H:%M:%S"),
    }
