"""内容层护栏（**F4**）：对模型产出的**文字**做可验证的约束。

与编排层的关系
--------------
护栏**不认识**状态机、能力注册表或槽位 —— 它只吃 `(text, GuardrailContext)`、
吐 `(text, hits)`。因此它**独立于编排层**、可以**逐条叠加**（`GUARDRAILS` 元组），
也就能单测 —— 不必跑一整轮编排。

为什么内容层需要它
------------------
编排层的守卫管"能不能推进"，F1 的感知契约管"判定成功没有"，
但**模型写了什么**一直没有代码约束 —— 而几条红线的落点恰恰全在内容层：

- **X-16 的真实原因是内容层**：模型在 `learning` 阶段**自己宣布了验收结论**，
  于是用户先听到"通过"，下一步又被代码推翻（**I-2** 就是为它立的）。
  提示词里已经写了禁令，但**提示词不是强制**。
- **I-14** 要求摘要只写过程事实，而摘要里唯一不可信的正是模型润色的那一段。

修法都是**确定性**的（删句 / 丢弃补充段 / 追加提醒），**不做二次模型调用** ——
护栏不能反过来增加成本与不确定性。命中与否都会被记录（`TurnResult.guardrail_hits`）。
"""

from dataclasses import dataclass
from typing import Callable

from coach.domain.stages import STAGE_LEARNING

__all__ = [
    "GUARDRAILS",
    "Guardrail",
    "GuardrailContext",
    "GuardrailReport",
    "run_guardrails",
    "upcoming_task_goals",
]

#: 宣布验收结论的措辞。**刻意保持为一份短清单**：护栏必须"可验证"，
#: 模糊的语义判断（"这句算不算暗示通过"）不该进这里 —— 那会变成不可维护的黑箱。
_VERDICT_PHRASES = (
    "验收通过", "验收未通过", "验收不通过", "通过了验收", "未通过验收",
    "判定通过", "判定为通过", "判定结果为", "验收结果", "验收结论",
    "已通过验收", "恭喜你通过", "本次通过", "本轮通过",
)

#: 判定性词汇（**I-14**：摘要只写过程事实，不承载判定）。
_SUMMARY_JUDGEMENT_WORDS = (
    "掌握度", "已掌握", "未掌握", "薄弱点", "水平评估", "判为", "评分",
)

#: 删句后若什么都不剩，用这句**确定性安全文本**顶上（不能让用户收到空白回复）。
_SAFE_LEARNING_REPLY = "（这一轮我们先把任务做完；是否通过由系统在下一步统一给出。）"

#: 命中"提前布置后续任务"后追加的提醒。
#: **不删正文** —— 复述任务目标常常是正常讲解的一部分，删了反而伤内容；
#: 而"同时讲两个任务"的危害是混淆，一条提醒足以消除。
_NEXT_TASK_REMINDER = "（提醒：本轮的权威任务只有上面那一个，后续任务请等系统下发。）"

#: 句子切分点（中英文句末标点 + 换行）
_SENTENCE_END = "。！？!?\n"


@dataclass(frozen=True)
class GuardrailContext:
    """护栏需要的**全部**上下文 —— 都是 plain data，不含 state 对象、不含编排。"""

    stage: str = ""
    kind: str = ""                      # reply / summary_supplement / …
    today_task_goal: str = ""
    upcoming_task_goals: tuple = ()


@dataclass(frozen=True)
class Guardrail:
    """一条护栏。`apply` 必须是**纯函数**（同样的输入给同样的输出）。"""

    id: str
    description: str
    apply: Callable[[str, GuardrailContext], str]
    #: 只在这些阶段生效；空元组 = 全部阶段
    stages: tuple = ()
    #: 只在这些内容种类上生效；空元组 = 全部种类
    kinds: tuple = ()

    def applies_to(self, context: GuardrailContext) -> bool:
        if self.stages and context.stage not in self.stages:
            return False
        if self.kinds and context.kind not in self.kinds:
            return False
        return True


@dataclass
class GuardrailReport:
    """护栏处理后的文本 + 命中清单（命中要做成**可见**的，否则等于没有）。"""

    text: str
    hits: list


def _split_sentences(text: str) -> list:
    """按句末标点切句，**保留分隔符**（重组时不能丢标点）。"""
    parts, buf = [], []
    for char in text:
        buf.append(char)
        if char in _SENTENCE_END:
            parts.append("".join(buf))
            buf = []
    if buf:
        parts.append("".join(buf))
    return parts


def _g_verdict_announcement(text: str, context: GuardrailContext) -> str:
    """**G-1 防抢答判定**：命中"宣布验收结论"的句子直接删掉。

    删句而不是删整条回复：模型大部分话是有用的，只有那一两句越界。
    全被删光时用确定性安全文本顶上。
    """
    sentences = _split_sentences(text)
    kept = [s for s in sentences if not any(p in s for p in _VERDICT_PHRASES)]
    if len(kept) == len(sentences):
        return text
    cleaned = "".join(kept).strip()
    return cleaned or _SAFE_LEARNING_REPLY


def _g_summary_judgement(text: str, context: GuardrailContext) -> str:
    """**G-2 摘要不承载判定**（**I-14**）：命中判定词 → **整段丢弃**。

    返回空串即"这段不可用"，由调用方保留确定性骨架（骨架永远可用）。
    """
    if any(word in text for word in _SUMMARY_JUDGEMENT_WORDS):
        return ""
    return text


def _g_premature_next_task(text: str, context: GuardrailContext) -> str:
    """**G-3 不提前布置后续任务**：命中后续任务的目标原文 → 追加一条提醒。"""
    for goal in context.upcoming_task_goals:
        if len(goal) >= 6 and goal in text:
            return text.rstrip() + "\n" + _NEXT_TASK_REMINDER
    return text


#: 护栏清单 —— **顺序即应用顺序**（每条只在上一条的输出上继续）。
GUARDRAILS = (
    Guardrail(
        id="verdict_announcement",
        description="learning 阶段不得宣布验收结论（**I-2** / X-16）；命中则删掉那几句",
        apply=_g_verdict_announcement,
        stages=(STAGE_LEARNING,),
    ),
    Guardrail(
        id="summary_judgement_words",
        description="摘要的模型润色段不得承载判定（**I-14**）；命中则整段丢弃",
        apply=_g_summary_judgement,
        kinds=("summary_supplement",),
    ),
    Guardrail(
        id="premature_next_task",
        description="对话回复不得提前布置后续任务；命中则追加确定性提醒",
        apply=_g_premature_next_task,
        kinds=("reply",),
    ),
)


def run_guardrails(text: str, context=None) -> GuardrailReport:
    """按顺序应用所有命中的护栏，返回处理后的文本与命中清单。

    **任何异常都不能影响主流程**（与 metrics、observability 同纪律）：
    某条护栏自己炸了，就当它没说话，继续走下一条。
    """
    context = context or GuardrailContext()
    current = text or ""
    hits = []
    for guard in GUARDRAILS:
        if not guard.applies_to(context):
            continue
        try:
            updated = guard.apply(current, context)
        except Exception:                  # noqa: BLE001 —— 护栏失效不该让整轮崩掉
            continue
        if updated != current:
            hits.append(guard.id)
            current = updated
    return GuardrailReport(text=current, hits=hits)


def upcoming_task_goals(state, today_task=None) -> tuple:
    """窗口里**除当前任务之外**的任务目标（供 G-3 比对）。

    这是本模块唯一读 state 的地方 —— 只做"把内容取出来"，
    不参与任何判定（护栏仍然不认识编排）。
    """
    task = today_task if today_task is not None else (state.get("today_task") or {})
    current = str((task or {}).get("goal") or "").strip()
    window = state.get("current_window") or {}
    goals = []
    for day in window.get("days") or []:
        for item in (day or {}).get("tasks") or []:
            goal = str((item or {}).get("goal") or "").strip()
            if len(goal) >= 6 and goal != current and goal not in goals:
                goals.append(goal)
    return tuple(goals)
