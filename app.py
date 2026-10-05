"""CLI 入口（薄壳）。

真正的实现在 `coach.cli.main`；这里只保留一个入口文件，
使 `python app.py` 与 README 里既有的用法继续可用。
"""

from coach.cli.main import main

if __name__ == "__main__":
    raise SystemExit(main())
