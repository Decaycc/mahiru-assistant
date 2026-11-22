# -*- coding: utf-8 -*-
"""样式表的静态体检：变量、括号、编码。

为什么值得单独守：

  CSS 变量是**算不出来就整条声明作废**的 —— 不是退化成默认值，而是变成
  inherit。写错一个名字，表现是「这个按钮的圆角没了」或者「复选框勾不上
  颜色」，而浏览器、py_compile、界面接线检查**都不会说一个字**。
  本项目真踩过两次：`--dur`（从来没定义过，动画整条被丢掉）和一次
  令牌文件被 WebView2 缓存住（控件全变方角）。

  另外 `--accent`（Jazeera Orange）在这个体系里是**身份色，不是交互色**：
  只允许出现在品牌块与 eyebrow 竖条上（见 DESIGN.md 第 3 / 4 节）。
  一旦有人拿它填按钮，按钮就会在视觉上篡夺品牌的位置，所以这里把它钉死。

跑法：python tools/verify/verify_css_tokens.py（或 tools/run_checks.py）
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSS_DIR = os.path.join(ROOT, "web", "css")

fails: list[str] = []
notes: list[str] = []


def check(cond, msg: str) -> None:
    if not cond:
        fails.append(msg)


# ── 1. 编码与换行 ─────────────────────────────────────────────────────────
# 这个仓库是纯 LF + UTF-8 无 BOM。带 BOM 会让某些工具把它当字节序标记输出；
# CRLF 混进来则会让「按行比对」类的脚本全线错位。
css_files = sorted(f for f in os.listdir(CSS_DIR) if f.endswith(".css"))
check(css_files, "web/css 下一个 .css 都没有")

texts: dict[str, str] = {}
for name in css_files:
    path = os.path.join(CSS_DIR, name)
    raw = open(path, "rb").read()
    check(raw[:3] != b"\xef\xbb\xbf", f"{name}: 不该有 UTF-8 BOM")
    check(b"\r\n" not in raw, f"{name}: 混入了 CRLF（本仓库统一 LF）")
    try:
        texts[name] = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        fails.append(f"{name}: 不是合法 UTF-8 —— {e}")
        texts[name] = raw.decode("utf-8", errors="replace")

for name, txt in texts.items():
    check(txt.count("{") == txt.count("}"),
          f"{name}: 花括号不配对（{{={txt.count('{')} }}={txt.count('}')}）")

print(f"样式表 {len(css_files)} 个：{', '.join(css_files)}")

# ── 2. 变量定义 vs 引用 ───────────────────────────────────────────────────
# 定义可能写在任何一个选择器里（:root、[data-theme=dark] 等），全都算数。
defined: set[str] = set()
for txt in texts.values():
    defined |= set(re.findall(r"(--[\w-]+)\s*:", txt))

used: dict[str, list[str]] = {}
for name, txt in texts.items():
    for i, line in enumerate(txt.splitlines(), 1):
        for var in re.findall(r"var\(\s*(--[\w-]+)", line):
            used.setdefault(var, []).append(f"{name}:{i}")

undefined = sorted(v for v in used if v not in defined)
for v in undefined:
    where = "、".join(used[v][:4])
    fails.append(f"引用了未定义的变量 {v}（{where}）")

print(f"变量定义 {len(defined)} 个，被引用 {len(used)} 个")
if undefined:
    print("  未定义的：" + ", ".join(undefined))
else:
    print("  引用全部有定义")

# ── 3. 身份色不许当交互色 ─────────────────────────────────────────────────
# 允许出现裸 --primary（不含 --primary-ink 这类派生）的选择器。
# 每一条都是 DESIGN.md 里明确的「身份职责」：品牌块 + 侧栏激活指示 + 主 CTA。
PRIMARY_OK = (
    ".brand-mark",        # masthead 的品牌块
    "body::before",       # 顶部橙色状态线（签名元素，预览 v2 确认）
    ".nav-indicator",     # 侧栏激活胶囊（用 --sidebar-accent 莓果玫瑰，此处兼容旧注释）
    ".nav-item.active",   # 侧栏活动项的指示条
    ".btn-primary",       # 主 CTA（唯一允许的橙色填充）
    ".banner",            # 权限横幅实心带（与导航胶囊同橙，需授权=品牌注意色）
    ".switch:checked",    # 开关的「开」态：用户选定的 iOS 风，开=品牌色
    ".settings-check",    # 设置页「检查更新」主按钮（主 CTA 的同级延续）
    ".status-new",        # 设置页「发现新版本」提示词（spec 明示橙的第二职责）
    ".ghost-link",        # 设置页 GitHub 幽灵按钮（spec：GitHub 悬停给橙）
)  # 注：顶部橙色状态线已按用户要求移除（2026-10-16）

# 把 CSS 粗略切成「选择器 { 声明 }」块。够用即可 —— 这里只做静态提示，
# 不是要写一个 CSS 解析器。
block_re = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
for name, txt in texts.items():
    for m in block_re.finditer(txt):
        selector = " ".join(m.group(1).split())
        body = m.group(2)
        # 只看真正的「用」—— 定义（--primary: ...）不算
        uses = [ln for ln in body.splitlines()
                if re.search(r"var\(\s*--primary\s*\)", ln)]
        if not uses:
            continue
        if any(sel in selector for sel in PRIMARY_OK):
            continue
        line_no = txt[:m.start()].count("\n") + 1
        fails.append(f"{name}:{line_no} 选择器「{selector}」把 --primary 用于非身份用途 "
                     f"（橙色只能做品牌块、侧栏激活指示与主 CTA，见 DESIGN.md 第 2 节）")

accent_uses = sum(len(re.findall(r"var\(\s*--primary\s*\)", t)) for t in texts.values())
print(f"裸 --primary 引用 {accent_uses} 处（只允许出现在品牌块 / 侧栏激活指示 / 主 CTA）")

# ── 4. 投影纪律 ───────────────────────────────────────────────────────────
# 这个体系是平面的：层级靠发丝线，全系统只有浮层允许有投影。
elevated = (".toast", ".modal", ".popover", ".menu", ".dialog")
# 开关圆点的投影是用户选定的 iOS 风的一部分（滑块悬浮在轨道上），属平面体系的既有例外。
switch_lift = (".switch",)
for name, txt in texts.items():
    for m in block_re.finditer(txt):
        selector = " ".join(m.group(1).split())
        if "box-shadow" not in m.group(2):
            continue
        if "box-shadow: none" in m.group(2):
            continue
        if any(sel in selector for sel in elevated):
            continue
        if any(sel in selector for sel in switch_lift):
            continue
        # --shadow-sm 本身就是 none，所以「变量形式」的直接放行
        if re.search(r"box-shadow:\s*var\(--shadow-sm\)", m.group(2)):
            continue
        line_no = txt[:m.start()].count("\n") + 1
        notes.append(f"{name}:{line_no} 选择器「{selector}」带投影 —— "
                     f"确认它是浮层，否则这个体系要求平面")

print(f"投影提示 {len(notes)} 条")

# ── 汇总 ──────────────────────────────────────────────────────────────────
print()
for n in notes:
    print("  [提示] " + n)
if fails:
    print()
    for f in fails:
        print("  [FAIL] " + f)
    print(f"\n结论：{len(fails)} 项不合格")
    sys.exit(1)
print("\n结论：全部通过")
sys.exit(0)
