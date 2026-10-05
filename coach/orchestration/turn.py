"""单轮流程编排（从 `app.py` 抽出，行为与 V0.3 保持一致）。

一轮的顺序（每一步都有明确理由，勿随意调换）：

    ① 画像抽取 → 合并（空值不覆盖）
    ② 计划阶段：先判定"用户是否确认"，再确保计划已生成
    ③ 每日任务阶段：先判定"是否提交"，再准备今日任务
    ④ 验收阶段：有提交且尚未判定时先做结构化判定
    ⑤ 状态机推进（条件满足才走一步）
    ⑥ 测评阶段：首次进入先生成大纲
    ⑦ 让教练带着最新状态对话
    ⑧ 测评记账（只有"题目在上一步已经提出"时才记录本轮作答）
    ⑨ 判定成功后应用画像更新（按 pass / retry 决定推进还是重做）
    ⑩ 记录历史并落盘

前四步必须先于状态机推进、后三步必须后于推进，否则守卫会读到过期状态。
"""

from dataclasses import dataclass, field
from typing import Any

from coach.domain.assessment_rules import finalize, is_finished
from coach.domain.cursor import build_today_task, is_plan_finished
from coach.domain.profile_rules import merge_profile, profile_complete
from coach.domain.stages import (
    STAGE_ASSESSMENT,
    STAGE_EVALUATION,
    STAGE_LEARNING,
    STAGE_PLANNING,
    try_advance,
)
from coach.metrics import recorder as metrics
from coach.services import assessment, daily_task, evaluation, planning, profile
from coach.services.coach import chat_with_coach
from coach.storage.state_store import save_state

__all__ = ["TurnResult", "run_turn"]


@dataclass
class TurnResult:
    """一轮对话的结果。界面层只读它，不需要理解内部流程。"""

    user_input: str
    stage_before: str = ""
    stage_after: str = ""

    answer: str = ""
    sources: list[dict] = field(default_factory=list)

    # 画像
    updated_fields: list[str] = field(default_factory=list)

    # 阶段变化（可能一轮内发生多次）
    transitions: list[tuple[str, str]] = field(default_factory=list)

    # 测评
    assessment_plan_created: bool = False
    assessment_topics: list[str] = field(default_factory=list)
    record: Any = None
    summary: dict | None = None

    # 计划
    plan_created: bool = False
    confirmation: Any = None

    # 每日任务
    task_created: dict | None = None
    submission: Any = None

    # 验收与画像更新
    evaluation_result: Any = None
    update_summary: dict | None = None

    # 本窗口计划是否已全部完成
    plan_finished: bool = False

    @property
    def image_fields_updated(self) -> bool:
        return bool(self.updated_fields)


def run_turn(state, user_input: str, use_rag: bool = False) -> TurnResult:
    """执行一轮完整流程，返回结果并落盘。

    state 会被原地修改（与旧 `app.py` 的行为一致）。
    """
    result = TurnResult(
        user_input=user_input,
        stage_before=state.get("current_stage", ""),
    )

    # 指标归属：本轮内的 LLM 调用都记在本轮**起始阶段**下（近似但足够定位）
    metrics.set_stage(result.stage_before)

    # ① 画像抽取 → 合并（空值不覆盖）
    #    只在**画像未齐**时抽取：四项齐全后每轮再抽一次既没有可测收益，
    #    又占掉约 1/3 的调用量（违反“每步 LLM 调用必须能说明可测收益”）。
    if profile_complete(state):
        result.updated_fields = []
    else:
        result.updated_fields = merge_profile(state, profile.extract_profile(user_input))

    # ② 计划阶段：先判定确认，再确保计划已生成
    if state.get("current_stage") == STAGE_PLANNING:
        if state.get("current_plan") and not planning.is_confirmed(state):
            result.confirmation = planning.confirm_plan(state, user_input)
        result.plan_created = planning.ensure_plan(state)

    # ③ 每日任务阶段：先判定提交，再准备今日任务
    in_learning = state.get("current_stage") == STAGE_LEARNING
    if in_learning:
        if state.get("today_task") and not state.get("pending_submission"):
            result.submission = daily_task.detect_submission(state, user_input)
        if not state.get("today_task"):
            result.task_created = build_today_task(state)

    # ④ 验收阶段：有提交且尚未判定时先做结构化判定
    if state.get("current_stage") == STAGE_EVALUATION and state.get("pending_submission"):
        result.evaluation_result = evaluation.evaluate(state)

    # ⑤ 状态机：条件满足才推进一步
    previous_stage = state.get("current_stage")
    if try_advance(state):
        result.transitions.append((previous_stage, state.get("current_stage")))

    # ⑥ 测评阶段：首次进入先生成大纲
    in_assessment = state.get("current_stage") == STAGE_ASSESSMENT
    if in_assessment:
        result.assessment_plan_created = assessment.ensure_plan(state)
        if result.assessment_plan_created:
            plan_questions = (state.get("assessment_progress") or {}).get("plan") or []
            result.assessment_topics = [q.get("topic", "") for q in plan_questions]

    # ⑦ 让教练带着最新状态对话
    #    注意传 **stage_before**：状态机在本轮可能已经推进（例如"用户刚提交"→ evaluation），
    #    但教练此刻仍应按**本轮起始阶段**说话；否则它会抢在代码判定之前自己宣布验收结论。
    answer, sources = chat_with_coach(
        user_input=user_input,
        history=state["conversation_history"],
        use_rag=use_rag,
        state=state,
        stage=result.stage_before,
    )
    result.answer = answer
    result.sources = sources

    # ⑧ 测评记账：只有"题目在上一步已经提出"时才记录本轮作答
    if in_assessment and not result.assessment_plan_created:
        result.record = assessment.record_answer(state, user_input, answer)
        if is_finished(state):
            result.summary = finalize(state)
            previous_stage = state.get("current_stage")
            if try_advance(state):
                result.transitions.append((previous_stage, state.get("current_stage")))

    # ⑨ 判定成功后应用画像更新，并按 pass / retry 决定推进还是重做
    if result.evaluation_result is not None:
        previous_stage = state.get("current_stage")
        if try_advance(state):                       # 结果验收 -> 画像更新
            result.transitions.append((previous_stage, state.get("current_stage")))
        result.update_summary = evaluation.apply_update(state)
        previous_stage = state.get("current_stage")
        if try_advance(state):                       # 画像更新 -> 每日任务
            result.transitions.append((previous_stage, state.get("current_stage")))

    # ⑩ 本窗口计划是否已全部完成（滚动重排将在后续版本实现）
    if in_learning and not result.plan_created and result.task_created is None:
        result.plan_finished = is_plan_finished(state)

    # ⑪ 记录历史并落盘
    state["conversation_history"].append({"role": "user", "content": user_input})
    state["conversation_history"].append({"role": "assistant", "content": answer})
    save_state(state)

    result.stage_after = state.get("current_stage", "")

    # 一轮结束事件：用于按轮聚合（如 §8 护栏"平均每轮 LLM 调用次数"）
    metrics.record(
        metrics.EVENT_TURN,
        stage=result.stage_before,
        label=f"{result.stage_before}->{result.stage_after}",
        result="ok",
        verdict=None,
    )
    return result
