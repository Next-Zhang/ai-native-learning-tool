"""命令行界面层。

注意：**不要在 `__init__` 里导入 `main` 函数**——那会让函数遮蔽同名子模块
`coach.cli.main`（`import coach.cli` 后 `coach.cli.main` 会变成函数而不是模块）。
需要入口函数请用完整路径：`from coach.cli.main import main`。
"""
