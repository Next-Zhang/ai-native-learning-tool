"""支持 `python -m coach` 启动同一套 CLI。"""

from coach.cli.main import main

if __name__ == "__main__":
    raise SystemExit(main())
