"""学习需求画像的确定性规则（原 `state.py` 的画像部分）。

关键规则：
- **空值不覆盖** —— "这轮没提到"不等于"这个信息不存在"。
- **必填四项与可选项分开** —— `sessions_per_week` 可选（碎片化场景常无法承诺）。
"""

#: **必填四项**：齐全才能进入能力测评（状态机的第一道守卫）。
#: `session_minutes` 是**单次**可投入时长，不是"每天总量"（见 architecture.md §11.3）。
PROFILE_FIELDS = ("learning_goal", "current_level", "session_minutes", "target_date")

#: **可选**字段：会被抽取与保存，但**不参与完备性判定**。
#: 若把它算进必填，用户会被卡在澄清阶段反复追问"每周几次"。
OPTIONAL_PROFILE_FIELDS = ("sessions_per_week",)

#: 提示词要求模型抽取、且 `merge_profile` 会合并的全部字段。
EXTRACTABLE_PROFILE_FIELDS = PROFILE_FIELDS + OPTIONAL_PROFILE_FIELDS

#: 单次可投入时长的**硬上下界**（v0.18，见 docs/memory-design.md §9）。
#: 上界 120 分钟是**产品决策**：更长的"一次学习"在教学上应当拆开（间隔效应），
#: 而且它让"一次学习最多多少轮对话"有了上界 —— 注入预算因此可预测。
SESSION_MINUTES_MIN = 15
SESSION_MINUTES_MAX = 120


def clamp_session_minutes(value):
    """把「单次可投入时长」钳到 [15, 120]；空值或不可解析返回 None（宁缺勿错）。

    ⚠️ 这是**行为变化**：用户说"我一次能学 4 小时"时会被钳到 120。
    调用方（`orchestration.executor`）会明确告知用户，不能让用户以为系统按 4 小时排。
    """
    if value is None or value == "":
        return None
    try:
        minutes = int(float(value))
    except (TypeError, ValueError):
        return None
    return max(SESSION_MINUTES_MIN, min(SESSION_MINUTES_MAX, minutes))


def merge_profile(state, profile) -> list[str]:
    """把画像中的**非空**字段合并进 state，返回本轮被更新的字段名列表。

    profile 可以是 Pydantic 模型（UserProfile），也可以是普通 dict。
    """
    data = profile.model_dump() if hasattr(profile, "model_dump") else dict(profile)

    updated: list[str] = []
    for field in EXTRACTABLE_PROFILE_FIELDS:
        value = data.get(field)
        # 跳过没提到 / 空白的值，保留 state 里已有的信息
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if field == "session_minutes":
            value = clamp_session_minutes(value)
            if value is None:
                continue
        if state.get(field) != value:
            state[field] = value
            updated.append(field)
    return updated


def profile_complete(state) -> bool:
    """**必填四项**（目标 / 水平 / 单次时长 / 期限）是否都已收集。"""
    for field in PROFILE_FIELDS:
        value = state.get(field)
        if value is None or value == "" or value == []:
            return False
    return True


def missing_profile_fields(state) -> list[str]:
    """返回还缺失的**必填**字段名，便于提示教练"还差什么"。"""
    return [
        field for field in PROFILE_FIELDS
        if state.get(field) in (None, "", [])
    ]
