# -*- coding: utf-8 -*-
"""后台任务调度。

为什么需要它：垃圾扫描要遍历几万个文件、DISM 要跑几分钟。这些都不能在
UI 线程里做，否则窗口直接假死。所以统一走「工作线程 + 轮询」：

    前端  start_xxx()  ──▶  立刻拿到 job_id，界面不卡
    前端  poll(job_id) ──▶  每 200ms 取一次进度 / 日志 / 最终结果

**为什么用轮询而不是跨线程 evaluate_js**：pywebview 的 evaluate_js 在非 UI
线程调用行为不稳定（要切回主线程），而且前端无法感知丢失的事件。轮询是有状态
的、可重入的，前端刷新后还能接着拿，简单可靠。
"""
import threading
import time
import traceback
from collections import deque

# 单次保留的日志行数：够看就行，避免长时间任务把内存吃光
LOG_TAIL = 300


class Job:
    """一个后台任务的状态容器。工作线程与轮询线程都会读它，故加锁。"""

    def __init__(self, jid: str, kind: str, label: str):
        self.id = jid
        self.kind = kind
        self.label = label
        self.cancel = threading.Event()
        self.state = "running"          # running | done | error | cancelled
        self.progress = ""              # 当前正在处理的路径
        self.message = ""               # 最近一条日志（给单行状态用）
        self.result = None
        self.error = None
        self.started = time.time()
        self.finished = None
        self._logs = deque(maxlen=LOG_TAIL)
        self._lock = threading.Lock()

    # ---------------------------------------------------------- 工作线程调用
    def log(self, text: str) -> None:
        text = str(text)
        with self._lock:
            self._logs.append(text)
            self.message = text

    def set_progress(self, text: str) -> None:
        with self._lock:
            self.progress = str(text)

    def set_result(self, value) -> None:
        with self._lock:
            self.result = value

    # ---------------------------------------------------------- 轮询线程调用
    def snapshot(self, since: int = 0) -> dict:
        """返回状态快照。since 用于只取「上次之后新增的日志」，避免重复刷屏。"""
        with self._lock:
            logs = list(self._logs)
            fresh = logs[since:] if 0 <= since <= len(logs) else logs
            return {
                "id": self.id,
                "kind": self.kind,
                "label": self.label,
                "state": self.state,
                "progress": self.progress,
                "message": self.message,
                "logs": fresh,
                "log_total": len(logs),
                "result": self.result,
                "error": self.error,
                "elapsed": round((self.finished or time.time()) - self.started, 2),
            }


class JobManager:
    """任务注册表 + 线程池（每个任务一条线程，够用且无需引入并发库）。"""

    def __init__(self, history: int = 30):
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._seq = 0
        self._history = history

    # ------------------------------------------------------------------ 启动
    def start(self, kind: str, label: str, fn) -> str:
        """在后台线程里执行 fn(job)。返回值是 job_id。"""
        with self._lock:
            self._seq += 1
            jid = f"{kind}-{self._seq}"
            job = Job(jid, kind, label)
            self._jobs[jid] = job
            self._order.append(jid)
            # 超量就丢最老的已完成任务
            while len(self._order) > self._history:
                old = self._order[0]
                if self._jobs.get(old) and self._jobs[old].state == "running":
                    break
                self._order.pop(0)
                self._jobs.pop(old, None)

        def runner():
            try:
                job.set_result(fn(job))
                with job._lock:
                    job.state = "cancelled" if job.cancel.is_set() else "done"
            except Exception as e:                       # noqa: BLE001
                with job._lock:
                    job.state = "error"
                    job.error = f"{type(e).__name__}: {e}"
                job.log("!! " + traceback.format_exc(limit=6))
            finally:
                with job._lock:
                    job.finished = time.time()

        threading.Thread(target=runner, name=f"job-{jid}", daemon=True).start()
        return jid

    # ------------------------------------------------------------------ 查询
    def poll(self, jid: str, since: int = 0) -> dict:
        job = self._jobs.get(jid)
        if job is None:
            return {"ok": False, "error": f"未知任务 {jid}"}
        snap = job.snapshot(since)
        snap["ok"] = True
        return snap

    def cancel(self, jid: str) -> dict:
        job = self._jobs.get(jid)
        if job is None:
            return {"ok": False, "error": f"未知任务 {jid}"}
        job.cancel.set()
        job.log("… 收到取消请求，正在收尾")
        return {"ok": True}

    def running(self) -> list[dict]:
        with self._lock:
            return [self._jobs[i].snapshot(10 ** 9)
                    for i in self._order
                    if self._jobs.get(i) and self._jobs[i].state == "running"]

    def busy(self) -> bool:
        return bool(self.running())
