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
import traceback
from pathlib import Path

# 允许以脚本方式直接运行（把项目根目录加入 import 路径）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from profile_extractor import UserProfile, extract_profile
from stages import try_advance
from state import (
    DEFAULT_STATE,
    merge_profile,
    missing_profile_fields,
    profile_complete,
)


def fresh_state() -> dict:
    """每个测试用一份干净的默认状态。"""
    return copy.deepcopy(DEFAULT_STATE)


# ---------------------------------------------------------------------------
# 1) schema：分钟数清洗
# ---------------------------------------------------------------------------

def test_minutes_parsing():
    assert UserProfile.model_validate({"daily_minutes": 30}).daily_minutes == 30
    assert UserProfile.model_validate({"daily_minutes": "30"}).daily_minutes == 30
    assert UserProfile.model_validate({"daily_minutes": "30分钟"}).daily_minutes == 30
    assert UserProfile.model_validate({"daily_minutes": "1小时"}).daily_minutes == 60
    assert UserProfile.model_validate({"daily_minutes": "半小时"}).daily_minutes == 30
    # 无法解析 -> None（宁缺勿错），不得抛异常
    assert UserProfile.model_validate({"daily_minutes": "很多"}).daily_minutes is None
    assert UserProfile.model_validate({"daily_minutes": None}).daily_minutes is None


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
    p = UserProfile(daily_minutes=30)          # 本轮只提到时间

    updated = merge_profile(state, p)

    assert updated == ["daily_minutes"], updated
    assert state["learning_goal"] == "Python"  # 没被 None 抹掉
    assert state["daily_minutes"] == 30


def test_merge_all_none_changes_nothing():
    state = fresh_state()
    state.update({"learning_goal": "Python", "daily_minutes": 30})
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
    updated = merge_profile(state, {"learning_goal": "Python", "daily_minutes": None})
    assert updated == ["learning_goal"]
    assert state["daily_minutes"] is None


# ---------------------------------------------------------------------------
# 3) 阶段守卫
# ---------------------------------------------------------------------------

def test_stage_guard_blocks_incomplete():
    state = fresh_state()
    state.update({"learning_goal": "Python", "current_level": "有少量基础", "daily_minutes": 30})

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
            "daily_minutes": 30,
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
        print("        [跳过] 未设置 DEEPSEEK_API_KEY，跳过真实抽取用例")
        return

    profile = extract_profile(ACCEPTANCE_SENTENCE)
    print("        抽取结果:", profile.model_dump())

    assert profile.learning_goal, "learning_goal 不应为空"
    assert "Python" in profile.learning_goal
    assert profile.daily_minutes == 30
    assert profile.current_level, "current_level 不应为空"
    assert profile.target_date, "target_date 不应为空"

    # 合并进 state 后，四项齐全 -> 必须推进到 assessment（文档验收标准）
    state = fresh_state()
    merge_profile(state, profile)
    assert try_advance(state) == "assessment"
    assert state["current_stage"] == "assessment"


# ---------------------------------------------------------------------------
# 极简 runner（不依赖 pytest）
# ---------------------------------------------------------------------------

def main() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]

    passed = failed = 0
    for test in tests:
        print(f"[RUN ] {test.__name__}")
        try:
            test()
        except Exception as exc:                      # noqa: BLE001
            failed += 1
            print(f"[FAIL] {test.__name__}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
        else:
            passed += 1
            print(f"[PASS] {test.__name__}")

    print(f"\n结果：{passed} 通过 / {failed} 失败（共 {len(tests)} 个用例）")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
