# -*- coding: utf-8 -*-
"""MultronWcleaner 解析器夹具。

底账（子代理实测 5132 条）：true 2812 / false 2320，标 false 的正是
pagefile.sys、系统还原点、Windows.old、ESD 这些绝不该默认删的。
所以这里重点验「false 的一律不要」「系统路径一律不要」「隐私一律不要」。
"""
import os
import sys
from collections import Counter

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SRC)
from app.core import rule_update as ru   # noqa: E402

DB = r"""{=Windows
LocalTemp=C:\Users\{##}\AppData\Local\Temp=true
Prefetch=C:\Windows\Prefetch=false
SystemPagefile=C:\pagefile.sys=true
WindowsOld=C:\Windows.old=true
WindowsRestorePoints=C:\System Volume Information=true
WindowsEventLogs=C:\Windows\System32\winevt\Logs=true
}
{=Chrome
ChromeCache=C:\Users\{##}\AppData\Local\Google\Chrome\User Data\Default\Cache=true
ChromeCodeCache=C:\Users\{##}\AppData\Local\Google\Chrome\User Data\Default\Code Cache=true
ChromeCookies=C:\Users\{##}\AppData\Local\Google\Chrome\User Data\Default\Cookies=true
ChromeHistory=C:\Users\{##}\AppData\Local\Google\Chrome\User Data\Default\History=true
}
{=Thunderbird
#profile#=C:\Users\{##}\AppData\Local\Thunderbird\Profiles\=true
ThunderbirdProfileCache=#profileget#=\cache2=true
ThunderbirdMailData=#profileget#=\Mail\Local Folders=true
}
{=NotCache
Downloads=C:\Users\{##}\Downloads=true
Recent=C:\Users\{##}\AppData\Roaming\Microsoft\Windows\Recent=true
ProgramFilesThing=C:\Program Files\SomeApp\Cache=true
}
"""

counters = Counter()
caution = {}
ru.parse_multron(DB, counters, caution)

print("=" * 70)
print("MultronWcleaner 解析结果")
print("=" * 70)
for k in sorted(caution):
    print(f"  收录  {k}")
print()
print("  计数：")
for k, v in counters.most_common():
    print(f"    {k:<28} {v}")

print()
print("=" * 70)
print("断言")
print("=" * 70)
fail = 0
def check(label, got, want):
    global fail
    ok = got == want
    if not ok:
        fail += 1
    print(f"  [{'ok' if ok else '!!'}] {label}: {got!r}"
          + ("" if ok else f"  (期望 {want!r})"))

WANT = {
    r"{PROFILE}\AppData\Local\Temp",
    r"{PROFILE}\AppData\Local\Google\Chrome\User Data\Default\Cache",
    r"{PROFILE}\AppData\Local\Google\Chrome\User Data\Default\Code Cache",
    r"{PROFILE}\AppData\Local\Thunderbird\Profiles\*\cache2",
}
check("收录的模板集合", set(caution), WANT)
check("收录数量", len(caution), 4)
check("条目总数", counters["Multron 条目总数"], 15)
check("上游标 false 的全部丢弃",
      counters["Multron 上游标为不推荐(丢弃)"], 1)
check("系统路径（非用户根）不进", counters["Multron 路径不合格(丢弃)"], 5)
check("隐私条目跳过（Cookies/History/Recent）",
      counters["Multron 隐私条目(跳过)"], 3)
check("非缓存类丢弃", counters["Multron 不是缓存类(丢弃)"], 2)
check("疑似文件丢弃", counters["Multron 疑似文件(丢弃)"], 0)
check("收录计数与集合一致", counters["Multron 收录(谨慎档)"], len(caution))
check("四类丢弃 + 收录 = 条目总数",
      counters["Multron 上游标为不推荐(丢弃)"]
      + counters["Multron 路径不合格(丢弃)"]
      + counters["Multron 隐私条目(跳过)"]
      + counters["Multron 不是缓存类(丢弃)"]
      + counters["Multron 疑似文件(丢弃)"]
      + counters["Multron 收录(谨慎档)"],
      counters["Multron 条目总数"])

print()
print("  逐个重点路径：")
for bad in (r"C:\pagefile.sys", r"C:\Windows.old",
            r"C:\System Volume Information",
            r"C:\Windows\System32\winevt\Logs",
            r"C:\Program Files\SomeApp\Cache"):
    t = ru.multron_to_template(bad)
    ok = t is None
    if not ok:
        fail += 1
    print(f"    [{'ok' if ok else '!!'}] 拒绝 {bad}  -> {t!r}")

for good, want in ((r"C:\Users\{##}\AppData\Local\Temp",
                    r"{PROFILE}\AppData\Local\Temp"),
                   (r"C:\ProgramData\SomeApp\Cache",
                    r"{PROGRAMDATA}\SomeApp\Cache"),
                   (r"C:\Users\Public\Documents\Cache",
                    r"{PUBLIC}\Documents\Cache")):
    t = ru.multron_to_template(good)
    ok = t == want
    if not ok:
        fail += 1
    print(f"    [{'ok' if ok else '!!'}] 接受 {good}  -> {t!r}")

print()
print("全部通过" if fail == 0 else f"{fail} 项失败")
sys.exit(1 if fail else 0)
