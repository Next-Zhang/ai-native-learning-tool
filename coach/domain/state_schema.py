"""状态 schema 与向后兼容迁移（原 `state.py` 的 schema 部分）。

本模块只定义"状态长什么样"与"旧状态如何升级"，**不做落盘**（落盘见 `coach.storage.state_store`）。
"""

import json

from coach.domain.stages import STAGE_GOAL_CLARIFICATION

DEFAULT_STATE = {
    "learning_goal": None,
    "current_level": None,
    "daily_minutes": None,
    "target_date": None,

    "current_stage": STAGE_GOAL_CLARIFICATION,

    "skill_profile": {},
    "weak_points": [],

    "current_plan": None,
    "plan_confirmed": False,       # V0.3c：计划是否已被用户确认（确认后才进入每日任务）
    "plan_progress": {             # V0.3d：计划游标（第几天 / 当天第几个任务 / 已完成列表）
        "day": 1,
        "task": 1,
        "completed": [],
        "finished": False,
    },
    "today_task": None,

    # V0.3 新增字段（V0.3b–e 使用；旧状态文件由 ensure_keys 自动补齐）
    "assessment_progress": None,   # 测评进度：题目、作答、当前题号
    "pending_submission": None,    # 用户提交、待验收的学习结果
    "latest_result": None,         # 最近一次验收结论
    "latest_result_applied": False,  # V0.3e：该结论是否已应用到画像

    "conversation_history": []
}


def ensure_keys(state, defaults=None) -> list[str]:
    """为 state 补齐 defaults 中缺失的顶层键（不覆盖已有值），返回补齐的键名。

    用途：版本升级新增 state 字段时，让旧的状态文件平滑迁移而不是报错。
    """
    if defaults is None:
        defaults = DEFAULT_STATE
    added: list[str] = []
    for key, value in defaults.items():
        if key not in state:
            # 可变默认值要深拷贝，避免多个 state 共享同一个 list/dict
            state[key] = json.loads(json.dumps(value))
            added.append(key)
    return added
