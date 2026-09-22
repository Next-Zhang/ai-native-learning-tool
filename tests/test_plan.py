r"""V0.3c 学习计划验收测试（纯 Python 断言脚本）。

运行（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\test_plan.py

覆盖：
- 期限解析：阿拉伯数字 / 中文数字 / 各时间单位 / 模糊表达返回 None
- 窗口天数：min(7, 期限天数)、期限不足 7 天按实际、解析不出用默认 7 天
- 计划清洗：天数对齐窗口（截断 + 补齐）、重编号、每天任务上限、空任务丢弃、空计划兜底
- 确认门控：有计划但未确认时守卫必须拦住；确认后才放行到 learning
- 真实用例（需 DEEPSEEK_API_KEY）：生成计划 + B2 确认判定（确认 / 不确认各一次）
"""

import copy
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from planner import (
    DEFAULT_HORIZON_DAYS,
    MAX_TASKS_PER_DAY,
    confirm_plan,
    ensure_plan,
    fallback_plan,
    is_confirmed,
    normalize_plan_data,
    parse_target_days,
    plan_horizon,
)
from stages import try_advance
from state import DEFAULT_STATE, STAGE_LEARNING, STAGE_PLANNING


def _planning_state(**extra) -> dict:
    state = copy.deepcopy(DEFAULT_STATE)
    state.update({
        "learning_goal": "Python 数据分析",
        "current_level": "学过一点基础",
        "daily_minutes": 30,
        "target_date": "1个月",
        "current_stage": STAGE_PLANNING,
        "skill_profile": {"pandas": 0.5},
        "weak_points": ["pandas"],
    })
    state.update(extra)
    return state


# ---------------------------------------------------------------------------
# 1) 期限解析
# ---------------------------------------------------------------------------

def test_parse_target_days_arabic():
    assert parse_target_days("1个月") == 30
    assert parse_target_days("3个月") == 90
    assert parse_target_days("2周") == 14
    assert parse_target_days("10天") == 10
    assert parse_target_days("1年") == 365


def test_parse_target_days_chinese():
    assert parse_target_days("一个月") == 30
    assert parse_target_days("三个月") == 90
    assert parse_target_days("两周") == 14
    assert parse_target_days("十天") == 10
    assert parse_target_days("一年") == 365
    assert parse_target_days("半个月") == 15
    assert 180 <= parse_target_days("半年") <= 183


def test_parse_target_days_unparseable():
    for text in ["年底", "尽快", "有空就学", "", None, "abc"]:
        assert parse_target_days(text) is None, f"{text!r} 应解析失败"


# ---------------------------------------------------------------------------
# 2) 窗口天数
# ---------------------------------------------------------------------------

def test_plan_horizon_rules():
    assert plan_horizon({"target_date": "1个月"}) == DEFAULT_HORIZON_DAYS == 7
    assert plan_horizon({"target_date": "3个月"}) == 7      # 超过窗口上限 -> 7
    assert plan_horizon({"target_date": "3天"}) == 3        # 不足 7 天 -> 按实际
    assert plan_horizon({"target_date": "1天"}) == 1
    assert plan_horizon({"target_date": "年底"}) == 7       # 解析不出 -> 默认
    assert plan_horizon({}) == 7


# ---------------------------------------------------------------------------
# 3) 计划清洗
# ---------------------------------------------------------------------------

def test_normalize_plan_truncates_to_horizon():
    data = {"days": [{"theme": f"主题{i}", "tasks": [{"goal": f"目标{i}"}]}
                     for i in range(1, 6)]}
    days = normalize_plan_data(data, horizon=3)
    assert len(days) == 3
    assert [d["day"] for d in days] == [1, 2, 3]
    assert [d["theme"] for d in days] == ["主题1", "主题2", "主题3"]


def test_normalize_plan_pads_to_horizon():
    data = {"days": [{"theme": "只有一天", "tasks": [{"goal": "目标"}]}]}
    days = normalize_plan_data(data, horizon=4, daily_minutes=30)
    assert len(days) == 4
    assert [d["day"] for d in days] == [1, 2, 3, 4]
    # 补齐的占位日也必须有可执行任务
    assert all(d["tasks"] for d in days)


def test_normalize_plan_limits_tasks_and_drops_empty():
    data = {"days": [{
        "theme": "任务清洗",
        "tasks": [
            {"goal": "任务1", "minutes": "45分钟"},
            {"goal": "任务2"},
            {"goal": "任务3"},
            {"goal": "任务4"},                      # 超出每天上限，应被截断
            {"material": "", "exercise": ""},       # 全空 -> 丢弃
        ],
    }]}
    days = normalize_plan_data(data, horizon=1)
    tasks = days[0]["tasks"]
    assert len(tasks) == MAX_TASKS_PER_DAY == 3
    assert tasks[0]["minutes"] == 45                # 字符串分钟被转成整数
    assert [t["goal"] for t in tasks] == ["任务1", "任务2", "任务3"]


def test_normalize_plan_fallback_when_empty():
    days = normalize_plan_data({}, horizon=3, goal="Python 数据分析",
                               weak_points=["pandas"], daily_minutes=30)
    assert len(days) == 3
    assert all(d["tasks"] for d in days)
    assert "pandas" in days[0]["theme"]              # 兜底计划优先围绕薄弱点
    assert days[0]["tasks"][0]["minutes"] == 30


def test_fallback_plan_cycles_topics():
    days = fallback_plan(4, goal="Python", weak_points=["A", "B"], daily_minutes=20)
    assert [d["theme"] for d in days] == ["A 强化", "B 强化", "A 强化", "B 强化"]
    assert all(d["tasks"][0]["minutes"] == 20 for d in days)


# ---------------------------------------------------------------------------
# 4) 确认门控（B / B2 的核心）
# ---------------------------------------------------------------------------

def test_guard_requires_confirmation():
    plan = {"horizon_days": 7, "start_date": "2026-01-01",
            "days": [{"day": 1, "theme": "t", "tasks": [{"goal": "g"}]}]}

    # 有计划但未确认 -> 必须拦住，不能进入 learning
    state = _planning_state(current_plan=plan, plan_confirmed=False)
    assert is_confirmed(state) is False
    assert try_advance(state) is None
    assert state["current_stage"] == STAGE_PLANNING

    # 用户确认后 -> 放行
    state["plan_confirmed"] = True
    assert try_advance(state) == STAGE_LEARNING


def test_confirm_plan_keeps_waiting_without_llm():
    """没有可用的 LLM（无 Key）时：判定返回 None，且绝不误置确认标志。"""
    if os.getenv("DEEPSEEK_API_KEY"):
        print("        [跳过] 本用例仅在无 API Key 时验证失败兜底")
        return

    state = _planning_state(
        current_plan={"horizon_days": 7, "start_date": "2026-01-01",
                      "days": [{"day": 1, "theme": "t", "tasks": [{"goal": "g"}]}]},
        plan_confirmed=False,
    )
    verdict = confirm_plan(state, "可以，开始吧")
    assert verdict is None
    assert state["plan_confirmed"] is False


# ---------------------------------------------------------------------------
# 5) 真实用例（需 Key）
# ---------------------------------------------------------------------------

def test_live_generate_plan():
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("        [跳过] 未设置 DEEPSEEK_API_KEY，跳过真实计划生成")
        return

    state = _planning_state()
    assert ensure_plan(state) is True
    assert ensure_plan(state) is False               # 已存在 -> 不重复生成

    plan = state["current_plan"]
    print("        计划窗口:", plan["horizon_days"], "天 | 起始:", plan["start_date"])
    for day in plan["days"]:
        goals = " / ".join(t["goal"] for t in day["tasks"])
        print(f"          第{day['day']}天 {day['theme']}: {goals}")

    assert plan["horizon_days"] == 7
    assert len(plan["days"]) == 7
    assert all(day["theme"] for day in plan["days"])
    assert all(day["tasks"] for day in plan["days"])
    assert state["plan_confirmed"] is False          # 新计划必须等待确认


def test_live_confirmation_judgement():
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("        [跳过] 未设置 DEEPSEEK_API_KEY，跳过真实确认判定")
        return

    plan = {"horizon_days": 7, "start_date": "2026-01-01",
            "days": [{"day": 1, "theme": "pandas 基础", "tasks": [{"goal": "读 CSV"}]}]}

    # 明确同意 -> 确认
    state = _planning_state(current_plan=copy.deepcopy(plan), plan_confirmed=False)
    verdict = confirm_plan(state, "可以，就按这个计划开始吧")
    print("        同意判定:", verdict)
    assert verdict is not None and verdict.confirmed is True
    assert state["plan_confirmed"] is True

    # 要求修改 -> 不确认
    state2 = _planning_state(current_plan=copy.deepcopy(plan), plan_confirmed=False)
    verdict2 = confirm_plan(state2, "第 3 天能不能简单一点？我怕跟不上")
    print("        修改判定:", verdict2)
    assert verdict2 is not None and verdict2.confirmed is False
    assert state2["plan_confirmed"] is False


# ---------------------------------------------------------------------------
# 极简 runner
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
