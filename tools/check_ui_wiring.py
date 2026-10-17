# -*- coding: utf-8 -*-
"""界面接线静态检查：前端点的每个 #id 和后端方法都要真的存在。

改界面时最容易犯、又最难一眼看出来的两类错：
  1. JS 里 `UI.$('#junk-xxx')` 写了个 index.html 里不存在的 id
     → 运行到那行直接 `null.addEventListener` 崩掉，或者静默什么都不做；
  2. JS 里 `Bridge.call('xxx')` 这个方法后端根本没定义
     → 用户点了按钮只看到一句「不支持的操作」。
两类都是纯字符串，编译和冒烟都发现不了，所以单独扫一遍。

id 的来源要包括**动态生成的**（JS 模板串里 `id="..."` 也算），
否则会把 `#junk-empty-bin` 这种 innerHTML 里造出来的 id 误报成缺失。

用法：python tools/check_ui_wiring.py
退出码 0 = 干净，1 = 有缺失。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "web", "index.html")
JS_DIR = os.path.join(ROOT, "web", "js")
BRIDGE = os.path.join(ROOT, "app", "bridge.py")

# UI.$('#x') / document.getElementById('x') / querySelector('#x')
NEED_ID = re.compile(r"""(?:UI\.\$|document\.getElementById|querySelector(?:All)?)\s*\(\s*['"]#?([A-Za-z][\w-]*)['"]""")
# 任何地方定义 id 都算，包括 JS 模板串里的
DEF_ID = re.compile(r"""id\s*=\s*["']([A-Za-z][\w-]*)["']""")
CALL = re.compile(r"""Bridge\.call\(\s*['"]([A-Za-z_]\w*)['"]""")
DEF_METHOD = re.compile(r"""^\s*def\s+([A-Za-z_]\w*)\s*\(""", re.M)


def read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def js_files():
    for base, _dirs, names in os.walk(JS_DIR):
        for n in sorted(names):
            if n.endswith(".js"):
                yield os.path.join(base, n)


def main():
    if not os.path.isfile(HTML):
        print(f"找不到 {HTML}")
        return 1

    defined_ids = set(DEF_ID.findall(read(HTML)))
    js_texts = {}
    for p in js_files():
        t = read(p)
        js_texts[p] = t
        defined_ids |= set(DEF_ID.findall(t))

    bridge_text = read(BRIDGE) if os.path.isfile(BRIDGE) else ""
    # 只认缩进后紧跟的 def（Api 类的方法），连同模块级函数一起收
    defined_methods = set(DEF_METHOD.findall(bridge_text))
    # _guard 包了一层，方法名在 def 里，直接可查

    missing_ids = []
    for p, t in js_texts.items():
        rel = os.path.relpath(p, ROOT)
        for m in NEED_ID.finditer(t):
            name = m.group(1)
            # 带 # 前缀的才是 id 选择器；UI.$('.x') 那种是 class，跳过
            if "#" not in m.group(0) and not m.group(0).startswith("UI.$"):
                continue
            if "querySelector" in m.group(0) and "#" not in m.group(0):
                continue
            if name not in defined_ids:
                line = t.count("\n", 0, m.start()) + 1
                missing_ids.append((rel, line, name))

    missing_methods = []
    for p, t in js_texts.items():
        rel = os.path.relpath(p, ROOT)
        for m in CALL.finditer(t):
            name = m.group(1)
            if name not in defined_methods:
                line = t.count("\n", 0, m.start()) + 1
                missing_methods.append((rel, line, name))

    print("=" * 68)
    print("界面接线检查")
    print("=" * 68)
    print(f"  index.html 里定义了 {len(defined_ids)} 个 id")
    print(f"  bridge.py 里定义了 {len(defined_methods)} 个方法")
    print()

    bad = False
    if missing_ids:
        bad = True
        print(f"!! 前端引用了 {len(missing_ids)} 个**不存在**的 id：")
        for rel, line, name in missing_ids:
            print(f"     {rel}:{line}  #{name}")
    else:
        print("  [OK] 前端引用的每个 #id 都有定义")

    if missing_methods:
        bad = True
        print(f"!! 前端调用了 {len(missing_methods)} 个**后端没有**的方法：")
        for rel, line, name in missing_methods:
            print(f"     {rel}:{line}  Bridge.call('{name}')")
    else:
        print("  [OK] 前端调用的每个后端方法都存在")

    print()
    if bad:
        print("结果：有缺失，见上面。")
        return 1
    print("结果：接线一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
