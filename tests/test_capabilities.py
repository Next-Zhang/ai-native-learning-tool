r"""能力注册表与三级授权的测试（架构决策 2 / 3 / 5）。

运行（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\test_capabilities.py

这些用例把 `docs/architecture.md` 的声明规则**变成可执行断言**，
其中两条是"把不变量固定在结构上"的关键：

- **I-9**：`engagement.*` 能力**不得写任何判定字段**（趣味化不能污染验收信号）
- **I-10**：验收档位由代码决定，模型不得降档（档位参数见 `evaluation_rules`）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.domain.autonomy import (
    DEFAULT_AUTONOMY,
    Autonomy,
    AutonomyViolation,
    ensure_action_registered,
    ensure_allowed,
    ensure_within_ceiling,
    exceeds,
    is_declared,
    parse_autonomy,
)
from coach.domain.capabilities import (
    ANY_STAGE,
    REGISTRY,
    REGISTRY_BY_NAME,
    SLOT_CLOSING,
    SLOT_INTAKE,
    SLOTS,
    capabilities_for,
    validate_registry,
)
from coach.domain.confirmations import GATED_ACTIONS, UnknownActionError
from coach.domain.stages import ALL_STAGES

# 判定字段：任何"趣味化/反馈"类能力都不许写（I-9）
JUDGEMENT_FIELDS = frozenset({
    "latest_result", "skill_profile", "weak_points",
    "plan_progress", "assessment_progress",
})

# 现有 13 条 = turn.py 的 11 步（显式化前必须先钉住，否则重构会静默漏步）
EXPECTED_EXISTING = frozenset({
    "perception.profile_extract",
    "perception.plan_confirm",
    "planning.plan_generate",
    "perception.submission_detect",
    "planning.daily_task_build",
    "evaluation.judge",
    "planning.assessment_outline",
    "dialogue.coach_reply",
    "perception.assessment_verdict",
    "memory.assessment_finalize",
    "memory.profile_apply",
    "planning.window_finish_check",
    "planning.window_roll",
    "memory.commit_history",
})


# ---------------------------------------------------------------------------
# 1) 注册表自身的完整性
# ---------------------------------------------------------------------------

def test_registry_has_no_problems():
    problems = validate_registry()
    assert problems == (), "注册表校验未通过：\n  - " + "\n  - ".join(problems)


def test_existing_registry_matches_turn_steps():
    """钉住能力集合 —— 与阶段流程一一对应。

    v0.16 起注册表里**不再有 planned 占位**（未实现的功能不该占位），
    因此这里直接断言全部能力。
    """
    names = {c.name for c in REGISTRY}
    assert names == EXPECTED_EXISTING, (
        f"多出={sorted(names - EXPECTED_EXISTING)} 缺少={sorted(EXPECTED_EXISTING - names)}"
    )


def test_registry_names_unique_and_indexed():
    """契约钉桩：只断言注册表的名字唯一且索引一致，**只防误删、不证明行为**。"""
    names = [c.name for c in REGISTRY]
    assert len(names) == len(set(names))
    assert set(REGISTRY_BY_NAME) == set(names)


def test_every_stage_has_enabled_capabilities():
    for stage in ALL_STAGES:
        assert capabilities_for(stage), f"阶段 {stage} 没有任何已启用能力"


def test_capabilities_for_sorts_by_slot_then_order():
    picked = capabilities_for("planning")
    keys = [(SLOTS.index(c.slot), c.order) for c in picked]
    assert keys == sorted(keys), f"排序不符：{keys}"


def test_capabilities_for_filters_by_slot():
    intake = capabilities_for("planning", slot=SLOT_INTAKE)
    assert [c.name for c in intake] == ["perception.profile_extract"]

    closing = capabilities_for("learning", slot=SLOT_CLOSING)
    assert [c.name for c in closing] == [
        "planning.window_finish_check", "planning.window_roll", "memory.commit_history",
    ]


def test_global_capabilities_serve_every_stage():
    global_names = {c.name for c in REGISTRY if c.enabled and ANY_STAGE in c.stages}
    assert "dialogue.coach_reply" in global_names
    assert "memory.commit_history" in global_names
    for stage in ALL_STAGES:
        served = {c.name for c in capabilities_for(stage)}
        assert global_names <= served, f"阶段 {stage} 缺少全局能力"


# ---------------------------------------------------------------------------
# 2) 结构化的不变量（比文档更硬）
# ---------------------------------------------------------------------------

def test_engagement_cannot_touch_judgement_fields():
    """**I-9**：趣味化只作用于反馈层，不得写任何判定字段。

    v0.16 删除了 `engagement.*` 的**占位能力**（未实现的功能不该在注册表里占位）。
    本用例在 S-15 落地后**必须重新生效**，因此保留断言逻辑，当前无对象时显式跳过。
    """
    engagement = [c for c in REGISTRY if c.kind == "engagement"]
    if not engagement:
        raise SkipTest("S-15 未实现，暂无 engagement 能力可校验（落地后必须恢复）")
    for cap in engagement:
        overlap = set(cap.writes) & JUDGEMENT_FIELDS
        assert not overlap, f"{cap.name} 会写判定字段 {sorted(overlap)}，违反 I-9"
        assert cap.level is Autonomy.READ, f"{cap.name} 必须是 read 级（只产反馈文本）"


def test_dialogue_reply_is_read_only():
    """教练回复不写 state —— 状态只能由能力按声明写（防止隐式污染）。"""
    cap = REGISTRY_BY_NAME["dialogue.coach_reply"]
    assert cap.writes == ()
    assert cap.level is Autonomy.READ


def test_enabled_danger_capabilities_have_registered_action():
    """契约钉桩：断言"已启用的 danger 能力必须登记 action_id"这一声明规则。

    **只防误删、不证明行为**：当前注册表里没有已启用的 danger 能力，所以循环体
    空转 —— 它是一道"将来启用时才会真正生效"的守卫（`validate_registry` 也查同一条）。
    """
    for cap in REGISTRY:
        if cap.enabled and cap.level is Autonomy.DANGER:
            assert cap.action_id in GATED_ACTIONS, f"{cap.name} 的 action_id 未登记"


def test_every_enabled_capability_has_handler_and_precondition():
    """注册表与执行器**必须一一对应** —— 声明了却没实现是最危险的漏步形态。"""
    from coach.orchestration.executor import missing_handlers

    gaps = missing_handlers()
    assert gaps == (), "已启用能力缺少实现：\n  - " + "\n  - ".join(gaps)


def test_registry_stage_source_is_valid():
    """契约钉桩：只断言 `stage_source` 取值合法，**只防误删、不证明行为**。"""
    from coach.domain.capabilities import STAGE_SOURCE_LIVE, STAGE_SOURCE_TURN_START

    for cap in REGISTRY:
        assert cap.stage_source in (STAGE_SOURCE_LIVE, STAGE_SOURCE_TURN_START), cap.name


def test_window_finish_check_uses_turn_start_stage():
    """这条能力必须用**本轮起始阶段**判定 —— 对应 turn.py 的 `in_learning` 快照。

    契约钉桩：断言的是注册表声明（`STAGE_SOURCE_TURN_START` + 只服务 learning），
    **只防误删、不证明行为**；真实行为由 `test_dialogue` 的执行顺序用例覆盖。
    """
    from coach.domain.capabilities import STAGE_SOURCE_TURN_START

    cap = REGISTRY_BY_NAME["planning.window_finish_check"]
    assert cap.stage_source == STAGE_SOURCE_TURN_START
    assert cap.stages == ("learning",)


# ---------------------------------------------------------------------------
# 3) 三级授权
# ---------------------------------------------------------------------------

def test_default_autonomy_is_danger():
    assert DEFAULT_AUTONOMY is Autonomy.DANGER
    assert parse_autonomy(None) is Autonomy.DANGER
    assert parse_autonomy("") is Autonomy.DANGER


def test_unknown_autonomy_declaration_falls_back_to_danger():
    """**I-5**：无法识别一律按 danger（fail-closed），而不是按 read 放行。"""
    assert parse_autonomy("writ") is Autonomy.DANGER
    assert parse_autonomy("ADMIN") is Autonomy.DANGER
    assert parse_autonomy(123) is Autonomy.DANGER


def test_is_declared_is_strict_while_parse_is_permissive():
    assert is_declared("write") and is_declared(Autonomy.READ)
    assert not is_declared("writ") and not is_declared(None) and not is_declared(123)


def test_parse_autonomy_normalizes_case_and_space():
    assert parse_autonomy(" WRITE ") is Autonomy.WRITE
    assert parse_autonomy("Read") is Autonomy.READ


def test_exceeds_compares_levels():
    assert exceeds(Autonomy.READ, Autonomy.WRITE)
    assert exceeds(Autonomy.WRITE, Autonomy.DANGER)
    assert not exceeds(Autonomy.WRITE, Autonomy.WRITE)
    assert not exceeds(Autonomy.DANGER, Autonomy.WRITE)


def test_ensure_within_ceiling_blocks_escalation():
    try:
        ensure_within_ceiling(Autonomy.READ, Autonomy.WRITE, subject="tool.web_search")
    except AutonomyViolation as exc:
        assert "tool.web_search" in str(exc) and "write" in str(exc)
    else:
        raise AssertionError("read 级能力不应被允许执行 write 级动作")


def test_ensure_within_ceiling_allows_equal_and_lower():
    assert ensure_within_ceiling(Autonomy.WRITE, Autonomy.WRITE) is Autonomy.WRITE
    assert ensure_within_ceiling(Autonomy.DANGER, Autonomy.READ) is Autonomy.READ


def test_ensure_within_ceiling_treats_missing_declaration_as_danger():
    """未声明上限的能力 = danger：它反而**能**做 danger 动作（但仍要过登记）。"""
    assert ensure_within_ceiling(None, Autonomy.DANGER) is Autonomy.DANGER


def test_ensure_action_registered_requires_id_for_danger():
    try:
        ensure_action_registered(Autonomy.DANGER, None)
    except AutonomyViolation as exc:
        assert "action_id" in str(exc)
    else:
        raise AssertionError("danger 级动作没有 action_id 时必须拒绝")


def test_ensure_action_registered_rejects_unknown_action():
    try:
        ensure_action_registered(Autonomy.DANGER, "delete_everything")
    except UnknownActionError:
        pass
    else:
        raise AssertionError("未登记的动作不应被放行")


def test_ensure_action_registered_accepts_registered_action():
    """已登记的 danger 动作必须放行。

    **隐式断言**：`ensure_action_registered` 无返回值，"放行"就等于"不抛异常"；
    它若抛 `AutonomyViolation` / `UnknownActionError`，本用例即失败。
    """
    registered = sorted(GATED_ACTIONS)[0]
    ensure_action_registered(Autonomy.DANGER, registered)


def test_ensure_action_registered_skips_for_write_level():
    """write / read 级不需要 action_id（它们不需要确认门）。

    **隐式断言**：同上 —— 不抛异常即通过；级别低于 danger 时必须**直接返回**，
    即使传了一个未登记的 action_id 也不检查。
    """
    ensure_action_registered(Autonomy.WRITE, None)
    ensure_action_registered(Autonomy.READ, "whatever")


def test_ensure_allowed_combines_level_and_registration():
    assert ensure_allowed(Autonomy.DANGER, Autonomy.DANGER, action_id="delete_history") is Autonomy.DANGER

    try:
        ensure_allowed(Autonomy.READ, Autonomy.DANGER, action_id="delete_history")
    except AutonomyViolation:
        pass
    else:
        raise AssertionError("越级必须先被级别检查拦下")

    try:
        ensure_allowed(Autonomy.DANGER, Autonomy.DANGER, action_id="nope")
    except UnknownActionError:
        pass
    else:
        raise AssertionError("级别够但动作未登记，仍须拒绝")


# ---------------------------------------------------------------------------
# 极简 runner（共用实现见 tests/_runner.py）
# ---------------------------------------------------------------------------

from _runner import SkipTest, run_tests        # noqa: E402


def main() -> int:
    return run_tests(globals())


if __name__ == "__main__":
    raise SystemExit(main())
