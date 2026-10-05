"""Agent 状态机：阶段定义、转换守卫与推进（原 `stages.py` 的规则部分）。

设计要点：
1. **本模块是转换规则的唯一来源**；`state_store` 只负责状态读写。
2. **转换必须有守卫（guard）** —— 条件不满足绝不推进，防止跳级。
3. **每次 try_advance() 只推进一步** —— 便于观察、便于测试。
4. 阶段提示词已移出本模块，见 `coach.prompts.stages`（提示词是内容，规则是逻辑）。

关于计划窗口：planning 阶段只规划**未来 7 天**（目标期限不足 7 天则按实际期限），
滚动推进，不做整周期一次性计划。
"""

from coach.domain.profile_rules import profile_complete

# 阶段名常量
STAGE_GOAL_CLARIFICATION = "goal_clarification"
STAGE_ASSESSMENT = "assessment"
STAGE_PLANNING = "planning"
STAGE_LEARNING = "learning"
STAGE_EVALUATION = "evaluation"
STAGE_PROFILE_UPDATE = "profile_update"
STAGE_REVIEW = "review"
STAGE_COMPLETED = "completed"

# 主干阶段（按顺序推进）
STAGES = (
    STAGE_GOAL_CLARIFICATION,
    STAGE_ASSESSMENT,
    STAGE_PLANNING,
    STAGE_LEARNING,
    STAGE_EVALUATION,
    STAGE_PROFILE_UPDATE,
)

# 出口阶段（不是线性主干，由业务流程决定进入）
EXIT_STAGES = (STAGE_REVIEW, STAGE_COMPLETED)

ALL_STAGES = STAGES + EXIT_STAGES

STAGE_LABELS = {
    STAGE_GOAL_CLARIFICATION: "目标澄清",
    STAGE_ASSESSMENT: "能力测评",
    STAGE_PLANNING: "学习计划",
    STAGE_LEARNING: "每日任务",
    STAGE_EVALUATION: "结果验收",
    STAGE_PROFILE_UPDATE: "画像更新",
    STAGE_REVIEW: "复习",
    STAGE_COMPLETED: "已完成",
}


def stage_label(stage: str | None) -> str:
    """阶段名的中文标签。"""
    return STAGE_LABELS.get(stage, str(stage))


# ---------------------------------------------------------------------------
# 转换守卫：条件函数（纯函数，便于测试）
# ---------------------------------------------------------------------------

def _guard_profile_complete(state) -> bool:
    """四项信息齐全才允许进入能力测评。"""
    return profile_complete(state)


def _guard_skill_profile(state) -> bool:
    """已产出能力画像才允许进入计划阶段。"""
    return bool(state.get("skill_profile"))


def _guard_plan_confirmed(state) -> bool:
    """已有学习计划**且用户已确认**，才允许进入每日任务（V0.3c：先确认后教学）。"""
    return bool(state.get("current_plan")) and bool(state.get("plan_confirmed"))


def _guard_submission(state) -> bool:
    """有今日任务且用户已提交结果，才允许进入验收。"""
    return bool(state.get("today_task")) and bool(state.get("pending_submission"))


def _guard_latest_result(state) -> bool:
    """已有验收结论才允许进入画像更新。"""
    return state.get("latest_result") is not None


def _guard_update_applied(state) -> bool:
    """画像更新已应用，才允许从 profile_update 回到每日任务（V0.3e 回路）。"""
    return bool(state.get("latest_result_applied"))


# (起始阶段, 目标阶段, 守卫函数, 守卫说明) —— 主干：线性推进
TRANSITIONS = (
    (STAGE_GOAL_CLARIFICATION, STAGE_ASSESSMENT, _guard_profile_complete, "四项信息齐全"),
    (STAGE_ASSESSMENT, STAGE_PLANNING, _guard_skill_profile, "已产出能力画像"),
    (STAGE_PLANNING, STAGE_LEARNING, _guard_plan_confirmed, "计划已生成且用户已确认"),
    (STAGE_LEARNING, STAGE_EVALUATION, _guard_submission, "已提交待验收结果"),
    (STAGE_EVALUATION, STAGE_PROFILE_UPDATE, _guard_latest_result, "已产出验收结论"),
)

# 回路：画像更新完成后回到每日任务（继续下一个任务或重做当前任务）
RESUME_TRANSITIONS = (
    (STAGE_PROFILE_UPDATE, STAGE_LEARNING, _guard_update_applied, "画像更新已应用"),
)

ALL_TRANSITIONS = TRANSITIONS + RESUME_TRANSITIONS


def pending_transition(state):
    """返回当前阶段对应的转换定义 (from, to, guard, reason)；无则返回 None。"""
    stage = state.get("current_stage")
    for transition in ALL_TRANSITIONS:
        if transition[0] == stage:
            return transition
    return None


def can_advance(state) -> bool:
    """当前阶段是否已满足推进条件。"""
    transition = pending_transition(state)
    return bool(transition) and transition[2](state)


def blocked_reason(state) -> str | None:
    """当前阶段尚未满足的推进条件说明；已可推进或无转换时返回 None。"""
    transition = pending_transition(state)
    if transition is None or transition[2](state):
        return None
    return transition[3]


def try_advance(state) -> str | None:
    """尝试推进一步；成功返回新阶段名，未满足守卫返回 None。

    注意：每次只推进一步 —— 即使一次调用后所有条件都成立，也只推进一档，
    下一次再推进。这样阶段变化是逐轮可见、可测试的。
    """
    transition = pending_transition(state)
    if transition is None:
        return None
    from_stage, to_stage, guard, _reason = transition
    if state.get("current_stage") != from_stage or not guard(state):
        return None
    state["current_stage"] = to_stage
    return to_stage


def describe_stage(state) -> str:
    """生成一行阶段描述，用于终端展示。"""
    stage = state.get("current_stage")
    label = stage_label(stage)
    reason = blocked_reason(state)
    if reason:
        return f"{label}（待满足：{reason}）"
    return label
