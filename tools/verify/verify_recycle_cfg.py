# -*- coding: utf-8 -*-
"""回收站配置链路的验证：save_config 合并语义 + _clean_worker 是否透传 recycle。"""
import json
import os
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.core import junk                                    # noqa: E402
from app import bridge                                        # noqa: E402

ok_all = True


def chk(label, cond, extra=""):
    global ok_all
    print(("  [OK]   " if cond else "  [FAIL] ") + label + (("  " + extra) if extra else ""))
    if not cond:
        ok_all = False


# 用临时配置文件，绝不碰用户真实的 config/junkclean_config.json
real_cfg = junk.CONFIG_PATH
tmpdir = tempfile.mkdtemp(prefix="mahiru_cfg_")
junk.CONFIG_PATH = os.path.join(tmpdir, "cfg.json")
print(f"  （临时配置：{junk.CONFIG_PATH}）")

print()
print("=" * 68)
print("1) save_config 必须是合并，不是整份覆盖")
print("=" * 68)
junk.save_config({"selected": {"third_party_apps": True, "user_temp": True},
                  "last_log": ["a", "b"]})
cfg = junk.load_config()
chk("初始 selected 写进去了", cfg["selected"].get("third_party_apps") is True)

# 界面切换主题时只会带 theme —— 不能把 selected 抹掉
junk.save_config({"theme": "dark"})
cfg = junk.load_config()
chk("切主题后 selected 还在", bool(cfg["selected"]), str(cfg["selected"]))
chk("切主题后 last_log 还在", cfg.get("last_log") == ["a", "b"],
    str(cfg.get("last_log")))
chk("theme 也写进去了", cfg.get("theme") == "dark", str(cfg.get("theme")))

junk.save_config({"recycle_bin": True})
cfg = junk.load_config()
chk("recycle_bin 写入成功", cfg.get("recycle_bin") is True)
chk("写入 recycle_bin 后 selected 仍完好", bool(cfg["selected"]))
chk("写入 recycle_bin 后 theme 仍完好", cfg.get("theme") == "dark")

junk.save_config({"recycle_bin": False})
chk("recycle_bin 可以切回 False",
    junk.load_config().get("recycle_bin") is False)

# 默认值：配置文件里没有这个键时应当视为「直接删除」
os.remove(junk.CONFIG_PATH)
chk("干净配置里 recycle_bin 是 falsy（默认直接删除）",
    not junk.load_config().get("recycle_bin"),
    repr(junk.load_config().get("recycle_bin")))

print()
print("=" * 68)
print("2) _clean_worker 必须把配置里的 recycle 透传给 clean_rules")
print("=" * 68)


class FakeJob:
    def __init__(self):
        self.cancel = threading.Event()
        self.lines = []

    def log(self, m):
        self.lines.append(m)

    def set_progress(self, m):
        pass


STUB_RULE = {"key": "__stub__", "name": "桩规则", "kind": "contents",
             "level": "safe", "paths": [], "default": True}

captured = {}

real_rules_by_keys = bridge._rules_by_keys
real_clean_rules = junk.clean_rules
bridge._rules_by_keys = lambda keys: [STUB_RULE]


def fake_clean_rules(rules, cancel=None, log=None, recycle=False):
    captured["recycle"] = recycle
    captured["n"] = len(rules)
    if log:
        log("桩：假装清理了")
    return {"freed": 0, "deleted": 0, "failed": [], "rules": [],
            "recycled": 3, "recycled_bytes": 4096}


junk.clean_rules = fake_clean_rules
try:
    # 关（默认）
    job = FakeJob()
    res = bridge._clean_worker(job, ["__stub__"])
    chk("默认（未配置）→ recycle=False", captured.get("recycle") is False,
        str(captured))
    chk("返回体带 recycled 字段", res.get("recycled") == 3, str(res.get("recycled")))
    chk("返回体带 recycled_bytes", res.get("recycled_bytes") == 4096)
    chk("没有错误地写「移入回收站」的日志",
        not any("移入回收站" in s for s in job.lines))

    # 开
    junk.save_config({"recycle_bin": True})
    job2 = FakeJob()
    res2 = bridge._clean_worker(job2, ["__stub__"])
    chk("配置为真 → recycle=True", captured.get("recycle") is True, str(captured))
    chk("日志明确说了不释放空间",
        any("移入回收站" in s and "不会" in s for s in job2.lines),
        "\n     ".join(job2.lines))
    chk("结束日志也点出没释放空间",
        any("还没有释放" in s for s in job2.lines),
        "\n     ".join(job2.lines))

    # 关回去
    junk.save_config({"recycle_bin": False})
    job3 = FakeJob()
    bridge._clean_worker(job3, ["__stub__"])
    chk("配置为假 → recycle=False", captured.get("recycle") is False)
finally:
    bridge._rules_by_keys = real_rules_by_keys
    junk.clean_rules = real_clean_rules
    junk.CONFIG_PATH = real_cfg
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

print()
print("=" * 68)
print("3) 用户真实配置没被动过")
print("=" * 68)
if os.path.exists(real_cfg):
    with open(real_cfg, "r", encoding="utf-8") as fh:
        real = json.load(fh)
    chk("真实配置存在且可解析", isinstance(real, dict), str(sorted(real)))
else:
    print("  （本来就没有配置文件，跳过）")

print()
print("=" * 68)
print("结果：" + ("全部通过" if ok_all else "有失败项，见上面的 [FAIL]"))
print("=" * 68)
sys.exit(0 if ok_all else 1)
