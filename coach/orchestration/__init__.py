"""编排层：把"一轮对话"的完整流程封装成可复用函数。

抽出来的原因：原 `app.py` 把这套流程内联在 252 行的 CLI 脚本里，
换一个界面（如 Streamlit 演示页）就只能复制逻辑。现在 CLI 与任何新界面
都只需调用 `run_turn()` 并渲染返回的 `TurnResult`。
"""

from coach.orchestration.turn import TurnResult, run_turn

__all__ = ["TurnResult", "run_turn"]
