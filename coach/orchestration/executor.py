"""按【阶段×能力矩阵】驱动一轮执行（架构决策 5，见 `docs/architecture.md` §5）。

骨架 vs 能力
------------
一轮里有 **3 个状态机推进点**（原 `turn.py` 的 ⑤ ⑧ ⑨）。它们的位置属于
**状态机契约（I-1）**，不可让渡，因此固定在骨架里：

```
for slot in SLOTS:                     # ← 骨架（改它 = 改流程）
    for cap in selector.select(...):   # ← 可插拔（加它 = 不动骨架）
        precondition? → 权限检查 → 执行
    if slot == stage_pre: 推进 #1       # ← 骨架推进点
```

推进 #2（测评收尾）与 #3（应用判定）是**条件性**的，由对应能力自己负责
（它们是那两个能力的语义的一部分），因此写在 handler 里。

行为等价性
----------
本模块是对原 `turn.py` ① – ⑪ 的**逐字转写**，不是重新设计：
每个 `PRECONDITIONS` 条目和 `HANDLERS` 条目都能对上原来的一行。
等价性由 `tests/test_dialogue.py`（消息装配与阶段选择）与
`tests/test_capabilities.py`（注册表完整性）共同把关。

字段快照语义
------------
`turn.py` 在不同位置取的是**不同的阶段快照**：③ 用推进前的阶段算 `in_learning`，
⑥ 用推进后的阶段。注册表的 `stage_source` 精确表达了这一点（`live` / `turn_start`）。
"""

from dataclasses import dataclass, field
from typing import Any, Callable

from coach.domain.assessment_rules import finalize, is_finished
from coach.domain.autonomy import ensure_action_registered
from coach.domain.capabilities import (
    REGISTRY,
    SLOT_STAGE_PRE,
    SLOTS,
    Capability,
    select_capabilities,
)
from coach.domain import memory
from coach.domain.cursor import build_today_task, is_plan_finished
from coach.domain.profile_rules import merge_profile, profile_complete
from coach.domain.stages import try_advance
from coach.metrics import recorder as metrics
from coach.services import assessment, daily_task, evaluation, planning, profile
from coach.services.memory import summarize_cycle, summarize_progress
from coach.services.coach import chat_with_coach
from coach.storage.state_store import save_state

__all__ = [
    "HANDLERS",
    "PRECONDITIONS",
    "MatrixSelector",
    "TurnContext",
    "TurnResult",
    "execute_slots",
    "missing_handlers",
]


# ---------------------------------------------------------------------------
# 对外契约（界面层只读它）
# ---------------------------------------------------------------------------

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

    # 学习任务
    task_created: dict | None = None
    submission: Any = None

    # 验收与画像更新
    evaluation_result: Any = None
    update_summary: dict | None = None

    # 本窗口计划是否已全部完成
    plan_finished: bool = False

    # 本窗口是否已滚动到下一里程碑（S-12）
    window_rolled: bool = False

    @property
    def image_fields_updated(self) -> bool:
        return bool(self.updated_fields)


@dataclass
class TurnContext:
    """一次执行的全部输入与中间量（**不含隐藏全局状态**，便于将来做轮边界快照）。"""

    state: dict
    user_input: str
    use_rag: bool = False
    result: TurnResult = None                     # 在 __post_init__ 里补
    stage_before: str = ""
    answer: str = ""

    def __post_init__(self) -> None:
        # 顺序要紧：**先**把 stage_before 落到 state 的真实阶段上，**再**据此装配 result。
        # 反过来的话（旧实现），调用方不显式传 stage_before 时 `ctx.result.stage_before`
        # 会是空字符串，而 `ctx.stage_before` 却是真实阶段 —— 展示与指标的阶段归属会自相矛盾。
        if not self.stage_before:
            self.stage_before = self.state.get("current_stage", "")
        if self.result is None:
            self.result = TurnResult(user_input=self.user_input, stage_before=self.stage_before)

    @property
    def stage(self) -> str:
        """当前阶段（**实时**，可能已被本轮推进改变）。"""
        return self.state.get("current_stage", "")


# ---------------------------------------------------------------------------
# 选择器（策略）：今天＝矩阵；将来可换 hybrid，见 architecture.md §5.2
# ---------------------------------------------------------------------------

class MatrixSelector:
    """按注册表的【阶段×能力矩阵】选步骤。**当前唯一实现**（等价于原硬编码顺序）。"""

    name = "matrix"

    def select(self, ctx: TurnContext, slot: str) -> tuple[Capability, ...]:
        return select_capabilities(ctx.stage, ctx.stage_before, slot=slot)

def _ensure_executable(cap: Capability) -> None:
    """执行前的固定检查：danger 级能力必须带**已登记**的 action_id（I-4）。"""
    ensure_action_registered(cap.level, cap.action_id)


# ---------------------------------------------------------------------------
# 推进（状态机是唯一推进来源 —— I-1，不在这里判断"能不能"，只负责调用与记录）
# ---------------------------------------------------------------------------

def _advance(ctx: TurnContext) -> bool:
    before = ctx.stage
    if try_advance(ctx.state):
        ctx.result.transitions.append((before, ctx.stage))
        return True
    return False


# ---------------------------------------------------------------------------
# 前置条件（与 handlers 一一对应；对不上就是漏步骤）
# ---------------------------------------------------------------------------

PRECONDITIONS: dict[str, Callable[[TurnContext], bool]] = {
    # ① 画像：画像齐了就不再调（避免每轮空跑 —— 实测占 1/3 调用量）
    "perception.profile_extract": lambda ctx: not profile_complete(ctx.state),
    # ② 计划：先判"用户是否确认"，再确保计划生成
    "perception.plan_confirm": lambda ctx: (
        bool(ctx.state.get("current_window")) and not planning.is_confirmed(ctx.state)
    ),
    "planning.plan_generate": lambda ctx: True,
    # ③ 学习任务：先判"是否提交"，再准备今日任务
    "perception.submission_detect": lambda ctx: (
        bool(ctx.state.get("today_task")) and not ctx.state.get("pending_submission")
    ),
    "planning.daily_task_build": lambda ctx: not ctx.state.get("today_task"),
    # ④ 验收：有提交且尚未判定时才判
    "evaluation.judge": lambda ctx: bool(ctx.state.get("pending_submission")),
    # ⑥ 测评：首次进入先生成大纲
    "planning.assessment_outline": lambda ctx: True,
    # ⑦ 对话：总是执行
    "dialogue.coach_reply": lambda ctx: True,
    # ⑧ 测评记账：只有"题目已经提出"时才记本轮作答
    "perception.assessment_verdict": lambda ctx: not ctx.result.assessment_plan_created,
    "memory.assessment_finalize": lambda ctx: (
        not ctx.result.assessment_plan_created and is_finished(ctx.state)
    ),
    # ⑨ 应用判定：只有本轮真的产出了判定
    "memory.profile_apply": lambda ctx: ctx.result.evaluation_result is not None,
    # ⑩ 窗口完成检查（阶段由 stage_source=turn_start 保证）
    "planning.window_finish_check": lambda ctx: (
        not ctx.result.plan_created and ctx.result.task_created is None
    ),
    # ⑩b 滚动：只有窗口**真的走完**才滚动（roll_window 内部还会再确认一次）
    "planning.window_roll": lambda ctx: is_plan_finished(ctx.state),
    # ⑩c L1 滚动摘要（v0.18）：只有"装不下"的原文攒够门槛时才值得花一次模型调用
    "memory.condense_progress": lambda ctx: bool(_droppable_messages(ctx.state)),
    # ⑩d L2 定稿摘要（v0.18）：刚跨过一次单次学习边界、且那一次还没定稿
    "memory.condense_cycle": lambda ctx: memory.pending_cycle_seq(ctx.state) is not None,
    # ⑪ 落盘：总是执行
    "memory.commit_history": lambda ctx: True,
}


# ---------------------------------------------------------------------------
# 执行体（与原 turn.py 逐行对应）
# ---------------------------------------------------------------------------

def _h_profile_extract(ctx: TurnContext) -> None:
    ctx.result.updated_fields = merge_profile(ctx.state, profile.extract_profile(ctx.user_input))


def _h_plan_confirm(ctx: TurnContext) -> None:
    ctx.result.confirmation = planning.confirm_plan(ctx.state, ctx.user_input)


def _h_plan_generate(ctx: TurnContext) -> None:
    ctx.result.plan_created = planning.ensure_plan(ctx.state)


def _h_window_roll(ctx: TurnContext) -> None:
    """[S-12] 窗口走完 → 滚动到下一里程碑，按**实际速度重估**后续估计。"""
    ctx.result.window_rolled = planning.roll_window(ctx.state)


def _h_submission_detect(ctx: TurnContext) -> None:
    ctx.result.submission = daily_task.detect_submission(ctx.state, ctx.user_input)


def _h_daily_task_build(ctx: TurnContext) -> None:
    ctx.result.task_created = build_today_task(ctx.state)


def _h_judge(ctx: TurnContext) -> None:
    ctx.result.evaluation_result = evaluation.evaluate(ctx.state)


def _h_assessment_outline(ctx: TurnContext) -> None:
    ctx.result.assessment_plan_created = assessment.ensure_plan(ctx.state)
    if ctx.result.assessment_plan_created:
        plan_questions = (ctx.state.get("assessment_progress") or {}).get("plan") or []
        ctx.result.assessment_topics = [q.get("topic", "") for q in plan_questions]


def _h_coach_reply(ctx: TurnContext) -> None:
    # 传 **stage_before**：状态机在本轮可能已推进，但教练仍应按**本轮起始阶段**说话，
    # 否则它会抢在代码判定之前自己宣布验收结论（**I-2 / X-16**）。
    answer, sources = chat_with_coach(
        user_input=ctx.user_input,
        history=ctx.state["conversation_history"],
        use_rag=ctx.use_rag,
        state=ctx.state,
        stage=ctx.stage_before,
    )
    ctx.answer = answer
    ctx.result.answer = answer
    ctx.result.sources = sources


def _h_assessment_verdict(ctx: TurnContext) -> None:
    ctx.result.record = assessment.record_answer(ctx.state, ctx.user_input, ctx.answer)


def _h_assessment_finalize(ctx: TurnContext) -> None:
    ctx.result.summary = finalize(ctx.state)
    _advance(ctx)                      # 骨架推进点 #2：assessment -> planning


def _h_profile_apply(ctx: TurnContext) -> None:
    """应用验收结论，并推进 evaluation → learning。

    **v0.16**：原先是"推进 #3 → 应用 → 推进 #4"两步（经过 `profile_update` 阶段）。
    该阶段已删除，现在应用完再推进一步即可；守卫 `_guard_update_applied`
    保证"没应用完就不会推进"。
    """
    ctx.result.update_summary = evaluation.apply_update(ctx.state)
    _advance(ctx)                      # 骨架推进点 #3：evaluation -> learning


def _h_window_finish_check(ctx: TurnContext) -> None:
    ctx.result.plan_finished = is_plan_finished(ctx.state)


#: 原始对话日志的条数上限（**它不是注入量**）—— 约两次单次学习的量。
#: 注入量另由 `memory.select_history` 按**字符预算**决定（docs/memory-design.md §6.1）。
HISTORY_MAX_MESSAGES = memory.HISTORY_MAX_MESSAGES


def trim_history(state) -> int:
    """把超出**日志上限**的对话移进**按单次学习分段**的归档；返回**被丢弃的消息条数**。

    v0.18 改了三处（见 docs/memory-design.md §8.2 / I-13）：

    1. 上限从"注入窗口 8 条"改成"日志上限"。**注入量不再由它决定** ——
       8 条 = 4 轮 ≈ 最近十几分钟，对一次 2 小时的学习太小了。
    2. 归档按**单次学习分段**，于是"保留最近 N 次学习的原文"才可实现。
    3. 丢弃**必须留痕**：返回值就是被丢掉的消息条数，调用方负责记指标事件。
       改造前是 `del archive[:-500]` —— 静默丢弃，用户永远不知道少了什么。
    """
    history = state.get("conversation_history") or []
    if len(history) <= HISTORY_MAX_MESSAGES:
        return 0
    overflow = history[:-HISTORY_MAX_MESSAGES]
    state["conversation_history"] = history[-HISTORY_MAX_MESSAGES:]

    memory.append_to_archive(state, overflow)
    return memory.prune_archive(state)


def _droppable_messages(state) -> list:
    """筛出"该折进滚动摘要"的较早原文（L1 的触发判据）。

    用**回压比例**而不是满预算：满预算意味着"压完之后立刻又满了"，
    于是每轮都要多一次模型调用 —— 那是成本灾难（PRD §8 护栏）。
    另外要求至少攒够 `L1_MIN_DROPPED` 条，避免为两三条消息白调一次。
    """
    history = state.get("conversation_history") or []
    budget = int(memory.INJECT_CHAR_BUDGET * memory.L1_TARGET_RATIO)
    kept = memory.select_history(history, budget=budget,
                                 min_messages=memory.MIN_RAW_MESSAGES)
    cut = max(0, len(history) - len(kept))
    if cut < memory.L1_MIN_DROPPED:
        return []
    return history[:cut]


def _h_condense_progress(ctx: TurnContext) -> None:
    """**L1 滚动摘要**：较早的原文 → 折进 `rolling_summary`，原文进归档。

    只从**注入**里移出，原文仍留在归档（不删数据）；摘要**替换**而不是追加，
    否则摘要自己也会线性增长（见 docs/memory-design.md §6.2）。
    """
    dropped = _droppable_messages(ctx.state)
    if not dropped:
        return
    previous = ctx.state.get("rolling_summary") or ""
    ctx.state["rolling_summary"] = summarize_progress(ctx.state, dropped, previous)

    history = ctx.state.get("conversation_history") or []
    ctx.state["conversation_history"] = history[len(dropped):]
    memory.append_to_archive(ctx.state, dropped)


def _h_condense_cycle(ctx: TurnContext) -> None:
    """**L2 定稿摘要**：每次单次学习结束压一条，并留下结构化记录。

    幂等靠**顶层** `state["condensed_through_seq"]`（不放在游标里 —— 窗口滚动会重置游标）；
    定稿后滚动摘要清空，
    且定稿摘要**只追加、永不参与 L1 压缩**（避免层层失真，§6.2）。
    """
    seq = memory.pending_cycle_seq(ctx.state)
    if seq is None:
        return

    skeleton = memory.current_cycle_skeleton(ctx.state, seq)
    text = summarize_cycle(ctx.state, seq, skeleton)
    memory.record_cycle_summary(ctx.state, seq, text, skeleton.get("topics"))
    memory.upsert_session_record(
        ctx.state, seq,
        tasks_done=skeleton.get("tasks"),
        topics=skeleton.get("topics"),
        errors=skeleton.get("errors"),
        attempts=skeleton.get("attempts"),
        summary=text,
    )
    memory.mark_cycle_condensed(ctx.state, seq)
    ctx.state["rolling_summary"] = None          # 已定稿，滚动摘要清空


def _h_commit_history(ctx: TurnContext) -> None:
    ctx.state["conversation_history"].append({"role": "user", "content": ctx.user_input})
    ctx.state["conversation_history"].append({"role": "assistant", "content": ctx.answer})

    dropped = trim_history(ctx.state)
    if dropped:
        # **I-13：归档不是黑洞** —— 丢掉多少必须留痕，否则"窗口化"就是静默的截断。
        metrics.record(metrics.EVENT_ARCHIVE_PRUNED,
                       label=f"dropped={dropped}", result="pruned")

    save_state(ctx.state)


HANDLERS: dict[str, Callable[[TurnContext], None]] = {
    "perception.profile_extract": _h_profile_extract,
    "perception.plan_confirm": _h_plan_confirm,
    "planning.plan_generate": _h_plan_generate,
    "perception.submission_detect": _h_submission_detect,
    "planning.daily_task_build": _h_daily_task_build,
    "evaluation.judge": _h_judge,
    "planning.assessment_outline": _h_assessment_outline,
    "dialogue.coach_reply": _h_coach_reply,
    "perception.assessment_verdict": _h_assessment_verdict,
    "memory.assessment_finalize": _h_assessment_finalize,
    "memory.profile_apply": _h_profile_apply,
    "planning.window_finish_check": _h_window_finish_check,
    "planning.window_roll": _h_window_roll,
    "memory.condense_progress": _h_condense_progress,
    "memory.condense_cycle": _h_condense_cycle,
    "memory.commit_history": _h_commit_history,
}


def missing_handlers() -> tuple[str, ...]:
    """已启用、却没写 handler 或 precondition 的能力（注册表校验的一部分）。"""
    gaps = []
    for cap in REGISTRY:
        if not cap.enabled:
            continue
        if cap.name not in HANDLERS:
            gaps.append(f"{cap.name}: 缺少 handler")
        if cap.name not in PRECONDITIONS:
            gaps.append(f"{cap.name}: 缺少 precondition")
    return tuple(gaps)


# ---------------------------------------------------------------------------
# 骨架：按槽位执行
# ---------------------------------------------------------------------------

def execute_slots(ctx: TurnContext, selector=None) -> None:
    """按 `SLOTS` 顺序执行；`stage_pre` 之后固定推进一次（骨架推进点 #1）。"""
    selector = selector or MatrixSelector()
    for slot in SLOTS:
        for cap in selector.select(ctx, slot):
            if not PRECONDITIONS[cap.name](ctx):
                continue
            _ensure_executable(cap)
            HANDLERS[cap.name](ctx)
        if slot == SLOT_STAGE_PRE:
            _advance(ctx)
