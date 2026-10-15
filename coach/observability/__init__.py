"""观测性（**F5** 单轮因果链）。

与 `coach.metrics` 的分工：
- `metrics` —— **事件级**计数（一条 llm_call / 一条 turn），用于成本、延迟、护栏读数；
- `trace`   —— **单轮因果链**（输入 → 跑了哪些步骤 → 状态变了什么 → 回复），用于排查。
"""

from coach.observability import trace

__all__ = ["trace"]
