# -*- coding: utf-8 -*-
"""验证 D 盘的 venv 里 pywebview + pythonnet 真的可用。

分三级递进，前一级不过就不必看后一级：
  1. import 与版本
  2. pythonnet 能否加载 .NET / WinForms（pywebview 的 Windows 后端依赖它）
  3. 真开一个窗口、加载 HTML、拿到 JS 返回值，然后自动关闭
"""
import sys
import threading
import time
from importlib.metadata import version as _pkgver

print("=" * 62)
print("1. import 与版本")
print("=" * 62)
import clr           # noqa: E402
import webview       # noqa: E402

# pywebview 6.x 不在模块上暴露 __version__，要从包元数据取
for name in ("pywebview", "pythonnet", "clr_loader", "bottle"):
    try:
        print(f"  {name:<12} {_pkgver(name)}")
    except Exception as e:
        print(f"  {name:<12} <取版本失败: {e}>")
print(f"  Python       {sys.version.split()[0]}")
print(f"  解释器       {sys.executable}")

print()
print("=" * 62)
print("2. pythonnet 加载 .NET / WinForms")
print("=" * 62)
try:
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    import System.Windows.Forms as WinForms  # noqa: E402
    from System.Drawing import Size          # noqa: E402
    print(f"  WinForms     OK  （Application 类型: {WinForms.Application.__name__}）")
except Exception as e:
    print(f"  !! WinForms 加载失败: {e}")
    sys.exit(1)

# WebView2 运行时是否可见（pywebview 的 EdgeChromium 后端需要它）
try:
    from webview.platforms import edgechromium  # noqa: E402
    print(f"  edgechromium 后端模块  OK  ({edgechromium.__file__.rsplit(chr(92), 1)[-1]})")
except Exception as e:
    print(f"  !! edgechromium 后端不可用: {e}")

print()
print("=" * 62)
print("3. 真开窗口 + JS 往返（2 秒后自动关闭）")
print("=" * 62)

state = {"loaded": False, "js": None}

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>M2 探针</title></head><body style="font-family:Segoe UI;padding:24px">
<h2 id="h">pywebview 正常</h2>
<script>window.__ready = "js-bridge-ok";</script>
</body></html>"""

win = webview.create_window("GameBoost M2 探针", html=HTML, width=520, height=320)


def on_loaded():
    state["loaded"] = True
    try:
        state["js"] = win.evaluate_js("window.__ready")
    except Exception as e:
        state["js"] = f"<evaluate_js 失败: {e}>"
    # 再拿一次 DOM，确认页面真的渲染了
    try:
        state["dom"] = win.evaluate_js("document.getElementById('h').textContent")
    except Exception as e:
        state["dom"] = f"<失败: {e}>"


win.events.loaded += on_loaded


def closer():
    time.sleep(3.0)
    try:
        win.destroy()
    except Exception:
        pass


threading.Thread(target=closer, daemon=True).start()
webview.start()

print(f"  窗口已加载事件   : {state['loaded']}")
print(f"  JS 返回值         : {state.get('js')!r}")
print(f"  DOM 文本          : {state.get('dom')!r}")
print()
ok = state["loaded"] and state.get("js") == "js-bridge-ok"
print("结论：" + ("pywebview 可用，JS <-> 页面渲染均正常" if ok else "存在问题，见上"))
sys.exit(0 if ok else 1)
