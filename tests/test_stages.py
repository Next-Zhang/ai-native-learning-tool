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
from coach.domain.state_schema import DEFAULT_STATE, ensure_keys
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
    (STAGE_PLANNING, {"current_plan": {"days": []}, "plan_confirmed": False}),  # 有计划但未确认
    (STAGE_LEARNING, {"current_plan": {"days": []}}),                        # 没有用户提交
    (STAGE_EVALUATION, {"today_task": {"goal": "练习列表"}}),                 # 没有验收结论
]

# 每个阶段：条件**满足**时应推进到目标阶段
READY_CASES = [
    (
        STAGE_GOAL_CLARIFICATION,
        {"learning_goal": "Python", "current_level": "基础",
         "daily_minutes": 30, "target_date": "1个月"},
        STAGE_ASSESSMENT,
    ),
    (STAGE_ASSESSMENT, {"skill_profile": {"variables": 0.9}}, STAGE_PLANNING),
    (STAGE_PLANNING, {"current_plan": {"days": ["day1"]}, "plan_confirmed": True},
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
    """主干必须是一条线性链：goal → assessment → … → profile_update。"""
    assert [t[0] for t in TRANSITIONS] == list(STAGES[:-1])
    assert [t[1] for t in TRANSITIONS] == list(STAGES[1:])


def test_every_stage_has_label_and_prompt():
    for stage in ALL_STAGES:
        assert stage in STAGE_LABELS and STAGE_LABELS[stage], stage
        assert stage in STAGE_PROMPTS and len(STAGE_PROMPTS[stage].strip()) > 30, stage
    # 各阶段提示词必须不同（否则“阶段驱动行为”就是假的）
    assert len(set(STAGE_PROMPTS.values())) == len(ALL_STAGES)


def test_stage_prompts_encode_key_rules():
    """把关键产品规则写进提示词，防止以后被误删。"""
    assessment = STAGE_PROMPTS[STAGE_ASSESSMENT]
    assert "能力测评" in assessment
    assert "一次只出" in assessment          # 一次一道题
    assert "3~5" in assessment               # 题量

    planning = STAGE_PROMPTS[STAGE_PLANNING]
    assert "7 天" in planning                # 7 天滚动窗口（已确认的决策）

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
        daily_minutes=30, target_date="1个月",
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
                "skill_profile", "weak_points", "current_plan", "today_task"):
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
# 极简 runner（共用实现见 tests/_runner.py）
# ---------------------------------------------------------------------------

from _runner import SkipTest, run_tests        # noqa: E402


def main() -> int:
    return run_tests(globals())


if __name__ == "__main__":
    raise SystemExit(main())
