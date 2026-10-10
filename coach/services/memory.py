"""记忆的**叙事层**：两级压缩（L1 滚动摘要 / L2 定稿摘要）。

见 docs/memory-design.md §6。三条硬约束（§6.3）：

1. 只写**过程事实**（做了什么、学了什么、卡在哪）
2. **不得写判定**（掌握度 / 薄弱点 / 通过与否）—— **I-14**
3. **知识点名由代码提供**，模型不得自创或改名

第 3 条靠**结构**而不是靠提示词保证：摘要总是"**确定性骨架在前 + 模型润色在后**"
（`_compose`）。模型既替换不了事实，也引入不了画像里不存在的知识点。

失败兜底（§6.4）：退化为**确定性摘要**（骨架直接当摘要），绝不留空、绝不抛出 ——
与项目既有纪律一致（对话失败有 FALLBACK_REPLY、判定失败保持阶段、方案失败有兜底）。
"""

from coach.domain import memory
from coach.llm import client
from coach.prompts.tasks import (
    CONDENSE_CYCLE_SYSTEM_PROMPT,
    CONDENSE_PROGRESS_SYSTEM_PROMPT,
)

__all__ = [
    "fallback_cycle_summary",
    "summarize_cycle",
    "summarize_progress",
]

#: 送进模型的原文上限（字符）—— 压缩的输入本身也不能无限长
_MAX_INPUT_CHARS = 4000


def _polish(system_prompt: str, user_content: str, label: str) -> str:
    """调模型拿一段润色文本；**任何失败都返回空串**（由调用方走确定性兜底）。"""
    try:
        data = client.json_call(system_prompt, user_content, label=label)
        if not isinstance(data, dict):
            raise TypeError(f"压缩结果不是 JSON 对象：{type(data).__name__}")
        return str(data.get("summary") or "").strip()
    except Exception as exc:                  # noqa: BLE001 —— 压缩失败绝不中断主流程
        print(f"[记忆压缩失败，已使用确定性摘要] {type(exc).__name__}: {exc}")
        return ""


def _compose(skeleton_text: str, polished: str) -> str:
    """**骨架在前、润色在后** —— 这是 I-14 在结构上的保障。

    知识点名与验收动作永远来自骨架（代码生成），模型只能在后面补一段人话；
    它既不能替换事实，也不能凭空引入一个画像里不存在的知识点。
    """
    if not polished or polished == skeleton_text:
        return skeleton_text
    return f"{skeleton_text}\n【补充】{polished}"


def fallback_cycle_summary(state, seq=None) -> str:
    """确定性兜底摘要（= 骨架文本）。模型不可用时**记忆不会空着**。"""
    return memory.render_cycle_skeleton(memory.current_cycle_skeleton(state, seq))


def summarize_cycle(state, seq=None, skeleton=None) -> str:
    """**L2 定稿摘要**：确定性骨架 + 模型润色（模型失败时只留骨架）。"""
    skeleton = skeleton or memory.current_cycle_skeleton(state, seq)
    skeleton_text = memory.render_cycle_skeleton(skeleton)
    user_content = (
        f"【这次学习的事实骨架】\n{skeleton_text}\n\n"
        f"请据此写一条简短摘要。"
    )
    return _compose(skeleton_text,
                    _polish(CONDENSE_CYCLE_SYSTEM_PROMPT, user_content, "condense_cycle"))


def summarize_progress(state, dropped_messages, previous: str = "") -> str:
    """**L1 滚动摘要**：把（此前进展摘要 + 被挤出的较早对话）压成新的滚动摘要。

    失败兜底优先保留**已有的滚动摘要**（它至少是上一轮的结论），
    没有才退回确定性骨架 —— 记忆不能因为一次调用失败而变空。
    """
    body = []
    for message in dropped_messages or []:
        if not isinstance(message, dict):
            continue
        role = "用户" if message.get("role") == "user" else "教练"
        body.append(f"{role}：{str(message.get('content') or '')}")
    excerpt = "\n".join(body)[:_MAX_INPUT_CHARS]

    skeleton = memory.render_cycle_skeleton(memory.current_cycle_skeleton(state))
    user_content = (
        f"【此前进展摘要】\n{previous or '（无）'}\n\n"
        f"【较早的对话】\n{excerpt}\n\n"
        f"【本次学习的事实骨架】\n{skeleton}\n\n"
        f"请合并成一条进展摘要。"
    )
    polished = _polish(CONDENSE_PROGRESS_SYSTEM_PROMPT, user_content, "condense_progress")
    if polished:
        return polished
    return previous or skeleton