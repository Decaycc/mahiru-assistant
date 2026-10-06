# -*- coding: utf-8 -*-
"""打包入口。

为什么不直接用 app/__main__.py 当 PyInstaller 的入口：
那时脚本是作为**顶层模块**被执行的，没有包上下文，
里面任何 `from .x import y` 都会报
「attempted relative import with no known parent package」。
所以入口要放在包外，用绝对导入把包引进来。

`python -m app` 仍然走 app/__main__.py，两者互不影响。
"""
import os
import sys

# 源码运行时把项目根加入 sys.path；打包后 __file__ 在解压目录，
# 该目录本身已在 sys.path 里，这一步无害。
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from app.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
