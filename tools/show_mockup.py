# -*- coding: utf-8 -*-
"""把 design/ 下的 HTML 预览在一个 pywebview 窗口里打开，方便截图对比。

窗口标题里带 "mihiru" 是为了能复用 tools/shot_app.ps1 的窗口匹配
（那个脚本按 ASCII 子串找窗口，标题里不能放中文匹配串）。

用法：
    python tools/show_mockup.py design/styles.html
"""
import os
import sys
import webview

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main() -> int:
    rel = sys.argv[1] if len(sys.argv) > 1 else "design/styles.html"
    path = rel if os.path.isabs(rel) else os.path.join(ROOT, rel)
    if not os.path.exists(path):
        print(f"找不到 {path}", file=sys.stderr)
        return 1

    w = int(sys.argv[2]) if len(sys.argv) > 2 else 1880
    h = int(sys.argv[3]) if len(sys.argv) > 3 else 990

    # 用 file:// 而不是本地路径。
    # 传本地路径时 pywebview 会起一个内置 HTTP 服务器，而它用的是随机端口 ——
    # 偏偏 Windows 的 SO_REUSEADDR 允许两个进程绑同一端口，于是窗口可能连到
    # **别的实例**的服务器上（实测踩过：被一个残留的旧 EXE 接走，页面 404）。
    # file:// 不经过服务器，直接读文件，没有这个问题。
    from urllib.parse import quote
    url = "file:///" + quote(path.replace("\\", "/"), safe="/:")

    webview.create_window("mahiru 风格预览", url,
                          width=w, height=h, x=10, y=10,
                          background_color="#0E1014")
    webview.start(private_mode=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
