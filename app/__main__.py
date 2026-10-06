# -*- coding: utf-8 -*-
"""允许 `python -m app` 启动。"""
import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())
