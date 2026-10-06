"""状态 schema 与向后兼容迁移（原 `state.py` 的 schema 部分）。

本模块只定义"状态长什么样"与"旧状态如何升级"，**不做落盘**（落盘见 `coach.storage.state_store`）。
"""

import json

from coach.domain.plan_rules import plan_unit
from coach.domain.stages import STAGE_GOAL_CLARIFICATION

DEFAULT_STATE = {
    "learning_goal": None,
    "current_level": None,
    "session_minutes": None,       # **单次**可投入分钟数（v0.13 起替代 daily_minutes）
    "sessions_per_week": None,     # 每周大约几次（可选；None = 不作承诺）
    "target_date": None,

    "current_stage": STAGE_GOAL_CLARIFICATION,

    "skill_profile": {},
    "weak_points": [],

    # 双层计划（v0.14 / S-12）：
    #   roadmap        = 长期**路线图**（目标 → 里程碑），**不滚动**
    #   current_window = 短期**执行窗口**（可执行单元列表），**滚动**
    "roadmap": None,
    "current_window": None,
    "plan_confirmed": False,       # 路线图是否已被用户确认（确认后才进入学习）
    "plan_progress": {             # 窗口游标（第几个单元 / 单元内第几个任务 / 已完成 / 完成 / 尝试次数）
        "day": 1,
        "task": 1,
        "completed": [],
        "finished": False,
        "attempts": 0,             # v0.14：验收判定次数（**含重做**）—— "滚动=重估"的速度信号
    },
    "today_task": None,

    # V0.3 新增字段（V0.3b–e 使用；旧状态文件由 ensure_keys 自动补齐）
    "assessment_progress": None,   # 测评进度：题目、作答、当前题号
    "pending_submission": None,    # 用户提交、待验收的学习结果
    "latest_result": None,         # 最近一次验收结论
    "latest_result_applied": False,  # V0.3e：该结论是否已应用到画像

    "conversation_history": []
}

#: 旧字段 → 新字段。
#:
#: - v0.13：时间预算由"**每天总量**"改为"**单次时长**"。
#:   **迁移假设**：旧的 `daily_minutes` 被当作"一次坐下来的时长"。
#:   这对原用户（20~30 分钟/天）是合理的近似，但**语义确实变了** ——
#:   迁移后教练会按 `session_minutes` 排任务，用户若实际只有 10 分钟需自行纠正。
#:   之所以选择迁移而非"重新追问"：后者会把用户打回澄清阶段，代价更大。
#: - v0.14：`current_plan` 改名为 `current_window`（它本来就是"执行窗口"，
#:   不是完整计划；完整计划现在是 `roadmap`）。**纯改名，语义不变**。
LEGACY_FIELD_MAP = {
    "daily_minutes": "session_minutes",
    "current_plan": "current_window",
}


def migrate_legacy_fields(state) -> list[str]:
    """把旧字段搬到新字段，返回迁移记录（形如 `daily_minutes->session_minutes`）。

    只在新字段为空时搬；**不覆盖**新值，也**不删除**旧键 —— 迁移应当信息保全，
    删掉旧键会让"迁移出错"变成不可逆事件。
    """
    moved: list[str] = []
    for old, new in LEGACY_FIELD_MAP.items():
        if old not in state:
            continue
        if state.get(new) in (None, "", []):
            state[new] = state[old]
            if state[old] is not None:
                moved.append(f"{old}->{new}")
    return moved


def upgrade_window_shape(state) -> list[str]:
    """把旧的"计划"结构补齐成**执行窗口**结构（v0.14）。

    旧结构只有 `horizon_days`；新结构需要 `length`（窗口长度）+ `unit`（单位）
    + `milestone_id`（所属里程碑）。**只补缺失的键，不覆盖已有值。**
    """
    window = state.get("current_window")
    if not isinstance(window, dict):
        return []

    changed: list[str] = []
    if "length" not in window:
        window["length"] = int(
            window.get("horizon_days") or len(window.get("days") or []) or 1
        )
        changed.append("current_window.length")
    if "unit" not in window:
        window["unit"] = plan_unit(state)
        changed.append("current_window.unit")
    if "milestone_id" not in window:
        window["milestone_id"] = (state.get("roadmap") or {}).get("current_milestone")
        changed.append("current_window.milestone_id")
    return changed


def upgrade_plan_progress(state) -> list[str]:
    """给 `plan_progress` 补 v0.14 新增的 `attempts`（验收尝试次数）。

    **`ensure_keys` 只补顶层键**，嵌套结构必须单独升级 —— 漏了它，
    旧状态文件里的 `plan_progress` 就永远没有 `attempts`，
    "滚动=重估"会退化成中性（ratio = 1），静默失效。
    """
    progress = state.get("plan_progress")
    if not isinstance(progress, dict) or "attempts" in progress:
        return []
    progress["attempts"] = 0
    return ["plan_progress.attempts"]


def ensure_keys(state, defaults=None) -> list[str]:
    """升级 state：迁移旧字段 → 升级嵌套结构 → 补齐缺失顶层键；返回**全部变更**。

    **返回值必须包含迁移结果**：调用方（`storage.state_store.load_state`）只在
    返回非空时才落盘。旧实现丢弃迁移记录 → 迁移只在内存生效，**文件里始终留着旧字段**，
    看起来"迁移没生效"。

    顺序很重要：先迁移（否则 `session_minutes` 会被默认值 `None` 占位，
    后续迁移因"新值非空"被跳过）。
    """
    changed: list[str] = []
    changed.extend(migrate_legacy_fields(state))
    changed.extend(upgrade_window_shape(state))
    changed.extend(upgrade_plan_progress(state))

    if defaults is None:
        defaults = DEFAULT_STATE
    for key, value in defaults.items():
        if key not in state:
            # 可变默认值要深拷贝，避免多个 state 共享同一个 list/dict
            state[key] = json.loads(json.dumps(value))
            changed.append(key)
    return changed
