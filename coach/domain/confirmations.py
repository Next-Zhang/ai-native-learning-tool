"""不可逆动作的人工确认门（PRD **S-08** / §3.4 人工介入）。

背景
----
四类动作**必须经用户明确确认**才允许执行：**重建计划、修改长期目标、删除学习历史、标记技能已掌握**。
此前只有提示词层"要求"（`coach.prompts.stages` 的 profile_update 阶段文本），
**模型可以不遵守**——这不是强制。本模块把它变成**代码强制**。

语义：**fail-closed（默认拒绝）**
- 用户拒绝 → 不执行
- 超时 / 无应答 / 确认过程异常 → 不执行
- **未知 action_id → 直接抛错**：新增不可逆动作若忘了登记，会在调用点炸掉，
  而不是静默放行（防止绕过）

本模块是**纯逻辑**：不读输入、不落盘。"问用户"由调用方以 `confirm_fn` 注入
（CLI 用 `input()`，测试用假函数），因此完全可单测。
"""

from dataclasses import dataclass
from enum import Enum


class ActionId(str, Enum):
    """受门保护的不可逆动作。"""

    REBUILD_PLAN = "rebuild_plan"
    CHANGE_LEARNING_GOAL = "change_learning_goal"
    DELETE_HISTORY = "delete_history"
    MARK_SKILL_MASTERED = "mark_skill_mastered"


class ConfirmationOutcome(str, Enum):
    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"


class UnknownActionError(KeyError):
    """未登记的动作 —— 不允许执行，也不允许静默放行。"""


@dataclass(frozen=True)
class GatedAction:
    """一个需要人工确认的动作。"""

    action_id: str
    label: str          # 中文名（给用户看）
    description: str    # 将要做什么
    consequence: str    # 不可逆后果


GATED_ACTIONS: dict[str, GatedAction] = {
    ActionId.REBUILD_PLAN.value: GatedAction(
        action_id=ActionId.REBUILD_PLAN.value,
        label="重建学习计划",
        description="丢弃当前 7 天滚动计划，重新生成一份新计划",
        consequence="未完成的旧任务与当前游标进度将失效",
    ),
    ActionId.CHANGE_LEARNING_GOAL.value: GatedAction(
        action_id=ActionId.CHANGE_LEARNING_GOAL.value,
        label="修改长期学习目标",
        description="改写你的长期学习目标（或大幅调整期望期限）",
        consequence="后续计划与验收口径都会按新目标重来，旧目标的进度不再适用",
    ),
    ActionId.DELETE_HISTORY.value: GatedAction(
        action_id=ActionId.DELETE_HISTORY.value,
        label="删除学习历史",
        description="删除学习记录（可含画像、计划、进度与对话历史）",
        consequence="删除后无法从应用内恢复（本机备份仅保留最近 5 份状态文件）",
    ),
    ActionId.MARK_SKILL_MASTERED.value: GatedAction(
        action_id=ActionId.MARK_SKILL_MASTERED.value,
        label="标记技能为已掌握",
        description="把某项技能直接标记为“已掌握”，跳过验收",
        consequence="该技能将不再出现在薄弱点与后续练习中，绕过“以验收为准”的原则",
    ),
}


def get_action(action_id: str) -> GatedAction:
    """取动作定义；未登记则抛 UnknownActionError（fail-closed）。"""
    try:
        return GATED_ACTIONS[action_id]
    except KeyError:
        raise UnknownActionError(
            f"动作未登记，拒绝执行：{action_id!r}（已登记：{'、'.join(sorted(GATED_ACTIONS))}）"
        ) from None


def build_prompt(action_id: str, detail: str = "") -> str:
    """构造给用户看的确认提示。"""
    action = get_action(action_id)
    lines = [
        f"【需要你确认】{action.label}",
        f"将要执行：{action.description}",
    ]
    if detail:
        lines.append(f"本次范围：{detail}")
    lines.append(f"不可逆后果：{action.consequence}")
    lines.append("（拒绝或未明确确认，系统都不会执行该操作）")
    return "\n".join(lines)


@dataclass(frozen=True)
class ConfirmationDecision:
    """确认结果。`allowed` 是唯一的放行依据。"""

    action_id: str
    outcome: ConfirmationOutcome
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.outcome is ConfirmationOutcome.APPROVED

    def __bool__(self) -> bool:
        return self.allowed


def require_human_confirmation(action_id: str, confirm_fn, *, detail: str = "") -> ConfirmationDecision:
    """同步要求人工确认；返回是否放行。

    `confirm_fn(prompt) -> bool | None`：
    - 返回 `True`  → 已确认
    - 返回 `False` → 已拒绝
    - 返回 `None`  → 超时 / 无应答 → 按不执行处理
    - 抛异常       → 按不执行处理（fail-closed）

    未知 `action_id` 直接抛 `UnknownActionError`。
    """
    get_action(action_id)                     # 先校验，未登记的动作不进确认流程
    prompt = build_prompt(action_id, detail)

    if not callable(confirm_fn):
        raise TypeError("confirm_fn 必须是可调用对象")

    try:
        answer = confirm_fn(prompt)
    except Exception as exc:                  # noqa: BLE001 —— 确认过程出错必须默认拒绝
        return ConfirmationDecision(
            action_id,
            ConfirmationOutcome.TIMEOUT,
            f"确认过程异常，按未确认处理（{type(exc).__name__}）",
        )

    if answer is True:
        return ConfirmationDecision(action_id, ConfirmationOutcome.APPROVED, "用户已确认")
    if answer is False:
        return ConfirmationDecision(action_id, ConfirmationOutcome.DENIED, "用户已拒绝")
    return ConfirmationDecision(
        action_id,
        ConfirmationOutcome.TIMEOUT,
        "未获得明确确认（超时或无应答），按不执行处理",
    )
