"""结果验收相关的确定性规则（原 `evaluator.py` 的纯函数部分）。

要点：掌握度由完成度推导，动作一致性由代码强制 —— 不让模型自己给分或越级放行。
"""

COMPLETION_SCORES = {
    "completed": 1.0,
    "partial": 0.5,
    "not_completed": 0.0,
}

COMPLETION_ALIASES = {
    "completed": "completed", "完成": "completed", "已完成": "completed",
    "done": "completed", "通过": "completed",
    "partial": "partial", "部分完成": "partial", "部分": "partial",
    "partially": "partial", "不完整": "partial",
    "not_completed": "not_completed", "未完成": "not_completed",
    "没完成": "not_completed", "失败": "not_completed", "incomplete": "not_completed",
}

ACTION_ALIASES = {
    "pass": "pass", "通过": "pass", "通过验收": "pass", "approved": "pass",
    "retry": "retry", "重试": "retry", "重做": "retry", "redo": "retry",
    "supplement": "supplement", "补充": "supplement", "补充学习": "supplement",
    "补课": "supplement", "remedial": "supplement",
}

# 完成度 -> 缺省动作（模型没给或给了非法值时使用）
DEFAULT_ACTIONS = {
    "completed": "pass",
    "partial": "supplement",
    "not_completed": "retry",
}


def completion_score(completion: str) -> float:
    """完成度 -> 掌握度分数。"""
    return COMPLETION_SCORES.get(completion, 0.0)


def normalize_action(completion: str, action: str) -> str:
    """动作一致性守卫：不允许"没做完却通过"。"""
    if action == "pass" and completion != "completed":
        # 部分完成 -> 补充学习后再试；未完成 -> 重做
        return "supplement" if completion == "partial" else "retry"
    if action not in DEFAULT_ACTIONS.values():
        return DEFAULT_ACTIONS.get(completion, "retry")
    return action


def normalize_error_types(value) -> list[str]:
    """错误类型归一：字符串 / 列表 / None 都能处理。"""
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        return []
    return [str(item).strip() for item in items if str(item).strip()]
