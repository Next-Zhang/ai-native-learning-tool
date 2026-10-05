"""学习需求画像的确定性规则（原 `state.py` 的画像部分）。

关键规则：**空值不覆盖** —— "这轮没提到"不等于"这个信息不存在"。
"""

# 四项必须齐全才能进入能力测评（状态机的第一道守卫）
PROFILE_FIELDS = ("learning_goal", "current_level", "daily_minutes", "target_date")


def merge_profile(state, profile) -> list[str]:
    """把画像中的**非空**字段合并进 state，返回本轮被更新的字段名列表。

    profile 可以是 Pydantic 模型（UserProfile），也可以是普通 dict。
    """
    data = profile.model_dump() if hasattr(profile, "model_dump") else dict(profile)

    updated: list[str] = []
    for field in PROFILE_FIELDS:
        value = data.get(field)
        # 跳过没提到 / 空白的值，保留 state 里已有的信息
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if state.get(field) != value:
            state[field] = value
            updated.append(field)
    return updated


def profile_complete(state) -> bool:
    """四项（目标/水平/每日时间/期限）是否都已收集。"""
    for field in PROFILE_FIELDS:
        value = state.get(field)
        if value is None or value == "" or value == []:
            return False
    return True


def missing_profile_fields(state) -> list[str]:
    """返回还缺失的字段名，便于提示教练"还差什么"。"""
    return [
        field for field in PROFILE_FIELDS
        if state.get(field) in (None, "", [])
    ]
