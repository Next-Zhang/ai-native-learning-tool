"""提示词集中管理（纯数据，无逻辑）。

    stages  六阶段行为准则
    tasks   各用例的抽取/出题/判卷/计划/确认/提交/验收提示词
"""

from coach.prompts import stages, tasks

__all__ = ["stages", "tasks"]
