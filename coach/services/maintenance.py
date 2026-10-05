"""维护类用例：带确认门的不可逆操作（PRD **S-08**）。

`perform_reset` 是**唯一**允许删除学习历史的代码路径：
先过 `coach.domain.confirmations.require_human_confirmation`，
**被拒绝或超时则完全不改动 state、也不落盘**。

`confirm_fn` 由调用方注入（CLI 用 `input()`，测试用假函数），因此本模块可单测。
"""

import json
from dataclasses import dataclass
from pathlib import Path

from coach.domain import confirmations
from coach.domain.confirmations import ActionId, ConfirmationDecision
from coach.domain.state_schema import DEFAULT_STATE
from coach.metrics import recorder as metrics
from coach.storage import reset as reset_store
from coach.storage.reset import BACKUP_DIR
from coach.storage.state_store import STATE_FILE

SCOPE_HISTORY = "history"
SCOPE_ALL = "all"

_SCOPE_DETAIL = {
    SCOPE_HISTORY: "仅对话历史（画像 / 计划 / 阶段 / 进度保留）",
    SCOPE_ALL: "全部学习状态（画像 / 计划 / 进度 / 对话历史）",
}

__all__ = ["SCOPE_ALL", "SCOPE_HISTORY", "ResetOutcome", "perform_reset"]


@dataclass
class ResetOutcome:
    """一次（可能被取消的）重置操作的结果。"""

    executed: bool
    scope: str
    decision: ConfirmationDecision
    message: str
    cleared: int = 0
    backup_path: Path | None = None


def perform_reset(
    state,
    scope: str,
    confirm_fn,
    *,
    state_file: Path = STATE_FILE,
    backup_dir: Path = BACKUP_DIR,
) -> ResetOutcome:
    """经确认后清空对话历史（scope=history）或完全重置（scope=all）。

    被拒绝 / 超时 / 确认异常 → 直接返回 `executed=False`，**state 保持原样**。
    """
    if scope not in _SCOPE_DETAIL:
        raise ValueError(f"未知范围：{scope!r}（可选：{SCOPE_HISTORY} / {SCOPE_ALL}）")

    decision = confirmations.require_human_confirmation(
        ActionId.DELETE_HISTORY.value,
        confirm_fn,
        detail=_SCOPE_DETAIL[scope],
    )

    # 人机介入的可观测性（S-08）：无论放行与否都记一条
    metrics.record(
        metrics.EVENT_CONFIRMATION,
        label=ActionId.DELETE_HISTORY.value,
        result=decision.outcome.value,
    )

    if not decision.allowed:
        # 关键：不动 state、不落盘
        return ResetOutcome(
            False, scope, decision, f"[已取消] 未删除任何数据（{decision.reason}）"
        )

    if scope == SCOPE_HISTORY:
        cleared = reset_store.clear_history(state)
        reset_store.save_to(state, state_file)
        return ResetOutcome(
            True, scope, decision,
            f"[记忆] 已清空当前对话历史（{cleared} 条）；画像 / 计划 / 阶段保留",
            cleared=cleared,
        )

    backup = reset_store.backup_state(state_file, backup_dir)
    # 深拷贝默认状态：否则 state 会与 DEFAULT_STATE 共享同一批可变对象，
    # 后续写入会污染默认值（旧 CLI 的 `/reset all` 正是直接 state.update(DEFAULT_STATE)）。
    state.clear()
    state.update(json.loads(json.dumps(DEFAULT_STATE)))
    reset_store.save_to(state, state_file)

    message = "[记忆] 已完全重置（回到目标澄清）"
    if backup:
        message += f"，旧状态备份于 {backup.name}"
    return ResetOutcome(True, scope, decision, message, backup_path=backup)
