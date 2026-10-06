"""值归一（纯逻辑，无 IO / 无 LLM）。

放在 `domain/` 而不是 `services/`：**状态机守卫（`domain/stages.py`）也要用它**，
而 domain 不允许依赖上层。

背景：JSON 模式下模型仍可能把布尔值写成字符串（`{"confirmed": "false"}`），
而 `bool("false") is True` —— 这是本项目一个**安全相关**的缺陷类：
- "用户没确认" 被判成 "已确认" → **状态机误推进**
- 普通提问被判成 "提交" → **误记账、误验收**
"""

__all__ = ["to_bool"]

#: 模型把布尔值写成字符串时可接受的"真"写法
_TRUE_WORDS = frozenset({
    "true", "t", "yes", "y", "1", "on",
    "是", "对", "对的", "好", "好的", "可以", "行", "确认", "确定", "没问题",
})

#: ……以及"假"写法
_FALSE_WORDS = frozenset({
    "false", "f", "no", "n", "0", "off",
    "否", "不是", "不对", "不行", "没有", "还没", "未确认", "不要",
})


def to_bool(value, *, default: bool = False) -> bool:
    """把模型给出的"布尔"归一成真正的 `bool`；无法判断时取 `default`。

    **为什么不能直接写 `bool(value)`**：JSON 模式下模型仍可能把布尔值写成字符串，
    而 `bool("false") is True` —— 会让"用户没确认"被判成"已确认"（状态机误推进），
    也会把普通提问当成提交（误记账）。

    默认 `default=False` 是 **fail-closed**：拿不准就当作"没有确认 / 不是提交"，
    由调用方保持原状态继续等待。
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return default
