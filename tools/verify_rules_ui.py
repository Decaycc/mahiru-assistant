# -*- coding: utf-8 -*-
"""验证「清理规则库」这一块的界面接线：

  1. rules_info   读的是**正在用的那份文件**的头部，不是永远读内置的
  2. rules_info   能把来源解析成结构（名字 / URL / 版本 / 条数 / 许可）
  3. rules_info   给出生成时间、文件大小、路径
  4. reset_rules  真的把更新版挪走、退回内置版，并且**不删除**更新版
  5. reset_rules  在本来就是内置版时明确报错，而不是假装成功
  6. start_rule_update 的 refresh 一路透传到 rule_update.update()

全程把 config_dir 指向临时目录，**不碰用户真实配置**。
直接跑：python tools\\verify_rules_ui.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [XX] ") + name
          + (("   —— " + str(detail)) if detail and not cond else ""))


# 假冒的「更新版」规则文件：头部来源与内置版明显不同，
# 这样才能证明 rules_info 读的是它、而不是内置那份。
FAKE_OVERRIDE = '''# -*- coding: utf-8 -*-
"""第三方清理规则库衍生数据
（由软件里的「更新规则」按钮或 tools/update_rules.py 自动生成，勿手改）

来源与许可：
  * testsrc    https://example.invalid/testsrc
              版本 999 / 7 条 / TEST-LIC-1.0
  * othersrc   https://example.invalid/other
              版本 111 / 3 条 / MIT

生成时间：2020-01-02 03:04:05

四档：
  THIRD_PARTY_SAFE_DIRS          纯缓存，删了自动重建
"""
THIRD_PARTY_SAFE_DIRS = []
THIRD_PARTY_CAUTION_DIRS = []
THIRD_PARTY_FILE_RULES = []
THIRD_PARTY_CAUTION_FILE_RULES = []
'''


class FakeJob:
    """够用的 Job 替身：worker 只会调 log / set_progress。"""

    def __init__(self):
        self.lines = []

    def log(self, m):
        self.lines.append(str(m))

    def set_progress(self, p):
        self.lines.append("progress: " + str(p))


class FakeJobs:
    """同步执行的任务队列替身。

    真的 Jobs 会开后台线程，验证参数透传时还得轮询；
    这里直接跑完，`start` 收到的 fn 就是被测的那个 worker。
    """

    def __init__(self):
        self.calls = []

    def start(self, kind, label, fn):
        self.calls.append((kind, label))
        self.last = (kind, label, fn)
        fn(FakeJob())
        return "fake-job-1"


def make_api(jobs=None):
    from app.bridge import Api
    return Api(jobs)


def main():
    import app.paths as paths
    from app import bridge

    tmp = tempfile.mkdtemp(prefix="mahiru_rules_")
    paths.config_dir = lambda: tmp          # 全程只写临时目录
    target = os.path.join(tmp, "third_party_rules.py")

    api = make_api()

    print("\n=== 1. 没有更新版时，读内置那份 ===")
    d = api.rules_info()
    check("ok", d.get("ok") is True)
    check("using_override=False", d["using_override"] is False, d["using_override"])
    check("文件指向 app/core/third_party_rules.py",
          d["file"]["path"].replace("\\", "/").endswith(
              "app/core/third_party_rules.py"), d["file"]["path"])
    check("大小 > 100 KB", d["file"]["size"] > 100000, d["file"]["size"])
    check("有生成时间", bool(d["file"]["generated_at"]), d["file"]["generated_at"])
    check("至少 4 个来源", len(d["sources"]) >= 4, len(d["sources"]))
    check("每个来源都解析出了 url/版本/条数/许可",
          all(s["url"].startswith("http") and s["version"] and s["entries"]
              and s["license"] for s in d["sources"]),
          d["sources"])
    builtin_total = d["matched_total"]
    check("内置版本机有命中", builtin_total > 0, builtin_total)

    print("\n=== 2. 有更新版时，读的是更新版自己的头部 ===")
    with open(target, "w", encoding="utf-8", newline="\n") as f:
        f.write(FAKE_OVERRIDE)
    # 真实流程里，规则文件是在**启动时**被载入的；更新走 _reload_third_party_rules()。
    # 这里写完文件必须显式重载一次，否则 junk.RULES 里还是启动时那份内置规则。
    bridge._reload_third_party_rules()
    d = api.rules_info()
    check("using_override=True", d["using_override"] is True)
    names = [s["name"] for s in d["sources"]]
    check("来源来自假冒文件（testsrc/othersrc），不是内置的",
          names == ["testsrc", "othersrc"], names)
    check("版本解析正确", d["sources"][0]["version"] == "999",
          d["sources"][0])
    check("条数解析正确", d["sources"][0]["entries"] == "7", d["sources"][0])
    check("许可解析正确", d["sources"][0]["license"] == "TEST-LIC-1.0",
          d["sources"][0])
    check("生成时间来自假冒文件",
          d["file"]["generated_at"] == "2020-01-02 03:04:05",
          d["file"]["generated_at"])
    check("文件路径指向临时目录",
          os.path.normcase(d["file"]["path"]) == os.path.normcase(target),
          d["file"]["path"])
    check("空规则 → 本机命中 0", d["matched_total"] == 0, d["matched_total"])

    print("\n=== 3. reset_rules 退回内置，但不删除更新版 ===")
    r = api.reset_rules()
    check("ok", r.get("ok") is True, r)
    check("更新版已不在原位", not os.path.exists(target))
    kept = target + ".removed"
    check("更新版被挪到 .removed", os.path.exists(kept))
    if os.path.exists(kept):
        with open(kept, encoding="utf-8") as f:
            check("内容一字未丢", f.read() == FAKE_OVERRIDE)
    d = api.rules_info()
    check("已经切回内置版", d["using_override"] is False)
    check("命中数回到内置版的水平", d["matched_total"] == builtin_total,
          (d["matched_total"], builtin_total))
    check("reset 返回的命中数与之一致", r["matched_total"] == builtin_total,
          (r["matched_total"], builtin_total))

    print("\n=== 4. 本来就是内置版时，reset 明确失败 ===")
    r2 = api.reset_rules()
    check("ok=False", r2.get("ok") is False, r2)
    check("错误说清了原因", "内置" in str(r2.get("error", "")), r2)

    print("\n=== 5. refresh 一路透传到 rule_update.update() ===")
    seen = {}
    jobs = FakeJobs()
    api5 = make_api(jobs)

    # start_rule_update 只是把 worker 塞进任务队列；换掉 worker 看参数
    orig_worker = bridge._rule_update_worker
    bridge._rule_update_worker = lambda job, offline, refresh=False: seen.update(
        {"offline": offline, "refresh": refresh}) or {"ok": True}
    try:
        api5.start_rule_update(offline=False, refresh=True)
    finally:
        bridge._rule_update_worker = orig_worker
    check("start_rule_update(refresh=True) 把 refresh=True 传给了 worker",
          seen.get("refresh") is True, seen)
    check("offline 仍是 False", seen.get("offline") is False, seen)
    check("任务标签说明了是强制重下",
          "强制重下" in jobs.calls[-1][1], jobs.calls[-1][1])

    seen2 = {}
    jobs2 = FakeJobs()
    api6 = make_api(jobs2)
    bridge._rule_update_worker = lambda job, offline, refresh=False: seen2.update(
        {"refresh": refresh}) or {"ok": True}
    try:
        api6.start_rule_update(offline=True)
    finally:
        bridge._rule_update_worker = orig_worker
    check("不传 refresh 时默认 False（仍然吃缓存）",
          seen2.get("refresh") is False, seen2)

    print("\n=== 6. worker 把 refresh 传给 rule_update.update() ===")
    from app.core import rule_update
    got = {}

    def fake_update(path, **kw):
        got.update(kw)
        got["path"] = path
        return {"safe": 999, "caution": 0, "files": 0, "caution_files": 0,
                "size": 1234, "provenance": {}}

    orig_update = rule_update.update
    orig_reload = bridge._reload_third_party_rules
    rule_update.update = fake_update
    bridge._reload_third_party_rules = lambda: 123
    try:
        # 这里传的是**真实** worker，验证它怎么转手
        res = orig_worker(FakeJob(), False, True)
    finally:
        rule_update.update = orig_update
        bridge._reload_third_party_rules = orig_reload
    check("update() 收到 refresh=True", got.get("refresh") is True, got)
    check("update() 收到 offline=False", got.get("offline") is False, got)
    check("worker 返回 ok", res.get("ok") is True, res)
    check("worker 报出了新的命中数", res.get("matched_total") == 123, res)
    check("worker 报出了文件大小", res.get("size") == 1234, res)

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for n in FAIL:
            print("  失败：" + n)
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
