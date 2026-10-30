"""EngineerDiff 的 PyInstaller 启动入口。

打包后的 `EngineerDiff.exe` 直接执行本脚本；它只做一件事：调用约定入口
`engineerdiff.app:main`。这样做的原因：

- PyInstaller 以脚本形式执行入口时，`engineerdiff.app` 会按普通包模块导入，
  包内相对导入（`from .models import ...`）与从源码运行时完全一致；
- 入口路径不依赖 `src/engineerdiff/app.py` 的具体文件位置，符合
  "入口约定 `src/engineerdiff/app.py:main`" 的契约。

注意：本文件不包含任何业务逻辑，所有参数（含 `--self-test`）原样交给 `main()`。
"""

from __future__ import annotations

import sys


def main() -> int:
    from engineerdiff.app import main as app_main

    result = app_main()
    if result is None:
        return 0
    return int(result)


if __name__ == "__main__":
    sys.exit(main())
