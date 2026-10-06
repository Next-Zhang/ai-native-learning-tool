r"""V0.2 验收测试（纯 Python 断言脚本，不需要 pytest）。

运行（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\test_profile.py

覆盖：
- UserProfile schema：分钟数清洗、空白串转 None
- merge_profile：只合并非空字段、空值不覆盖、新值可覆盖旧值
- 阶段守卫：四项缺一不得推进；齐全必推进且幂等
- 真实抽取（集成用例，需要 DEEPSEEK_API_KEY；无 Key 时自动跳过）
"""

import copy
import os
import sys
from pathlib import Path

# 允许以脚本方式直接运行（把项目根目录加入 import 路径）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.domain.models import UserProfile
from coach.domain.profile_rules import (
    EXTRACTABLE_PROFILE_FIELDS,
    OPTIONAL_PROFILE_FIELDS,
    PROFILE_FIELDS,
    merge_profile,
    missing_profile_fields,
    profile_complete,
)
from coach.domain.stages import try_advance
from coach.domain.state_schema import DEFAULT_STATE
from coach.services.profile import extract_profile


def fresh_state() -> dict:
    """每个测试用一份干净的默认状态。"""
    return copy.deepcopy(DEFAULT_STATE)


# ---------------------------------------------------------------------------
# 1) schema：分钟数清洗
# ---------------------------------------------------------------------------

def test_minutes_parsing():
    assert UserProfile.model_validate({"session_minutes": 30}).session_minutes == 30
    assert UserProfile.model_validate({"session_minutes": "30"}).session_minutes == 30
    assert UserProfile.model_validate({"session_minutes": "30分钟"}).session_minutes == 30
    assert UserProfile.model_validate({"session_minutes": "1小时"}).session_minutes == 60
    assert UserProfile.model_validate({"session_minutes": "半小时"}).session_minutes == 30
    # 无法解析 -> None（宁缺勿错），不得抛异常
    assert UserProfile.model_validate({"session_minutes": "很多"}).session_minutes is None
    assert UserProfile.model_validate({"session_minutes": None}).session_minutes is None


# ---------------------------------------------------------------------------
# 1b) 时间预算：单次时长必填，每周次数**可选**（A-14）
# ---------------------------------------------------------------------------

def test_sessions_per_week_parsing():
    """可选的"每周几次"也要归一化；解析不出一律 None，不抛异常。"""
    assert UserProfile.model_validate({"sessions_per_week": 3}).sessions_per_week == 3
    assert UserProfile.model_validate({"sessions_per_week": "3"}).sessions_per_week == 3
    assert UserProfile.model_validate({"sessions_per_week": "每周三次"}).sessions_per_week == 3
    assert UserProfile.model_validate({"sessions_per_week": "五六次"}).sessions_per_week == 5
    assert UserProfile.model_validate({"sessions_per_week": "看情况"}).sessions_per_week is None
    assert UserProfile.model_validate({"sessions_per_week": None}).sessions_per_week is None


def test_time_budget_field_layout():
    """必填项是**单次时长**，不是"每天总量"；每周次数不进必填。

    契约钉桩：只断言字段布局常量，**只防误删、不证明行为**
    （抽取/合并的实际行为由前后几条用例覆盖）。
    """
    assert "session_minutes" in PROFILE_FIELDS
    assert "sessions_per_week" not in PROFILE_FIELDS
    assert "sessions_per_week" in OPTIONAL_PROFILE_FIELDS
    assert set(EXTRACTABLE_PROFILE_FIELDS) == set(PROFILE_FIELDS) | set(OPTIONAL_PROFILE_FIELDS)
    assert "daily_minutes" not in EXTRACTABLE_PROFILE_FIELDS


def test_sessions_per_week_does_not_block_completeness():
    """**关键**：可选字段不得把用户卡在澄清阶段（UR-08 一次只问 1~2 个问题）。"""
    state = {
        "learning_goal": "Python 数据分析",
        "current_level": "零基础",
        "session_minutes": 15,
        "target_date": "1个月",
    }
    assert profile_complete(state) is True
    assert missing_profile_fields(state) == []


def test_sessions_per_week_is_merged_when_provided():
    """提供了就存下来（能被教练展示），但缺失时不算"还差什么"。"""
    state = fresh_state()
    updated = merge_profile(state, {"sessions_per_week": 4})
    assert updated == ["sessions_per_week"]
    assert state["sessions_per_week"] == 4
    assert missing_profile_fields(state) != ["sessions_per_week"]


def test_blank_strings_become_none():
    p = UserProfile.model_validate(
        {"learning_goal": "   ", "current_level": "", "target_date": None}
    )
    assert p.learning_goal is None
    assert p.current_level is None
    assert p.target_date is None


# ---------------------------------------------------------------------------
# 2) merge_profile：部分更新语义
# ---------------------------------------------------------------------------

def test_merge_only_non_null():
    state = fresh_state()
    state["learning_goal"] = "Python"          # 已有信息
    p = UserProfile(session_minutes=30)          # 本轮只提到时间

    updated = merge_profile(state, p)

    assert updated == ["session_minutes"], updated
    assert state["learning_goal"] == "Python"  # 没被 None 抹掉
    assert state["session_minutes"] == 30


def test_merge_all_none_changes_nothing():
    state = fresh_state()
    state.update({"learning_goal": "Python", "session_minutes": 30})
    before = copy.deepcopy(state)

    updated = merge_profile(state, UserProfile())

    assert updated == [], updated
    assert state == before


def test_merge_overwrites_with_new_value():
    state = fresh_state()
    state["learning_goal"] = "Python"

    updated = merge_profile(state, UserProfile(learning_goal="Python 数据分析"))

    assert updated == ["learning_goal"]
    assert state["learning_goal"] == "Python 数据分析"


def test_merge_accepts_plain_dict():
    state = fresh_state()
    updated = merge_profile(state, {"learning_goal": "Python", "session_minutes": None})
    assert updated == ["learning_goal"]
    assert state["session_minutes"] is None


# ---------------------------------------------------------------------------
# 3) 阶段守卫
# ---------------------------------------------------------------------------

def test_stage_guard_blocks_incomplete():
    state = fresh_state()
    state.update({"learning_goal": "Python", "current_level": "有少量基础", "session_minutes": 30})

    assert profile_complete(state) is False
    assert try_advance(state) is None
    assert state["current_stage"] == "goal_clarification"
    assert missing_profile_fields(state) == ["target_date"]


def test_stage_advances_when_complete_and_is_idempotent():
    state = fresh_state()
    state.update(
        {
            "learning_goal": "Python 数据分析",
            "current_level": "有少量基础",
            "session_minutes": 30,
            "target_date": "1个月",
        }
    )

    assert profile_complete(state) is True
    assert try_advance(state) == "assessment"
    assert state["current_stage"] == "assessment"
    # 幂等：已是 assessment，不应再次“推进”
    assert try_advance(state) is None


# ---------------------------------------------------------------------------
# 4) 真实抽取（集成用例；无 API Key 自动跳过）
# ---------------------------------------------------------------------------

ACCEPTANCE_SENTENCE = "我想一个月学习 Python 数据分析，以前只学过一点基础，每天能学 30 分钟。"


def test_live_extraction():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SkipTest("未设置 DEEPSEEK_API_KEY，跳过真实抽取用例")

    profile = extract_profile(ACCEPTANCE_SENTENCE)
    print("        抽取结果:", profile.model_dump())

    assert profile.learning_goal, "learning_goal 不应为空"
    assert "Python" in profile.learning_goal
    assert profile.session_minutes == 30
    assert profile.current_level, "current_level 不应为空"
    assert profile.target_date, "target_date 不应为空"

    # 合并进 state 后，四项齐全 -> 必须推进到 assessment（文档验收标准）
    state = fresh_state()
    merge_profile(state, profile)
    assert try_advance(state) == "assessment"
    assert state["current_stage"] == "assessment"


# ---------------------------------------------------------------------------
# 极简 runner（共用实现见 tests/_runner.py）
# ---------------------------------------------------------------------------

from _runner import SkipTest, run_tests        # noqa: E402


def main() -> int:
    return run_tests(globals())


if __name__ == "__main__":
    raise SystemExit(main())
