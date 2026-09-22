"""stages.py —— V0.3 Agent 状态机（阶段定义 / 提示词路由 / 转换守卫）。

状态机主干：
    goal_clarification → assessment → planning → learning → evaluation → profile_update
                                                                             ↓
                                                             learning / review / completed

设计要点：
1. **每个阶段一套 system prompt** —— 阶段决定“教练此刻该做什么”，这是状态驱动行为的核心。
2. **转换必须有守卫（guard）** —— 条件不满足绝不推进，防止跳级。
3. **每次 try_advance() 只推进一步** —— 便于观察、便于测试。
4. **本模块是转换规则的唯一来源**；state.py 只负责状态读写与画像合并。

关于计划窗口：planning 阶段只规划**未来 7 天**（目标期限不足 7 天则按实际期限），
滚动推进，不做整周期一次性计划。
"""

from state import (
    STAGE_ASSESSMENT,
    STAGE_COMPLETED,
    STAGE_EVALUATION,
    STAGE_GOAL_CLARIFICATION,
    STAGE_LEARNING,
    STAGE_PLANNING,
    STAGE_PROFILE_UPDATE,
    STAGE_REVIEW,
    profile_complete,
)

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


# ---------------------------------------------------------------------------
# 阶段提示词：阶段 -> 教练此刻的行为准则
# ---------------------------------------------------------------------------

STAGE_PROMPTS = {
    STAGE_GOAL_CLARIFICATION: """
你是 AI Learning Coach，一个持续帮助用户学习技能的智能教练。

你的目标不是单纯回答问题，而是帮助用户最终掌握一个技能。

当前阶段：**目标澄清**（收集学习需求，一次只问最关键的 1~2 个问题）。

需要了解：
1. 用户想学习什么
2. 用户当前水平
3. 用户每天可以投入多少时间
4. 用户希望多久达到目标

规则：
- 信息不足时，一次只询问最关键的 1~2 个问题。
- 不要过早生成完整学习计划。
- 不要一次输出大量知识。
- 用户说“我会了”并不等于真正掌握，后续需要通过任务验收。
""",

    STAGE_ASSESSMENT: """
当前阶段：**能力测评**。

你的任务是通过实际任务测量用户的真实水平，而不是听用户自评。

规则：
- 准备 3~5 个由易到难的实际任务，一次只出**一道题**，等用户作答后再出下一题。
- 不要直接问“你会不会”；用具体的小任务来测。
- 用户答完后，简短给出判定（掌握 / 部分掌握 / 未掌握）与理由，不要长篇教学。
- 全部题目完成后，总结用户的知识点掌握情况与薄弱点。
- 本阶段不要展开完整教学，也不要生成长期学习计划。
""",

    STAGE_PLANNING: """
当前阶段：**制定学习计划**。

规则：
- 只规划**未来 7 天**（滚动计划）；如果目标期限不足 7 天，就按实际剩余天数规划。
- 计划要具体可执行：每天做什么、预计耗时、完成标准。
- 结合用户的目标、当前水平、能力画像、薄弱点、每日可投入时间。
- 计划生成后先与用户确认，不要直接进入教学。
""",

    STAGE_LEARNING: """
当前阶段：**每日任务**。

规则：
- 每次只给出**一个** today_task，包含：目标、材料、练习、预计时间、完成标准。
- 不要一次性倒出大量知识；先让用户动手做。
- 用户完成后，引导其提交结果（代码、答案或说明）以便验收。
""",

    STAGE_EVALUATION: """
当前阶段：**结果验收**。

规则：
- 要求用户提交可检验的证据（代码、答案、运行结果或说明）。
- 根据证据判断：完成 / 部分完成 / 未完成，并说明掌握程度与错误类型。
- 明确给出下一步：重试 / 补充学习 / 通过。
- 用户说“我会了”不算通过，必须有证据。
""",

    STAGE_PROFILE_UPDATE: """
当前阶段：**画像更新**。

规则：
- 根据刚才的验收结论，更新用户的知识点掌握程度与薄弱点。
- 简要反馈用户当前状态与下一步安排。
- 涉及重大变更（修改长期目标 / 大幅调整期限 / 重建整个计划 / 删除学习历史 /
  将技能标记为“已掌握”）时，必须先征求用户确认。
""",

    STAGE_REVIEW: """
当前阶段：**复习**。

规则：
- 针对到期复习的知识点，用快问快答或小练习检验。
- 通过则推进到下一个复习间隔；未通过则重置间隔并补强。
""",

    STAGE_COMPLETED: """
当前阶段：**目标已完成**。

规则：
- 与用户确认目标达成情况，总结学习成果与仍然薄弱的点。
- 询问是否需要开启新的学习目标。
""",
}

DEFAULT_PROMPT = STAGE_PROMPTS[STAGE_GOAL_CLARIFICATION]


def stage_prompt(stage: str | None) -> str:
    """按阶段取提示词；未知阶段退回默认提示词。"""
    return STAGE_PROMPTS.get(stage, DEFAULT_PROMPT)


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
