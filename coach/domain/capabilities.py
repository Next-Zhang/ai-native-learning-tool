"""能力注册表与阶段×能力矩阵（架构决策 2 / 5，见 `docs/architecture.md` §4 / §5）。

要解决的问题
------------
`coach/orchestration/turn.py` **曾**把 11 步的顺序**硬编码在控制流里**，于是
"加一个能力"必须改编排层，"换编排范式"必须重写控制流。本模块把
**哪些能力、在什么阶段、按什么顺序、读什么、写什么、要不要调模型、副作用多大**
变成**声明**；`orchestration/executor.py` 只按声明执行。

骨架槽位 vs 可插拔能力
----------------------
一轮里有 **4 个状态机推进点**（原 `turn.py` 的 ⑤ ⑧ ⑨，现固定在 `executor.py`），它们的位置是
**状态机契约的一部分（I-1），不可让渡**，因此固定在骨架（`SLOTS`）里，
**不**放进可插拔能力。能力只能挂进某个槽位，改动槽位顺序才是改骨架。

这样"加能力"= 加一条注册表记录 + 一个可调用对象（**不动 `turn.py`**），
而"改流程"仍然必须显式改骨架（应当难改）。
"""

from dataclasses import dataclass

from coach.domain.autonomy import Autonomy, is_declared, parse_autonomy
from coach.domain.confirmations import GATED_ACTIONS
from coach.domain.stages import ALL_STAGES

__all__ = [
    "ANY_STAGE",
    "Capability",
    "KINDS",
    "REGISTRY",
    "REGISTRY_BY_NAME",
    "SLOT_AFTER_DIALOGUE",
    "SLOT_CLOSING",
    "SLOT_DIALOGUE",
    "SLOT_EVALUATION_APPLY",
    "SLOT_INTAKE",
    "SLOT_STAGE_POST",
    "SLOT_STAGE_PRE",
    "SLOTS",
    "STAGE_SOURCE_LIVE",
    "STAGE_SOURCE_TURN_START",
    "capabilities_for",
    "select_capabilities",
    "validate_registry",
]

# ---------------------------------------------------------------------------
# 骨架槽位：顺序即执行顺序。推进点落在槽位之间/之内，由 executor 固定实现。
# ---------------------------------------------------------------------------

SLOT_INTAKE = "intake"                        # ① 画像抽取（早于一切）
SLOT_STAGE_PRE = "stage_pre"                  # ②③④ 阶段前置动作（写状态，让守卫满足）
SLOT_STAGE_POST = "stage_post"                # ⑥ 推进后的阶段动作（测评大纲）
SLOT_DIALOGUE = "dialogue"                    # ⑦ 与教练对话
SLOT_AFTER_DIALOGUE = "after_dialogue"        # ⑧ 对话后记账（测评判分/收尾）
SLOT_EVALUATION_APPLY = "evaluation_apply"    # ⑨ 应用判定（推进两次）
SLOT_CLOSING = "closing"                      # ⑩⑪ 收尾（窗口完成检查 + 落盘）

SLOTS = (
    SLOT_INTAKE,
    SLOT_STAGE_PRE,
    SLOT_STAGE_POST,
    SLOT_DIALOGUE,
    SLOT_AFTER_DIALOGUE,
    SLOT_EVALUATION_APPLY,
    SLOT_CLOSING,
)

ANY_STAGE = "*"

KINDS = ("perception", "planning", "evaluation", "memory", "dialogue", "tool", "teaching", "engagement")

#: 用**本轮起始阶段**（`stage_before`）选步骤，而不是当前阶段。
#: 只有"收尾检查"类能力需要它 —— 因为 `turn.py` 的 ⑩ 用的是推进**前**捕获的
#: `in_learning`。默认 `live`（当前阶段）。
STAGE_SOURCE_LIVE = "live"
STAGE_SOURCE_TURN_START = "turn_start"


# ---------------------------------------------------------------------------
# 声明契约
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Capability:
    """一个能力的声明卡片。

    `autonomy` 是**上限**：能力试图执行高于它的动作时由 `autonomy.ensure_allowed`
    抛 `AutonomyViolation`（不是降级执行）。
    """

    name: str
    kind: str
    slot: str
    stages: tuple[str, ...]        # ("*",) = 所有阶段
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    calls_llm: bool
    autonomy: str
    order: int                     # 槽位内的确定性顺序
    description: str = ""
    enabled: bool = True
    action_id: str | None = None   # danger 级能力必须给出（I-4）
    stage_source: str = STAGE_SOURCE_LIVE   # live | turn_start

    @property
    def level(self) -> Autonomy:
        return parse_autonomy(self.autonomy)

    def serves(self, stage: str) -> bool:
        return ANY_STAGE in self.stages or stage in self.stages

    def __str__(self) -> str:      # 便于测试失败时阅读
        return f"{self.name}[{self.slot}/{self.order}/{self.level.value}]"


# ---------------------------------------------------------------------------
# 注册表：**现有 14 条**（对应原 turn.py 的 11 步；S-12 的窗口滚动已落地）；
# **planned 7 条**是已确认方案的占位
# （enabled=False，不参与执行）
# ---------------------------------------------------------------------------

REGISTRY: tuple[Capability, ...] = (
    # ---- 现有 ----
    Capability(
        name="perception.profile_extract",
        kind="perception", slot=SLOT_INTAKE, stages=(ANY_STAGE,),
        reads=("learning_goal", "current_level", "session_minutes",
               "sessions_per_week", "target_date"),
        writes=("learning_goal", "current_level", "session_minutes",
                "sessions_per_week", "target_date"),
        calls_llm=True, autonomy=Autonomy.WRITE.value, order=10,
        description="从用户这句话里抽取画像四字段（空值不覆盖）；画像齐了就不再调",
    ),
    Capability(
        name="perception.plan_confirm",
        kind="perception", slot=SLOT_STAGE_PRE, stages=("planning",),
        reads=("current_window", "roadmap", "plan_progress", "plan_confirmed"),
        writes=("plan_confirmed",),
        calls_llm=True, autonomy=Autonomy.WRITE.value, order=20,
        description="判定用户是否确认了计划；判定失败保持等待，绝不误置确认标志",
    ),
    Capability(
        name="planning.plan_generate",
        kind="planning", slot=SLOT_STAGE_PRE, stages=("planning",),
        reads=("learning_goal", "current_level", "session_minutes",
               "sessions_per_week", "target_date", "weak_points",
               "skill_profile", "roadmap"),
        writes=("roadmap", "current_window", "plan_confirmed"),
        calls_llm=True, autonomy=Autonomy.WRITE.value, order=30,
        description=(
            "生成**路线图**（里程碑）+ **第一个执行窗口**；失败走确定性兜底，绝不空手"
        ),
    ),
    Capability(
        name="perception.submission_detect",
        kind="perception", slot=SLOT_STAGE_PRE, stages=("learning",),
        reads=("today_task", "pending_submission"),
        writes=("pending_submission",),
        calls_llm=True, autonomy=Autonomy.WRITE.value, order=40,
        description="判定用户是否提交了产出；失败保守处理，绝不把提问当提交",
    ),
    Capability(
        name="planning.daily_task_build",
        kind="planning", slot=SLOT_STAGE_PRE, stages=("learning",),
        reads=("current_window", "plan_progress", "today_task"),
        writes=("today_task", "plan_progress"),
        calls_llm=False, autonomy=Autonomy.WRITE.value, order=50,
        description="按游标取下一个任务（纯代码，不调模型）",
    ),
    Capability(
        name="evaluation.judge",
        kind="evaluation", slot=SLOT_STAGE_PRE, stages=("evaluation",),
        reads=("pending_submission", "today_task"),
        writes=("latest_result", "latest_result_applied"),
        calls_llm=True, autonomy=Autonomy.WRITE.value, order=60,
        description="结构化验收判定；失败保持 evaluation 且不写假判定",
    ),
    Capability(
        name="planning.assessment_outline",
        kind="planning", slot=SLOT_STAGE_POST, stages=("assessment",),
        reads=("skill_profile",),
        writes=("assessment_progress",),
        calls_llm=True, autonomy=Autonomy.WRITE.value, order=70,
        description="首次进入测评时生成 3~5 题大纲；失败用兜底大纲",
    ),
    Capability(
        name="dialogue.coach_reply",
        kind="dialogue", slot=SLOT_DIALOGUE, stages=(ANY_STAGE,),
        reads=(ANY_STAGE,),
        writes=(),
        calls_llm=True, autonomy=Autonomy.READ.value, order=80,
        description="教练回复；只读状态，不写任何 state 字段",
    ),
    Capability(
        name="perception.assessment_verdict",
        kind="perception", slot=SLOT_AFTER_DIALOGUE, stages=("assessment",),
        reads=("assessment_progress",),
        writes=("assessment_progress",),
        calls_llm=True, autonomy=Autonomy.WRITE.value, order=90,
        description="逐题判定 mastered/partial/missing；失败保守记 missing",
    ),
    Capability(
        name="memory.assessment_finalize",
        kind="memory", slot=SLOT_AFTER_DIALOGUE, stages=("assessment",),
        reads=("assessment_progress",),
        writes=("skill_profile", "weak_points", "assessment_progress"),
        calls_llm=False, autonomy=Autonomy.WRITE.value, order=100,
        description="测评收尾：纯代码聚合出能力画像与薄弱点",
    ),
    Capability(
        name="memory.profile_apply",
        kind="memory", slot=SLOT_EVALUATION_APPLY, stages=("evaluation",),
        reads=("latest_result",),
        writes=("skill_profile", "weak_points", "plan_progress",
                "latest_result_applied", "today_task", "pending_submission"),
        calls_llm=False, autonomy=Autonomy.WRITE.value, order=110,
        description=(
            "应用验收结论：平滑更新画像与游标，并推进 evaluation→learning"
            "（v0.16 合并了原 profile_update 阶段的两段式推进）"
        ),
    ),
    Capability(
        name="planning.window_finish_check",
        kind="planning", slot=SLOT_CLOSING, stages=("learning",),
        reads=("current_window", "plan_progress"),
        writes=(),
        calls_llm=False, autonomy=Autonomy.READ.value, order=120,
        stage_source=STAGE_SOURCE_TURN_START,
        description=(
            "判断本窗口是否已全部完成（**只读**）。"
            "用本轮起始阶段选步骤，与 turn.py 的 `in_learning` 快照语义一致"
        ),
    ),
    Capability(
        name="planning.window_roll",
        kind="planning", slot=SLOT_CLOSING, stages=("learning",),
        reads=("roadmap", "current_window", "plan_progress"),
        writes=("roadmap", "current_window", "plan_progress", "today_task",
                "pending_submission", "latest_result", "latest_result_applied"),
        calls_llm=True, autonomy=Autonomy.WRITE.value, order=125,
        description=(
            "[S-12] 窗口走完后按**实际速度重估**并滚动到下一里程碑（生成新窗口，"
            "含一次模型调用）；路线图已走完则不动作"
        ),
    ),
    Capability(
        name="memory.commit_history",
        kind="memory", slot=SLOT_CLOSING, stages=(ANY_STAGE,),
        reads=("conversation_history",),
        writes=("conversation_history",),
        calls_llm=False, autonomy=Autonomy.WRITE.value, order=130,
        description="记录本轮对话并落盘",
    ),

)

REGISTRY_BY_NAME: dict[str, Capability] = {cap.name: cap for cap in REGISTRY}


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

def capabilities_for(stage: str, slot: str | None = None) -> tuple[Capability, ...]:
    """取某阶段（可选限定槽位）**已启用**的能力，按 (槽位顺序, order) 升序。

    注意：这里按**单一阶段**过滤。若能力声明了 `stage_source="turn_start"`，
    执行器应改用 `select_capabilities()` —— 它会对每条能力分别取正确的阶段快照。
    """
    picked = [
        cap for cap in REGISTRY
        if cap.enabled and cap.serves(stage) and (slot is None or cap.slot == slot)
    ]
    picked.sort(key=lambda c: (SLOTS.index(c.slot), c.order))
    return tuple(picked)


def select_capabilities(
    stage_live: str, stage_turn_start: str, slot: str | None = None,
) -> tuple[Capability, ...]:
    """**执行器专用的选择**：按每条能力自己的 `stage_source` 取阶段快照。

    `live` 用当前阶段，`turn_start` 用本轮起始阶段 —— 后者对应 `turn.py` 里
    "推进前捕获 `in_learning`" 的行为。若统一用实时阶段，收尾检查会被跳过。
    """
    picked = [
        cap for cap in REGISTRY
        if cap.enabled
        and (slot is None or cap.slot == slot)
        and cap.serves(stage_turn_start if cap.stage_source == STAGE_SOURCE_TURN_START else stage_live)
    ]
    picked.sort(key=lambda c: (SLOTS.index(c.slot), c.order))
    return tuple(picked)


# ---------------------------------------------------------------------------
# 校验：把"声明写错"变成测试失败，而不是运行时惊喜
# ---------------------------------------------------------------------------

def validate_registry() -> tuple[str, ...]:
    """返回**问题清单**（空 = 通过）。规则见 `docs/architecture.md` §4.2。"""
    problems: list[str] = []
    seen_names: set[str] = set()
    seen_slot_order: dict[tuple[str, int], str] = {}

    for cap in REGISTRY:
        if not cap.name or "." not in cap.name:
            problems.append(f"{cap.name!r}: name 应形如 'kind.action'")
        if cap.name in seen_names:
            problems.append(f"{cap.name}: name 重复")
        seen_names.add(cap.name)

        if cap.kind not in KINDS:
            problems.append(f"{cap.name}: 未知 kind {cap.kind!r}")
        if cap.slot not in SLOTS:
            problems.append(f"{cap.name}: 未知 slot {cap.slot!r}")
        if cap.stage_source not in (STAGE_SOURCE_LIVE, STAGE_SOURCE_TURN_START):
            problems.append(f"{cap.name}: 未知 stage_source {cap.stage_source!r}")
        if not is_declared(cap.autonomy):
            problems.append(f"{cap.name}: autonomy 声明无效（{cap.autonomy!r}）—— 运行时会按 danger 处理")
        if not cap.stages:
            problems.append(f"{cap.name}: stages 不能为空（用 ('*',) 表示所有阶段）")
        for stage in cap.stages:
            if stage != ANY_STAGE and stage not in ALL_STAGES:
                problems.append(f"{cap.name}: 未知阶段 {stage!r}")

        key = (cap.slot, cap.order)
        if key in seen_slot_order:
            problems.append(
                f"{cap.name}: (slot={cap.slot}, order={cap.order}) 与 {seen_slot_order[key]} 冲突"
            )
        seen_slot_order[key] = cap.name

        if cap.enabled and cap.level is Autonomy.DANGER:
            if not cap.action_id:
                problems.append(f"{cap.name}: enabled 的 danger 能力必须声明 action_id（I-4）")
            elif cap.action_id not in GATED_ACTIONS:
                problems.append(f"{cap.name}: action_id {cap.action_id!r} 未在 GATED_ACTIONS 登记")

    # 每个阶段都必须至少有一个已启用能力服务，否则该阶段会静默空转
    for stage in ALL_STAGES:
        if not capabilities_for(stage):
            problems.append(f"阶段 {stage!r} 没有任何已启用能力")

    return tuple(problems)
