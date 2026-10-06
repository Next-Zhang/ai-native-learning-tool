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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.domain.plan_rules import (
    DEFAULT_TASK_MINUTES,
    DEFAULT_WINDOW_LENGTH,
    MAX_TASKS_PER_DAY,
    MAX_WINDOW_LENGTH,
    MILESTONE_DONE,
    MIN_TASK_MINUTES,
    UNIT_DAY,
    UNIT_SESSION,
    advance_milestone,
    clamp_task_minutes,
    fallback_plan,
    fallback_roadmap,
    normalize_plan_data,
    normalize_roadmap,
    parse_target_days,
    plan_unit,
    window_length,
)
from coach.domain.stages import STAGE_LEARNING, STAGE_PLANNING, try_advance
from coach.domain.state_schema import DEFAULT_STATE
from coach.services.planning import (
    confirm_plan,
    ensure_plan,
    is_confirmed,
    roll_window,
    window_usage,
)


def _planning_state(**extra) -> dict:
    state = copy.deepcopy(DEFAULT_STATE)
    state.update({
        "learning_goal": "Python 数据分析",
        "current_level": "学过一点基础",
        "session_minutes": 30,
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
# 2) 计划单位、窗口长度、路线图（A-14：双层计划）
# ---------------------------------------------------------------------------

def test_plan_unit_derivation():
    """碎片化用"次"；单次 >= 45 分钟视为整块时间，切回"天"（**旧模型仍可用**）。"""
    assert plan_unit({"session_minutes": 15}) == UNIT_SESSION
    assert plan_unit({"session_minutes": 30}) == UNIT_SESSION
    assert plan_unit({"session_minutes": 44}) == UNIT_SESSION
    assert plan_unit({"session_minutes": 45}) == UNIT_DAY
    assert plan_unit({"session_minutes": 120}) == UNIT_DAY
    assert plan_unit({}) == UNIT_SESSION                     # 未填写按碎片化
    assert plan_unit({"session_minutes": "很多"}) == UNIT_SESSION


def test_window_length_without_roadmap():
    """没有路线图时：= min(3, 期望期限天数)。"""
    assert window_length({}) == DEFAULT_WINDOW_LENGTH == 3
    assert window_length({"target_date": "1个月"}) == 3
    assert window_length({"target_date": "3天"}) == 3
    assert window_length({"target_date": "1天"}) == 1
    assert window_length({"target_date": "年底"}) == 3        # 解析不出 -> 默认


def test_window_length_follows_current_milestone():
    """有路线图时：窗口长度 = **当前里程碑**的 sessions_est（**不固定 3/7**）。"""
    state = {
        "roadmap": {
            "current_milestone": "M2",
            "milestones": [
                {"id": "M1", "status": MILESTONE_DONE, "sessions_est": 2},
                {"id": "M2", "status": "in_progress", "sessions_est": 5},
            ],
        }
    }
    assert window_length(state) == 5

    state["roadmap"]["milestones"][1]["sessions_est"] = 99    # 越界 -> 钳制
    assert window_length(state) == MAX_WINDOW_LENGTH


def test_roadmap_fallback_and_normalize():
    state = {"learning_goal": "Python 数据分析",
             "weak_points": ["pandas", "matplotlib"], "session_minutes": 15}

    fallback = fallback_roadmap(state)
    assert fallback["source"] == "fallback"
    assert fallback["unit"] == UNIT_SESSION
    assert fallback["milestones"], "兜底路线图不能为空"
    assert fallback["milestones"][0]["status"] == "in_progress"
    assert all(m["sessions_est"] >= 1 for m in fallback["milestones"])

    dirty = {"milestones": [
        {"title": "  第一阶段  ", "topics": ["a", " ", "b"], "sessions_est": "4"},
        {"topics": []},                                        # 全空 -> 丢弃
        {"title": "第二阶段", "sessions_est": 99},               # 越界 -> 钳制
    ]}
    clean = normalize_roadmap(dirty, state)
    assert [m["id"] for m in clean["milestones"]] == ["M1", "M2"]
    assert clean["milestones"][0]["title"] == "第一阶段"
    assert clean["milestones"][0]["topics"] == ["a", "b"]
    assert clean["milestones"][0]["sessions_est"] == 4
    assert clean["milestones"][1]["sessions_est"] == MAX_WINDOW_LENGTH

    # 一个可用里程碑都没有 -> 整体兜底，绝不返回空路线图
    assert normalize_roadmap({"milestones": []}, state)["source"] == "fallback"


def test_advance_milestone_walks_the_roadmap():
    state = {"roadmap": fallback_roadmap({"learning_goal": "g"})}
    ids = [m["id"] for m in state["roadmap"]["milestones"]]
    assert state["roadmap"]["current_milestone"] == ids[0]

    assert advance_milestone(state) is True
    assert state["roadmap"]["current_milestone"] == ids[1]
    assert state["roadmap"]["milestones"][0]["status"] == MILESTONE_DONE

    while advance_milestone(state):
        pass
    assert state["roadmap"]["current_milestone"] is None      # 路线图走完
    assert advance_milestone(state) is False


def test_roll_window_moves_on_and_recalibrates():
    """**滚动 = 换窗口 + 按实际速度重估**，不只是换下一批任务。

    速度信号是 `plan_progress["attempts"]`（每判定一次 +1，**含重做**）÷ 窗口内
    **任务总数**（见 `planning.window_usage`）。因此本用例只用**真实流程能产生的** state：

    - `completed` 里的 key 由 `cursor.mark_task_done` 写入且**会去重**，"重做"永远
      不会产生重复 key —— 拿重复 key 当"变慢"是造不出来的假现场；
    - 真正的"变慢"只能体现在 `attempts` 上（retry/supplement 也 +1）。
    """
    state = _planning_state()
    state["roadmap"] = fallback_roadmap(state)
    state["current_window"] = {
        "milestone_id": state["roadmap"]["current_milestone"],
        "unit": UNIT_SESSION, "length": 2, "start_date": "2026-01-01",
        # 2 个执行单元、3 个任务 —— 与下面 completed 的 3 个 key 自洽
        "days": [{"day": 1, "theme": "t1", "tasks": [{"goal": "g1"}, {"goal": "g2"}]},
                 {"day": 2, "theme": "t2", "tasks": [{"goal": "g3"}]}],
    }
    state["plan_confirmed"] = True

    # 未完成 -> 不滚动
    state["plan_progress"] = {"day": 1, "task": 1, "completed": [], "finished": False}
    assert roll_window(state) is False
    assert state["current_window"] is not None

    # 完成：3 个任务共判定了 5 次（2 次重做）-> 实际比估计慢 -> 后续估计必须上调
    before = [m["sessions_est"] for m in state["roadmap"]["milestones"][1:]]
    state["plan_progress"] = {
        "day": 3, "task": 1,
        "completed": ["1-1", "1-2", "2-1"], "finished": True, "attempts": 5,
    }
    assert roll_window(state) is True

    assert state["roadmap"]["milestones"][0]["status"] == MILESTONE_DONE
    assert state["current_window"]["milestone_id"] == state["roadmap"]["current_milestone"]
    assert state["plan_progress"]["completed"] == []            # 游标重置
    assert state["plan_confirmed"] is True                      # 不必重复确认
    after = [m["sessions_est"] for m in state["roadmap"]["milestones"][1:]]
    # 严格上调：有重做时 ratio > 1，若这里变成相等就说明速度信号又失效了
    assert all(a > b for a, b in zip(after, before)), f"重做过后重估应上调：{before} -> {after}"


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
    days = normalize_plan_data(data, horizon=4, session_minutes=30)
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
    days = normalize_plan_data(data, horizon=1, session_minutes=60)
    tasks = days[0]["tasks"]
    assert len(tasks) == MAX_TASKS_PER_DAY == 3
    assert tasks[0]["minutes"] == 45                # 字符串分钟被转成整数（未超上限）
    assert [t["goal"] for t in tasks] == ["任务1", "任务2", "任务3"]


# ---------------------------------------------------------------------------
# 任务粒度约束：单任务时长 ≤ 单次可投入时长（**代码强制**，A-14 新增）
# ---------------------------------------------------------------------------

def test_clamp_task_minutes_enforces_session_cap():
    """模型可以排 45 分钟的任务，但用户只有 15 分钟 —— 超出的由代码砍掉。"""
    assert clamp_task_minutes(45, 15) == 15          # 超上限 -> 砍到上限
    assert clamp_task_minutes(45, 60) == 45          # 未超 -> 原样保留
    assert clamp_task_minutes(None, 20) == 20        # 模型没给 -> 取单次时长
    assert clamp_task_minutes(0, 20) == 20           # 0 视为"没给"
    assert clamp_task_minutes(-5, 20) == 20          # 负数同样兜底
    assert clamp_task_minutes("30分钟", 20) == 20    # 字符串也不放过
    assert clamp_task_minutes(45, None) == DEFAULT_TASK_MINUTES


def test_clamp_task_minutes_floor_only_guards_the_cap():
    """下限只保护**上限**，不抬高短任务本身。

    "3 分钟做完的小练习"是合法的碎片化任务；把它抬到 5 分钟反而是编造。
    下限真正要防的是 `session_minutes` 退化到 0（会排出 0 分钟的任务）。
    """
    assert clamp_task_minutes(3, 20) == 3            # 短任务原样保留
    assert clamp_task_minutes(60, 1) == MIN_TASK_MINUTES   # 上限过小时被托到下限


def test_normalize_plan_data_clamps_overlong_tasks():
    """清洗阶段必须把超长任务砍到单次可完成 —— 这是碎片化的硬约束。"""
    data = {"days": [{"theme": "t", "tasks": [
        {"goal": "g1", "minutes": 90},
        {"goal": "g2", "minutes": 10},
    ]}]}
    tasks = normalize_plan_data(data, horizon=1, session_minutes=15)[0]["tasks"]
    assert [t["minutes"] for t in tasks] == [15, 10]


def test_fallback_plan_respects_session_minutes():
    """兜底计划也必须遵守粒度约束（不能因为"是兜底"就超时）。"""
    days = fallback_plan(2, goal="Python", session_minutes=10)
    assert all(task["minutes"] == 10 for day in days for task in day["tasks"])


def test_normalize_plan_fallback_when_empty():
    days = normalize_plan_data({}, horizon=3, goal="Python 数据分析",
                               weak_points=["pandas"], session_minutes=30)
    assert len(days) == 3
    assert all(d["tasks"] for d in days)
    assert "pandas" in days[0]["theme"]              # 兜底计划优先围绕薄弱点
    assert days[0]["tasks"][0]["minutes"] == 30


def test_fallback_plan_cycles_topics():
    days = fallback_plan(4, goal="Python", weak_points=["A", "B"], session_minutes=20)
    assert [d["theme"] for d in days] == ["A 强化", "B 强化", "A 强化", "B 强化"]
    assert all(d["tasks"][0]["minutes"] == 20 for d in days)


# ---------------------------------------------------------------------------
# 4) 确认门控（B / B2 的核心）
# ---------------------------------------------------------------------------

def test_guard_requires_confirmation():
    plan = {"length": 1, "start_date": "2026-01-01",
            "days": [{"day": 1, "theme": "t", "tasks": [{"goal": "g"}]}]}

    # 有计划但未确认 -> 必须拦住，不能进入 learning
    state = _planning_state(current_window=plan, plan_confirmed=False)
    assert is_confirmed(state) is False
    assert try_advance(state) is None
    assert state["current_stage"] == STAGE_PLANNING

    # 用户确认后 -> 放行
    state["plan_confirmed"] = True
    assert try_advance(state) == STAGE_LEARNING


def test_confirm_plan_keeps_waiting_without_llm():
    """没有可用的 LLM（无 Key）时：判定返回 None，且绝不误置确认标志。

    强制"无 Key"环境（注入 `api_key=None`），不依赖真实环境变量：
    以前写成 `if os.getenv(...): return`，结果是**配了 Key 就什么都不验**。
    """
    from coach.config import Settings, get_settings, set_settings

    original = get_settings()
    set_settings(Settings(api_key=None))          # 模拟"无 Key"
    try:
        state = _planning_state(
            current_window={"length": 1, "start_date": "2026-01-01",
                          "days": [{"day": 1, "theme": "t", "tasks": [{"goal": "g"}]}]},
            plan_confirmed=False,
        )
        verdict = confirm_plan(state, "可以，开始吧")
        assert verdict is None
        assert state["plan_confirmed"] is False
    finally:
        set_settings(original)


# ---------------------------------------------------------------------------
# 5) 真实用例（需 Key）
# ---------------------------------------------------------------------------

def test_live_generate_plan():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SkipTest("未设置 DEEPSEEK_API_KEY，跳过真实计划生成")

    state = _planning_state()
    assert ensure_plan(state) is True
    assert ensure_plan(state) is False               # 已存在 -> 不重复生成

    roadmap = state["roadmap"]
    window = state["current_window"]
    print("        路线图:", " / ".join(f"{m['id']} {m['title']}"
                                       f"(est {m['sessions_est']})"
                                       for m in roadmap["milestones"]))
    print(f"        执行窗口: {window['length']} {window['unit']} | 起始: {window['start_date']}")
    for day in window["days"]:
        goals = " / ".join(t["goal"] for t in day["tasks"])
        print(f"          第{day['day']}个单元 {day['theme']}: {goals}")

    assert roadmap["milestones"], "必须产出路线图"
    assert 1 <= window["length"] <= 7
    assert len(window["days"]) == window["length"]   # 窗口长度 = 单元数
    assert all(day["theme"] for day in window["days"])
    assert all(day["tasks"] for day in window["days"])
    assert state["plan_confirmed"] is False          # 新计划必须等待确认


def test_live_confirmation_judgement():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SkipTest("未设置 DEEPSEEK_API_KEY，跳过真实确认判定")

    plan = {"length": 1, "start_date": "2026-01-01",
            "days": [{"day": 1, "theme": "pandas 基础", "tasks": [{"goal": "读 CSV"}]}]}

    # 明确同意 -> 确认
    state = _planning_state(current_window=copy.deepcopy(plan), plan_confirmed=False)
    verdict = confirm_plan(state, "可以，就按这个计划开始吧")
    print("        同意判定:", verdict)
    assert verdict is not None and verdict.confirmed is True
    assert state["plan_confirmed"] is True

    # 要求修改 -> 不确认
    state2 = _planning_state(current_window=copy.deepcopy(plan), plan_confirmed=False)
    verdict2 = confirm_plan(state2, "第 3 天能不能简单一点？我怕跟不上")
    print("        修改判定:", verdict2)
    assert verdict2 is not None and verdict2.confirmed is False
    assert state2["plan_confirmed"] is False


# ---------------------------------------------------------------------------
# 6) D1 回归：速度重估必须是**任务粒度**（v0.14 审计修复）
# ---------------------------------------------------------------------------

def _window_state(attempts=None, per_unit: int = 2) -> dict:
    """一个"每单元 2 个任务"的已完成窗口（**真实流程可以产生**的状态）。"""
    state = _planning_state()
    state["roadmap"] = fallback_roadmap(state)
    state["current_window"] = {
        "milestone_id": state["roadmap"]["current_milestone"],
        "unit": UNIT_SESSION, "length": 2, "start_date": "2026-01-01",
        "days": [
            {"day": i + 1, "theme": f"t{i + 1}",
             "tasks": [{"goal": f"g{i + 1}-{j + 1}"} for j in range(per_unit)]}
            for i in range(2)
        ],
    }
    progress = {"day": 3, "task": 1, "completed": ["1-1", "1-2", "2-1", "2-2"],
                "finished": True}
    if attempts is not None:
        progress["attempts"] = attempts
    state["plan_progress"] = progress
    state["plan_confirmed"] = True
    return state


def test_window_usage_is_task_granular():
    """**分子分母必须同为任务粒度**，否则重估方向不可控。

    历史缺陷（审计发现并已修）：分子原用去重的 `completed`（任务位置数）、
    分母用**单元数** —— 每单元 2 个任务时 `ratio` 恒为 2（被钳到 1.5），
    于是后续里程碑被**无条件放大 50%**，而真正的"变慢"信号（重做）反而丢失。
    """
    # 无重做 -> ratio 恰为 1（**不再放大**）
    assert window_usage(_window_state(attempts=4)) == (4, 4)

    # 有重做 -> ratio > 1（这才是"比估计慢"的真信号）
    used, planned = window_usage(_window_state(attempts=7))
    assert (used, planned) == (7, 4)
    assert used > planned

    # 旧状态文件没有 attempts -> **中性**（ratio = 1），
    # 绝不能拿去重的 completed 冒充（那会被误读成"更快"而缩短估计）
    assert window_usage(_window_state()) == (4, 4)


def test_roll_window_does_not_inflate_without_retries():
    """每单元 2 个任务、**没有重做**时，后续里程碑的估计必须**保持不变**。

    这是 D1 的直接回归：修复前该场景会无条件 ×1.5。
    """
    state = _window_state(attempts=4)
    before = [m["sessions_est"] for m in state["roadmap"]["milestones"][1:]]

    assert roll_window(state) is True

    after = [m["sessions_est"] for m in state["roadmap"]["milestones"][1:]]
    assert after == before, f"无重做不应放大估计：{before} -> {after}"


def test_roll_window_inflates_when_retries_happened():
    """真的重做过（attempts 明显大于任务数）时，才该上调后续估计。"""
    state = _window_state(attempts=8)          # 4 个任务、8 次判定 -> 慢一倍
    before = [m["sessions_est"] for m in state["roadmap"]["milestones"][1:]]

    assert roll_window(state) is True

    after = [m["sessions_est"] for m in state["roadmap"]["milestones"][1:]]
    assert all(a >= b for a, b in zip(after, before))
    assert any(a > b for a, b in zip(after, before)), f"重做应上调：{before} -> {after}"


def test_roll_window_resets_progress_with_attempts_key():
    """滚动后的游标必须带 `attempts`（否则速度信号在下一个窗口丢失）。"""
    state = _window_state(attempts=5)

    assert roll_window(state) is True

    assert "attempts" in state["plan_progress"], "新游标漏了 attempts 键"
    assert state["plan_progress"]["attempts"] == 0


# ---------------------------------------------------------------------------
# 7) 模型把布尔写成字符串时，绝不能误判（v0.14 审计修复）
# ---------------------------------------------------------------------------

def test_confirm_plan_rejects_string_false():
    """`{"confirmed": "false"}` 必须被当成"**未确认**"（fail-closed）。

    回归自真实缺陷：`bool("false") is True` —— 会把"用户还在犹豫"判成"已确认"，
    直接导致**状态机误推进到 learning**（未确认就开始教学）。
    """
    from coach.llm import client as llm_client

    original = llm_client.json_call
    llm_client.json_call = lambda *a, **k: {"confirmed": "false", "reason": "用户还在犹豫"}
    try:
        state = _planning_state()
        state["current_window"] = {
            "milestone_id": "M1", "unit": UNIT_SESSION, "length": 1,
            "start_date": "2026-01-01",
            "days": [{"day": 1, "theme": "t", "tasks": [{"goal": "g"}]}],
        }
        state["plan_confirmed"] = False

        verdict = confirm_plan(state, "我再想想吧")

        assert verdict is not None and verdict.confirmed is False
        assert state["plan_confirmed"] is False, "字符串 false 不得置为已确认"
    finally:
        llm_client.json_call = original


# ---------------------------------------------------------------------------
# 极简 runner（共用实现见 tests/_runner.py）
# ---------------------------------------------------------------------------

from _runner import SkipTest, run_tests        # noqa: E402


def main() -> int:
    return run_tests(globals())


if __name__ == "__main__":
    raise SystemExit(main())
