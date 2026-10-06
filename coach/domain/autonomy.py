"""三级自主权（架构决策 3，见 `docs/architecture.md` §6）。

级别与判定标准
--------------
| 级别 | 标准 | 是否需要确认 |
|---|---|---|
| `read` | 只读、或只写**派生且可重算**的状态 | 不需要 |
| `write` | 改变 **state 中影响后续行为**的字段 | 需**记录**；可逆则不必逐次确认 |
| `danger` | **不可逆**或影响用户长期权益 | **必须过确认门**（`coach.domain.confirmations`） |

两条不变量在此落地
------------------
- **I-4**：`danger` 级动作必须**已登记**（`GATED_ACTIONS`）；未登记 → `UnknownActionError`。
- **I-5**：**未声明一律按 `danger` 处理**（fail-closed）——新增能力若忘了写 `autonomy`，
  会被当作危险动作挡下来，而不是静默放行。

本模块是**纯逻辑**：不读输入、不落盘、不弹确认框。它只回答"这个能力有没有权限做这件事"；
真正的"问用户"由调用方通过 `confirmations.require_human_confirmation` 注入。
"""

from enum import Enum

from coach.domain.confirmations import get_action

__all__ = [
    "Autonomy",
    "AutonomyViolation",
    "DEFAULT_AUTONOMY",
    "LEVEL",
    "ensure_action_registered",
    "ensure_allowed",
    "ensure_within_ceiling",
    "exceeds",
    "is_declared",
    "parse_autonomy",
]


class Autonomy(str, Enum):
    """能力的副作用上限。"""

    READ = "read"
    WRITE = "write"
    DANGER = "danger"


#: 级别大小关系：数值越大副作用越强
LEVEL = {Autonomy.READ: 0, Autonomy.WRITE: 1, Autonomy.DANGER: 2}

#: **未声明时的默认值**——fail-closed（I-5）
DEFAULT_AUTONOMY = Autonomy.DANGER


class AutonomyViolation(PermissionError):
    """能力试图执行**超过自身授权级别**的动作。

    这是缺陷信号，不是用户可以"确认放行"的东西：授权级别不应由运行时协商，
    而应由 `coach/domain/capabilities.py` 的注册表声明。
    """


def is_declared(value) -> bool:
    """声明是否**有效**（拼错、乱填一律为 False）。

    与 `parse_autonomy` 的分工：
    - `parse_autonomy` 对无效声明**宽松**（返回 `danger`），保证运行时 fail-closed；
    - `is_declared` 供注册表校验**严格**报错，保证拼错的声明在测试里就被抓出来。
    """
    if isinstance(value, Autonomy):
        return True
    if not isinstance(value, str):
        return False
    return value.strip().lower() in {a.value for a in Autonomy}


def parse_autonomy(value) -> Autonomy:
    """把声明解析为级别；**缺失或无法识别一律返回 `danger`**（I-5）。"""
    if isinstance(value, Autonomy):
        return value
    if value is None:
        return DEFAULT_AUTONOMY
    text = str(value).strip().lower()
    if not text:
        return DEFAULT_AUTONOMY
    try:
        return Autonomy(text)
    except ValueError:
        return DEFAULT_AUTONOMY


def exceeds(ceiling, needed) -> bool:
    """`needed` 是否**超出** `ceiling` 允许的范围。"""
    return LEVEL[parse_autonomy(needed)] > LEVEL[parse_autonomy(ceiling)]


def ensure_within_ceiling(ceiling, needed, *, subject: str = "") -> Autonomy:
    """确认 `needed` 没有越过 `ceiling`；越级抛 `AutonomyViolation`。

    返回解析后的 `needed` 级别，便于调用方复用。
    """
    level = parse_autonomy(needed)
    if exceeds(ceiling, level):
        who = f"{subject} " if subject else ""
        raise AutonomyViolation(
            f"{who}授权上限为 {parse_autonomy(ceiling).value}，"
            f"不能执行 {level.value} 级动作"
        )
    return level


def ensure_action_registered(level, action_id: str | None) -> None:
    """`danger` 级动作必须给出**已登记**的 `action_id`（I-4）。

    - 级别低于 `danger` → 无需登记，直接返回
    - 级别为 `danger` 但未给 `action_id` → `AutonomyViolation`（无法审计的动作不允许执行）
    - `action_id` 未登记 → `UnknownActionError`（由 `confirmations.get_action` 抛出）
    """
    if parse_autonomy(level) is not Autonomy.DANGER:
        return
    if not action_id:
        raise AutonomyViolation("danger 级动作必须提供已登记的 action_id（否则无法审计）")
    get_action(action_id)          # 未登记 → UnknownActionError


def ensure_allowed(ceiling, needed, *, action_id: str | None = None, subject: str = "") -> Autonomy:
    """组合检查：**先看级别、再看到底是哪个动作**。

    这是能力执行前的唯一入口。两步都过才算放行。
    """
    level = ensure_within_ceiling(ceiling, needed, subject=subject)
    ensure_action_registered(level, action_id)
    return level
