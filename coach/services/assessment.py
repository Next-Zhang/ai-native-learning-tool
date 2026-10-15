"""能力测评用例（原 `assessor.py` 的 LLM 部分）。

流程：
1. ensure_plan()      进入测评阶段时生成 3~5 道由易到难的大纲，写入 state["assessment_progress"]
2. record_answer()    每轮把「上一轮教练的问题 + 本轮用户回答」交给 LLM 判定并记账
3. finalize()         答满题量即结束（**在 domain.assessment_rules 里做确定性聚合**）

兜底：出题失败用目标生成三道通用递进题；判卷调用失败按 `missing` 记录，不中断测评。
返回统一走 `PerceptionResult`（**F1**）：`ok=False` 表示"没有判定结果"或"判定降级"，
`error` 说明是哪一种。
"""

from coach.domain.assessment_rules import (
    MAX_QUESTIONS,
    MIN_QUESTIONS,
    current_index,
    normalize_plan,
)
from coach.domain.models import AnswerRecord
from coach.domain.perception import KIND_ASSESSMENT_VERDICT, PerceptionResult
from coach.llm import client
from coach.prompts.tasks import (
    ASSESSMENT_JUDGE_SYSTEM_PROMPT,
    ASSESSMENT_PLAN_SYSTEM_PROMPT,
)

__all__ = [
    "describe_progress",
    "ensure_plan",
    "record_answer",
]


def ensure_plan(state) -> bool:
    """还没有大纲就生成一份并写入 state。返回是否新生成。"""
    progress = state.get("assessment_progress") or {}
    if progress.get("plan"):
        return False

    goal = state.get("learning_goal") or ""   # 守卫 profile_complete 保证非空；不再默认 "Python"
    level = state.get("current_level") or "未知"
    minutes = state.get("session_minutes")
    deadline = state.get("target_date")

    user_content = (
        f"学习目标：{goal}\n当前水平：{level}\n"
        f"单次可投入：{minutes} 分钟\n期望期限：{deadline}\n"
        f"请设计 {MIN_QUESTIONS}~{MAX_QUESTIONS} 道测评题。"
    )

    try:
        data = client.json_call(
            ASSESSMENT_PLAN_SYSTEM_PROMPT, user_content, label="assessment_plan"
        )
        questions = normalize_plan(data.get("questions"), goal=goal)
    except Exception as exc:                      # noqa: BLE001 —— 出题失败必须有兜底
        print(f"[测评出题失败，已使用兜底大纲] {type(exc).__name__}: {exc}")
        questions = normalize_plan([], goal=goal)

    state["assessment_progress"] = {
        "plan": questions,
        "records": [],
        "finished": False,
    }
    return True


def record_answer(state, user_input: str, coach_reply: str) -> PerceptionResult:
    """记录当前这道题的作答与判定（**F1 判定点**：`kind = assessment_verdict`）。

    `ok=False` 有两种：`error="no_question"`（没有进行中的题）与判定调用失败。
    ⚠️ 后者**仍然记账**（保守记 `missing`）—— 否则"答满题量"的守卫永远不满足。
    这是 **P-1 的例外**，已在 executor 里显式注明。

    注意：调用方应在"题目是上一轮提出的"情况下调用（首次生成大纲那一轮不记录）。
    """
    progress = state.get("assessment_progress") or {}
    plan = progress.get("plan") or []
    records = progress.get("records") or []
    index = current_index(progress)
    if not index or index > len(plan):
        return PerceptionResult.failure(KIND_ASSESSMENT_VERDICT, error="no_question")

    question = plan[index - 1]
    user_content = (
        f"【本次题目】知识点：{question.get('topic', '')}\n"
        f"教练的原话：\n{coach_reply}\n\n"
        f"【用户的回答】\n{user_input}"
    )

    error = ""
    try:
        data = client.json_call(
            ASSESSMENT_JUDGE_SYSTEM_PROMPT, user_content, label="assessment_judge"
        )
        # JSON 模式仍可能返回非对象（数组 / 字符串）—— 必须在守卫内归一，
        # 否则下面的 `data.get(...)` 会抛 AttributeError 并跳出兜底。
        if not isinstance(data, dict):
            raise TypeError(f"判定结果不是 JSON 对象：{type(data).__name__}")
    except Exception as exc:                      # noqa: BLE001 —— 判定失败保守记为 missing
        print(f"[测评判定失败，按 missing 记录] {type(exc).__name__}: {exc}")
        data = {"verdict": "missing", "answer": "", "note": "判定调用失败"}
        error = f"{type(exc).__name__}: {exc}"

    record = AnswerRecord(
        index=index,
        topic=question.get("topic", ""),
        answer=data.get("answer", ""),
        verdict=data.get("verdict", "missing"),
        note=data.get("note", ""),
    )
    records.append(record.model_dump())
    progress["records"] = records
    if len(records) >= len(plan):
        progress["finished"] = True
    state["assessment_progress"] = progress

    if error:
        # 兜底值进了 state（记账），但 **ok=False** —— 调用方不得把它当"真判定"用。
        return PerceptionResult.failure(KIND_ASSESSMENT_VERDICT,
                                        payload=record.model_dump(), error=error)
    return PerceptionResult.validated(KIND_ASSESSMENT_VERDICT, record)


def describe_progress(state) -> str:
    """给教练看的测评进度（用于注入对话，确保问对题）。"""
    progress = state.get("assessment_progress") or {}
    plan = progress.get("plan") or []
    if not plan:
        return ""
    records = progress.get("records") or []
    lines = [f"- 测评进度：第 {len(records) + 1}/{len(plan)} 题"]
    index = current_index(progress)
    if index and index <= len(plan):
        question = plan[index - 1]
        lines.append(f"- 本题目知识点：{question.get('topic', '')}")
    if records:
        done = "、".join(
            f"第{r.get('index')}题({r.get('topic')})={r.get('verdict')}" for r in records
        )
        lines.append(f"- 已记录判定：{done}")
    lines.append("- 请只针对当前这道题提问或简短反馈，不要跳到后面题目或给完整计划")
    return "\n".join(lines)
