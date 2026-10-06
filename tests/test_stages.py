r"""V0.3a 状态机验收测试（纯 Python 断言脚本）。

运行（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\test_stages.py

覆盖：
- 阶段顺序（主干必须是一条线性链）
- 每个阶段都有中文标签与行为提示词（且互不相同）
- 转换守卫：条件不满足绝不推进；满足才推进，且每次只走一步
- 越级防护：出口阶段没有自动转换
- state.ensure_keys：旧状态文件升级时补齐新字段、不覆盖已有值、不共享可变默认值
"""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.domain.stages import (
    ALL_STAGES,
    EXIT_STAGES,
    STAGES,
    STAGE_ASSESSMENT,
    STAGE_EVALUATION,
    STAGE_GOAL_CLARIFICATION,
    STAGE_LABELS,
    STAGE_LEARNING,
    STAGE_PLANNING,
    STAGE_PROFILE_UPDATE,
    TRANSITIONS,
    blocked_reason,
    can_advance,
    pending_transition,
    stage_label,
    try_advance,
)
from coach.domain.state_schema import (
    DEFAULT_STATE,
    ensure_keys,
    migrate_legacy_fields,
    upgrade_plan_progress,
    upgrade_window_shape,
)
from coach.prompts.stages import DEFAULT_PROMPT, STAGE_PROMPTS, stage_prompt


def _state_at(stage: str, **extra) -> dict:
    """构造一个“停在某阶段”的干净状态。"""
    state = copy.deepcopy(DEFAULT_STATE)
    state["current_stage"] = stage
    state.update(extra)
    return state


# 每个阶段：条件**不满足**时应被守卫拦住
BLOCKED_CASES = [
    (STAGE_GOAL_CLARIFICATION, {"learning_goal": "Python"}),                 # 只有 1/4 项
    (STAGE_ASSESSMENT, {}),                                                  # 没有能力画像
    (STAGE_PLANNING, {"skill_profile": {"variables": 0.9}}),                 # 没有学习计划
    (STAGE_PLANNING, {"current_window": {"days": []}, "plan_confirmed": False}),  # 有计划但未确认
    (STAGE_LEARNING, {"current_window": {"days": []}}),                        # 没有用户提交
    (STAGE_EVALUATION, {"today_task": {"goal": "练习列表"}}),                 # 没有验收结论
]

# 每个阶段：条件**满足**时应推进到目标阶段
READY_CASES = [
    (
        STAGE_GOAL_CLARIFICATION,
        {"learning_goal": "Python", "current_level": "基础",
         "session_minutes": 30, "target_date": "1个月"},
        STAGE_ASSESSMENT,
    ),
    (STAGE_ASSESSMENT, {"skill_profile": {"variables": 0.9}}, STAGE_PLANNING),
    (STAGE_PLANNING, {"current_window": {"days": ["day1"]}, "plan_confirmed": True},
     STAGE_LEARNING),
    (
        STAGE_LEARNING,
        {"today_task": {"goal": "练习列表"}, "pending_submission": "我的答案"},
        STAGE_EVALUATION,
    ),
    (STAGE_EVALUATION, {"latest_result": {"completion": "完成"}}, STAGE_PROFILE_UPDATE),
]


# ---------------------------------------------------------------------------
# 1) 结构与提示词
# ---------------------------------------------------------------------------

def test_chain_is_linear():
    """主干必须是一条线性链：goal → assessment → … → profile_update。

    契约钉桩：只断言 `TRANSITIONS` / `STAGES` 的形状，**只防误删、不证明行为**
    （守卫是否真的拦住/放行，由 `test_guards_*` 那几条负责）。
    """
    assert [t[0] for t in TRANSITIONS] == list(STAGES[:-1])
    assert [t[1] for t in TRANSITIONS] == list(STAGES[1:])


def test_every_stage_has_label_and_prompt():
    for stage in ALL_STAGES:
        assert stage in STAGE_LABELS and STAGE_LABELS[stage], stage
        assert stage in STAGE_PROMPTS and len(STAGE_PROMPTS[stage].strip()) > 30, stage
    # 各阶段提示词必须不同（否则“阶段驱动行为”就是假的）
    assert len(set(STAGE_PROMPTS.values())) == len(ALL_STAGES)


def test_stage_prompts_encode_key_rules():
    """把关键产品规则写进提示词，防止以后被误删。

    契约钉桩：只断言提示词文本，**只防误删、不证明行为** ——
    提示词写对了不等于模型会照做（X-16 的第一次翻车正是如此）。
    """
    assessment = STAGE_PROMPTS[STAGE_ASSESSMENT]
    assert "能力测评" in assessment
    assert "一次只出" in assessment          # 一次一道题
    assert "3~5" in assessment               # 题量

    planning = STAGE_PROMPTS[STAGE_PLANNING]
    assert "路线图" in planning              # 双层计划的长期层
    assert "执行窗口" in planning            # 双层计划的短期层
    assert "里程碑" in planning
    assert "不得超过" in planning            # 任务粒度硬约束（碎片化的落点）

    learning = STAGE_PROMPTS[STAGE_LEARNING]
    assert "学习任务" in learning

    evaluation = STAGE_PROMPTS[STAGE_EVALUATION]
    assert "证据" in evaluation              # 不能只信“我会了”


def test_stage_prompt_and_label_fallback():
    assert stage_prompt("no_such_stage") == DEFAULT_PROMPT
    assert stage_prompt(None) == DEFAULT_PROMPT
    assert stage_label("no_such_stage") == "no_such_stage"


# ---------------------------------------------------------------------------
# 2) 守卫：该拦的必须拦住
# ---------------------------------------------------------------------------

def test_guards_block_incomplete():
    for stage, extra in BLOCKED_CASES:
        state = _state_at(stage, **extra)
        assert can_advance(state) is False, f"{stage} 不应允许推进"
        assert try_advance(state) is None, f"{stage} 不应推进"
        assert state["current_stage"] == stage, f"{stage} 阶段被意外改变"
        assert blocked_reason(state), f"{stage} 应给出未满足的原因"


def test_guards_allow_when_ready():
    for stage, extra, expected in READY_CASES:
        state = _state_at(stage, **extra)
        assert can_advance(state) is True, f"{stage} 应允许推进"
        assert blocked_reason(state) is None
        assert try_advance(state) == expected, f"{stage} 应推进到 {expected}"
        assert state["current_stage"] == expected


def test_single_step_only():
    """即使后面阶段的条件也成立，一次调用也只推进一步。"""
    state = _state_at(
        STAGE_GOAL_CLARIFICATION,
        learning_goal="Python", current_level="基础",
        session_minutes=30, target_date="1个月",
        skill_profile={"variables": 0.9},          # 下一步的条件也满足
    )
    assert try_advance(state) == STAGE_ASSESSMENT   # 只走一步
    assert state["current_stage"] == STAGE_ASSESSMENT


def test_exit_stages_have_no_auto_transition():
    for stage in EXIT_STAGES:
        state = _state_at(stage)
        assert pending_transition(state) is None
        assert try_advance(state) is None
        assert blocked_reason(state) is None


# ---------------------------------------------------------------------------
# 3) 旧状态文件升级
# ---------------------------------------------------------------------------

def test_ensure_keys_upgrades_old_state():
    old_state = {
        "learning_goal": "Python",
        "current_stage": "assessment",
        "conversation_history": [{"role": "user", "content": "hi"}],
    }

    added = ensure_keys(old_state)

    # 新字段被补齐
    for key in ("assessment_progress", "pending_submission", "latest_result",
                "skill_profile", "weak_points", "current_window", "today_task"):
        assert key in old_state, key
    assert "latest_result" in added

    # 已有值绝不被覆盖
    assert old_state["learning_goal"] == "Python"
    assert old_state["current_stage"] == "assessment"
    assert old_state["conversation_history"] == [{"role": "user", "content": "hi"}]

    # 幂等：再补一次不应有新增
    assert ensure_keys(old_state) == []


def test_ensure_keys_does_not_share_mutable_defaults():
    a, b = {}, {}
    ensure_keys(a)
    ensure_keys(b)

    a["weak_points"].append("函数")
    a["skill_profile"]["variables"] = 0.1

    assert b["weak_points"] == []
    assert b["skill_profile"] == {}


# ---------------------------------------------------------------------------
# 4) v0.13 字段迁移：daily_minutes -> session_minutes（A-14）
# ---------------------------------------------------------------------------

def test_legacy_daily_minutes_migrates_to_session_minutes():
    """旧的"每天可投入"搬到"单次可投入"：**不覆盖新值、不删旧键**（信息保全）。"""
    state = {"daily_minutes": 30}
    moved = migrate_legacy_fields(state)

    assert moved == ["daily_minutes->session_minutes"]
    assert state["session_minutes"] == 30
    assert state["daily_minutes"] == 30          # 旧键保留，迁移可逆

    # 已有新值 -> 不覆盖
    state2 = {"daily_minutes": 30, "session_minutes": 15}
    assert migrate_legacy_fields(state2) == []
    assert state2["session_minutes"] == 15

    # 旧值为 None -> 不算迁移
    state3 = {"daily_minutes": None}
    assert migrate_legacy_fields(state3) == []
    assert state3["session_minutes"] is None


def test_ensure_keys_runs_migration_before_filling_defaults():
    """旧状态文件只经过 `ensure_keys` 就应该拿到新字段（调用方无需额外处理）。"""
    old_state = {"daily_minutes": 25, "conversation_history": []}

    ensure_keys(old_state)

    assert old_state["session_minutes"] == 25
    assert "sessions_per_week" in old_state
    assert old_state["sessions_per_week"] is None


def test_migration_is_idempotent():
    """迁移必须可重复执行（重启/多次加载同一文件）。"""
    state = {"daily_minutes": 20}
    assert migrate_legacy_fields(state) == ["daily_minutes->session_minutes"]
    assert migrate_legacy_fields(state) == []          # 第二次无操作
    assert state["session_minutes"] == 20


def test_upgrade_window_shape_fills_new_fields():
    """v0.14：旧的"计划"结构补齐成**执行窗口**结构（length / unit / milestone_id）。"""
    state = {
        "session_minutes": 15,
        "current_window": {
            "horizon_days": 7,
            "start_date": "2026-01-01",
            "days": [{"day": 1, "theme": "t", "tasks": []}],
        },
    }

    changed = upgrade_window_shape(state)
    window = state["current_window"]

    assert window["length"] == 7                 # 来自旧的 horizon_days
    assert window["unit"] == "session"           # 15 分钟 -> 碎片化，单位是"次"
    assert "milestone_id" in window
    assert set(changed) == {
        "current_window.length", "current_window.unit", "current_window.milestone_id",
    }

    # 幂等：再跑一次无变化
    assert upgrade_window_shape(state) == []

    # 已有值不被覆盖（三个键都齐 -> 完全无操作）
    other = {"current_window": {
        "length": 2, "unit": "day", "milestone_id": "M9", "horizon_days": 9,
    }}
    assert upgrade_window_shape(other) == []
    assert other["current_window"]["length"] == 2
    assert other["current_window"]["unit"] == "day"
    assert other["current_window"]["milestone_id"] == "M9"


def test_upgrade_window_shape_is_noop_without_window():
    assert upgrade_window_shape({}) == []
    assert upgrade_window_shape({"current_window": None}) == []


def test_upgrade_plan_progress_adds_attempts():
    """v0.14：`ensure_keys` 只补**顶层**键，嵌套的 `plan_progress.attempts` 要单独升级。"""
    state = {"plan_progress": {"day": 1, "task": 1, "completed": [], "finished": False}}

    assert upgrade_plan_progress(state) == ["plan_progress.attempts"]
    assert state["plan_progress"]["attempts"] == 0

    assert upgrade_plan_progress(state) == []                 # 幂等
    assert upgrade_plan_progress({}) == []                    # 没有 plan_progress -> 无操作
    assert upgrade_plan_progress({"plan_progress": None}) == []

    other = {"plan_progress": {"attempts": 3}}                # 已有值不被覆盖
    assert upgrade_plan_progress(other) == []
    assert other["plan_progress"]["attempts"] == 3


# ---------------------------------------------------------------------------
# 5) 守卫必须 fail-closed：字符串 "false" 不得放行（v0.14 审计修复）
# ---------------------------------------------------------------------------

def test_guard_plan_confirmed_rejects_string_false():
    """**唯一放行依据**不得被 `bool("false") is True` 骗过。

    回归自真实缺陷：`_guard_plan_confirmed` 原用 `bool(...)`，而模型在 JSON 模式下
    可能把布尔写成字符串 —— 旧状态文件里的 `"plan_confirmed": "false"`
    会让**未确认就开始教学**，而 `planning.is_confirmed` 却认为未确认（两处矛盾）。
    """
    for falsy in ("false", "False", "no", "否", "", None, 0):
        state = {"current_stage": STAGE_PLANNING,
                 "current_window": {"days": []}, "plan_confirmed": falsy}
        assert try_advance(state) is None, f"plan_confirmed={falsy!r} 不应放行"

    for truthy in (True, "true", 1, "是"):
        state = {"current_stage": STAGE_PLANNING,
                 "current_window": {"days": []}, "plan_confirmed": truthy}
        assert try_advance(state) == STAGE_LEARNING, f"plan_confirmed={truthy!r} 应放行"


def test_guard_update_applied_rejects_string_false():
    """同理：`"latest_result_applied": "false"` 不得让画像未更新就回到学习任务。"""
    state = {"current_stage": STAGE_PROFILE_UPDATE, "latest_result_applied": "false"}
    assert try_advance(state) is None

    state["latest_result_applied"] = "true"
    assert try_advance(state) == STAGE_LEARNING


def test_to_bool_is_fail_closed():
    """拿不准一律按 `False`（没有确认 / 不是提交），而不是按"非空即真"。"""
    from coach.domain.coercion import to_bool

    assert to_bool("false") is False
    assert to_bool("FALSE") is False
    assert to_bool("maybe") is False                 # 无法判断 -> fail-closed
    assert to_bool(None) is False
    assert to_bool(0) is False
    assert to_bool("") is False
    assert to_bool("true") is True
    assert to_bool(True) is True
    assert to_bool("maybe", default=True) is True     # 可显式改默认值


# ---------------------------------------------------------------------------
# 极简 runner（共用实现见 tests/_runner.py）
# ---------------------------------------------------------------------------

from _runner import SkipTest, run_tests        # noqa: E402


def main() -> int:
    return run_tests(globals())


if __name__ == "__main__":
    raise SystemExit(main())
