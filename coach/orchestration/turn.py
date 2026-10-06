"""单轮流程编排（**薄壳**：真正的执行在 `coach/orchestration/executor.py`）。

本模块只做三件事：

1. 装配 `TurnContext`（本轮起始阶段 + 指标归属）
2. 调 `executor.execute_slots()`
3. 记录"一轮结束"事件并返回 `TurnResult`

**流程顺序不在这里**——它在 `coach/domain/capabilities.py` 的注册表里，
由 `executor` 按骨架槽位驱动：

- **要加能力** → 改注册表 + 写 handler（不动本文件）
- **要改流程** → 改骨架槽位（应当难改）

设计依据见 `docs/architecture.md` §5。本文件从 11 步硬编码改写而来，
行为由 `tests/test_dialogue.py` 与 `tests/test_capabilities.py` 共同锁定。
"""

from coach.metrics import recorder as metrics
from coach.orchestration.executor import TurnContext, TurnResult, execute_slots

__all__ = ["TurnResult", "run_turn"]


def run_turn(state, user_input: str, use_rag: bool = False, *, selector=None) -> TurnResult:
    """执行一轮完整流程，返回结果并落盘。

    `state` 会被**原地修改**（与旧 `app.py` 行为一致）。

    `selector` 可注入替代的步骤选择策略（默认 `MatrixSelector`）——
    这是将来升级为 hybrid 编排的唯一入口，见 `architecture.md` §5.2。
    """
    ctx = TurnContext(
        state=state,
        user_input=user_input,
        use_rag=use_rag,
        stage_before=state.get("current_stage", ""),
    )

    # 指标归属：本轮内的 LLM 调用都记在本轮**起始阶段**下（近似但足够定位）
    metrics.set_stage(ctx.stage_before)

    execute_slots(ctx, selector=selector)

    result = ctx.result
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
