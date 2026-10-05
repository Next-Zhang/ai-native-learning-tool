r"""V0.3d 每日任务验收测试（纯 Python 断言脚本）。

运行（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\test_daily.py

覆盖：
- 计划游标：默认值、字段补齐、异常值兜底
- 任务查找：正常取出、越界返回 None
- 顺序推进：task 1→2、day 1→2、排完返回 None；跳过全空的天
- build_today_task：写入 state、计划排完时返回 None 并标记 finished
- mark_task_done：记录已完成、推进游标、清空 today_task / pending_submission
- 守卫：有今日任务但未提交 -> 拦住；有提交 -> 放行到 evaluation
- 提交判定：无 Key 时不误报（返回 None 且不写 pending_submission）
- 真实用例（需 Key）：提问 -> false；给出代码/答案 -> true 且写入提交
"""

import copy
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.domain.cursor import (
    build_today_task,
    first_valid_position,
    get_progress,
    is_plan_finished,
    lookup_task,
    mark_task_done,
    next_position,
)
from coach.domain.stages import STAGE_EVALUATION, STAGE_LEARNING, try_advance
from coach.domain.state_schema import DEFAULT_STATE
from coach.services.daily_task import describe_progress, detect_submission


def _plan(days=None) -> dict:
    return {
        "horizon_days": 2,
        "start_date": "2026-01-01",
        "days": days if days is not None else [
            {
                "day": 1, "theme": "读取数据",
                "tasks": [
                    {"goal": "读取 CSV", "material": "教程", "exercise": "写读取代码",
                     "minutes": 30, "done_criteria": "能读出前 5 行"},
                    {"goal": "查看数据", "material": "教程", "exercise": "用 head()",
                     "minutes": 20, "done_criteria": "能解释 head() 的作用"},
                ],
            },
            {
                "day": 2, "theme": "分组聚合",
                "tasks": [
                    {"goal": "groupby 分组", "material": "教程", "exercise": "分组求均值",
                     "minutes": 30, "done_criteria": "能算出分组均值"},
                ],
            },
        ],
    }


def _learning_state(plan=None, **extra) -> dict:
    state = copy.deepcopy(DEFAULT_STATE)
    state.update({
        "learning_goal": "Python 数据分析",
        "current_level": "学过一点基础",
        "daily_minutes": 30,
        "target_date": "1个月",
        "current_stage": STAGE_LEARNING,
        "current_plan": plan if plan is not None else _plan(),
        "plan_confirmed": True,
        "plan_progress": {"day": 1, "task": 1, "completed": [], "finished": False},
    })
    state.update(extra)
    return state


# ---------------------------------------------------------------------------
# 1) 游标与查找
# ---------------------------------------------------------------------------

def test_get_progress_defaults_and_merge():
    assert get_progress({}) == {"day": 1, "task": 1, "completed": [], "finished": False}

    # 部分字段 -> 用默认值补齐
    progress = get_progress({"plan_progress": {"day": 3}})
    assert progress["day"] == 3 and progress["task"] == 1 and progress["completed"] == []

    # completed 不是列表 -> 兜底为空列表
    assert get_progress({"plan_progress": {"completed": "oops"}})["completed"] == []


def test_lookup_task():
    plan = _plan()
    task = lookup_task(plan, 1, 2)
    assert task is not None
    assert task["day"] == 1 and task["task"] == 2
    assert task["theme"] == "读取数据"
    assert task["goal"] == "查看数据"
    assert task["minutes"] == 20

    assert lookup_task(plan, 1, 3) is None      # 当天没有第 3 个任务
    assert lookup_task(plan, 3, 1) is None      # 没有第 3 天
    assert lookup_task({}, 1, 1) is None


def test_next_position_sequence():
    plan = _plan()
    assert next_position(plan, 1, 1) == (1, 2)
    assert next_position(plan, 1, 2) == (2, 1)
    assert next_position(plan, 2, 1) is None    # 计划排完
    assert next_position(plan, 9, 1) is None


def test_first_valid_position_skips_empty_days():
    plan = _plan(days=[
        {"day": 1, "theme": "空白天", "tasks": []},
        {"day": 2, "theme": "有任务", "tasks": [{"goal": "g", "minutes": 10}]},
    ])
    assert first_valid_position(plan, 1, 1) == (2, 1)
    assert lookup_task(plan, 1, 1) is None


# ---------------------------------------------------------------------------
# 2) 任务构建与推进
# ---------------------------------------------------------------------------

def test_build_today_task_writes_state():
    state = _learning_state()
    task = build_today_task(state)

    assert task is not None
    assert task["day"] == 1 and task["task"] == 1
    assert state["today_task"]["goal"] == "读取 CSV"
    assert state["plan_progress"]["day"] == 1
    assert state["plan_progress"]["task"] == 1
    assert state["plan_progress"]["finished"] is False


def test_mark_task_done_advances_and_clears():
    state = _learning_state()
    build_today_task(state)
    state["pending_submission"] = {"content": "我的答案"}

    progress = mark_task_done(state)

    assert progress["completed"] == ["1-1"]
    assert (progress["day"], progress["task"]) == (1, 2)
    assert progress["finished"] is False
    assert state["today_task"] is None                 # 准备下一个任务
    assert state["pending_submission"] is None         # 清空待验收内容

    # 再完成一个 -> 进入第 2 天
    build_today_task(state)
    progress = mark_task_done(state)
    assert progress["completed"] == ["1-1", "1-2"]
    assert (progress["day"], progress["task"]) == (2, 1)


def test_build_today_task_none_when_plan_finished():
    plan = _plan(days=[{"day": 1, "theme": "唯一一天",
                        "tasks": [{"goal": "唯一任务", "minutes": 10}]}])
    state = _learning_state(plan=plan)

    assert build_today_task(state) is not None
    mark_task_done(state)

    assert is_plan_finished(state) is True
    assert build_today_task(state) is None
    assert state["plan_progress"]["finished"] is True
    assert "已全部完成" in describe_progress(state)


def test_describe_progress_line():
    state = _learning_state()
    build_today_task(state)
    line = describe_progress(state)
    assert "第 1/2 天" in line and "第 1 个任务" in line


# ---------------------------------------------------------------------------
# 3) 守卫：必须提交才能进入验收
# ---------------------------------------------------------------------------

def test_guard_requires_submission():
    state = _learning_state()
    build_today_task(state)

    # 有今日任务但未提交 -> 拦住
    assert try_advance(state) is None
    assert state["current_stage"] == STAGE_LEARNING

    # 有提交 -> 放行
    state["pending_submission"] = {"content": "我写的代码", "reason": "用户提交了代码"}
    assert try_advance(state) == STAGE_EVALUATION


def test_detect_submission_without_llm_keeps_state():
    if os.getenv("DEEPSEEK_API_KEY"):
        print("        [跳过] 本用例仅在无 API Key 时验证失败兜底")
        return

    state = _learning_state()
    build_today_task(state)

    verdict = detect_submission(state, "我写好了 df = pd.read_csv('a.csv')")

    assert verdict is None
    assert state["pending_submission"] is None        # 绝不误报提交
    assert try_advance(state) is None                 # 因此不能进入验收


# ---------------------------------------------------------------------------
# 4) 真实用例（需 Key）
# ---------------------------------------------------------------------------

def test_live_submission_detection():
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("        [跳过] 未设置 DEEPSEEK_API_KEY，跳过真实提交判定")
        return

    # 提问 -> 不算提交
    state = _learning_state()
    build_today_task(state)
    question = detect_submission(state, "这个 read_csv 的 encoding 参数是什么意思？")
    print("        提问判定:", question)
    assert question is not None and question.is_submission is False
    assert state["pending_submission"] is None

    # 给出代码 -> 算提交，并写入 pending_submission
    state2 = _learning_state()
    build_today_task(state2)
    answer = detect_submission(
        state2,
        "我写好了：import pandas as pd\n df = pd.read_csv('sales.csv')\n print(df.head())",
    )
    print("        提交判定:", answer)
    assert answer is not None and answer.is_submission is True
    assert state2["pending_submission"] is not None
    assert "read_csv" in state2["pending_submission"]["content"]
    assert try_advance(state2) == STAGE_EVALUATION


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
