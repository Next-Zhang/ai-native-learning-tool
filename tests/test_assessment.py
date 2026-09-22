r"""V0.3b 能力测评验收测试（纯 Python 断言脚本）。

运行（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\test_assessment.py

覆盖：
- 三档判定 -> 分数映射、中文/英文别名归一化
- 大纲清洗：重新编号、截断到 5 题、丢弃空题、难度收敛、空大纲兜底
- 知识点聚合平均分、薄弱点阈值（< 0.6）、边界值（0.6 不算薄弱）
- 题量进度：current_index、is_finished
- **闭环**：finalize 产出画像后，状态机守卫必须允许进入 planning
- 真实 LLM 用例（需要 DEEPSEEK_API_KEY；无 Key 时自动跳过）
"""

import copy
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assessor import (
    MAX_QUESTIONS,
    WEAK_THRESHOLD,
    AnswerRecord,
    aggregate_scores,
    current_index,
    derive_weak_points,
    finalize,
    is_finished,
    normalize_plan,
    verdict_score,
)
from stages import try_advance
from state import DEFAULT_STATE, STAGE_ASSESSMENT


def _assessment_state(records=None, questions=None) -> dict:
    state = copy.deepcopy(DEFAULT_STATE)
    state["current_stage"] = STAGE_ASSESSMENT
    state["learning_goal"] = "Python 数据分析"
    state["assessment_progress"] = {
        "plan": questions if questions is not None else [
            {"index": 1, "topic": "变量与类型", "difficulty": 1},
            {"index": 2, "topic": "列表切片", "difficulty": 2},
            {"index": 3, "topic": "列表切片", "difficulty": 3},
        ],
        "records": records or [],
        "finished": False,
    }
    return state


# ---------------------------------------------------------------------------
# 1) 判定与分数
# ---------------------------------------------------------------------------

def test_verdict_score_mapping():
    assert verdict_score("mastered") == 1.0
    assert verdict_score("partial") == 0.5
    assert verdict_score("missing") == 0.0
    assert verdict_score("unknown_value") == 0.0


def test_verdict_aliases_are_normalized():
    assert AnswerRecord(index=1, verdict="掌握").verdict == "mastered"
    assert AnswerRecord(index=1, verdict="部分正确").verdict == "partial"
    assert AnswerRecord(index=1, verdict="不会").verdict == "missing"
    assert AnswerRecord(index=1, verdict="MASTERED").verdict == "mastered"
    assert AnswerRecord(index=1, verdict=None).verdict == "missing"
    assert AnswerRecord(index=1, verdict="乱写").verdict == "missing"


# ---------------------------------------------------------------------------
# 2) 大纲清洗
# ---------------------------------------------------------------------------

def test_normalize_plan_truncates_and_renumbers():
    raw = [{"topic": f"知识点{i}", "difficulty": i} for i in range(1, 7)]   # 6 题
    plan = normalize_plan(raw, goal="Python")
    assert len(plan) == MAX_QUESTIONS == 5
    assert [q["index"] for q in plan] == [1, 2, 3, 4, 5]


def test_normalize_plan_drops_empty_topics_and_clamps_difficulty():
    raw = [
        {"topic": "   ", "difficulty": 1},          # 空题丢弃
        {"topic": "字符串", "difficulty": 99},       # 难度收敛到 5
        {"topic": "字典", "difficulty": "x"},        # 非法难度 -> 1
    ]
    plan = normalize_plan(raw, goal="Python")
    assert [q["topic"] for q in plan] == ["字符串", "字典"]
    assert plan[0]["difficulty"] == 5
    assert plan[1]["difficulty"] == 1


def test_normalize_plan_fallback_when_empty():
    plan = normalize_plan([], goal="Python 数据分析")
    assert len(plan) == 3, "空大纲必须兜底为 3 题，保证流程可继续"
    assert all("Python 数据分析" in q["topic"] for q in plan)
    assert [q["index"] for q in plan] == [1, 2, 3]


# ---------------------------------------------------------------------------
# 3) 聚合与薄弱点
# ---------------------------------------------------------------------------

def test_aggregate_scores_averages_same_topic():
    records = [
        {"topic": "列表切片", "verdict": "mastered"},   # 1.0
        {"topic": "列表切片", "verdict": "partial"},    # 0.5
        {"topic": "函数参数", "verdict": "missing"},    # 0.0
    ]
    scores = aggregate_scores(records)
    assert scores["列表切片"] == 0.75          # (1.0 + 0.5) / 2
    assert scores["函数参数"] == 0.0
    assert aggregate_scores([]) == {}


def test_weak_points_threshold_boundary():
    scores = {"A": 1.0, "B": 0.6, "C": 0.5, "D": 0.0}
    weak = derive_weak_points(scores)
    assert weak == ["D", "C"], f"0.6 不应算薄弱、0.5 应算薄弱；实际 {weak}"
    assert WEAK_THRESHOLD == 0.6


def test_weak_points_sorted_by_score_ascending():
    scores = {"X": 0.5, "Y": 0.0, "Z": 0.25}
    assert derive_weak_points(scores) == ["Y", "Z", "X"]


# ---------------------------------------------------------------------------
# 4) 进度
# ---------------------------------------------------------------------------

def test_current_index_and_is_finished():
    progress = {"plan": [{"topic": "a"}, {"topic": "b"}, {"topic": "c"}],
                "records": [], "finished": False}
    assert current_index(progress) == 1
    assert is_finished({"assessment_progress": progress}) is False

    progress["records"] = [{"index": 1}, {"index": 2}]
    assert current_index(progress) == 3
    assert is_finished({"assessment_progress": progress}) is False

    progress["records"] = [{"index": 1}, {"index": 2}, {"index": 3}]
    assert is_finished({"assessment_progress": progress}) is True

    progress["finished"] = True
    assert current_index(progress) == 0


# ---------------------------------------------------------------------------
# 5) 闭环：finalize 之后必须能进入 planning
# ---------------------------------------------------------------------------

def test_finalize_writes_profile_and_unlocks_next_stage():
    state = _assessment_state(records=[
        {"index": 1, "topic": "变量与类型", "verdict": "mastered"},
        {"index": 2, "topic": "列表切片", "verdict": "partial"},
        {"index": 3, "topic": "列表切片", "verdict": "missing"},
    ])

    # 测评未结束时，守卫必须拦住（还不能进入 planning）
    assert try_advance(state) is None
    assert state["current_stage"] == STAGE_ASSESSMENT

    summary = finalize(state)

    assert state["skill_profile"] == {"变量与类型": 1.0, "列表切片": 0.25}
    assert state["weak_points"] == ["列表切片"]      # 0.25 < 0.6
    assert summary["weak_points"] == ["列表切片"]
    assert state["assessment_progress"]["finished"] is True

    # 闭环：画像已产出 -> 守卫放行
    assert try_advance(state) == "planning"
    assert state["current_stage"] == "planning"


# ---------------------------------------------------------------------------
# 6) 真实 LLM 用例（无 Key 自动跳过）
# ---------------------------------------------------------------------------

def test_live_plan_generation():
    """真实出题：只断言大纲结构（题量、主题非空、难度递增）。"""
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("        [跳过] 未设置 DEEPSEEK_API_KEY，跳过真实出题用例")
        return

    from assessor import ensure_plan

    state = copy.deepcopy(DEFAULT_STATE)
    state.update({"learning_goal": "Python 数据分析", "current_level": "学过一点基础",
                  "daily_minutes": 30, "target_date": "1个月"})
    state["current_stage"] = STAGE_ASSESSMENT

    assert ensure_plan(state) is True
    plan = state["assessment_progress"]["plan"]
    print("        生成大纲:", [(q["topic"], q["difficulty"]) for q in plan])

    assert 3 <= len(plan) <= 5
    assert all(q["topic"] for q in plan)
    assert [q["difficulty"] for q in plan] == sorted(q["difficulty"] for q in plan)


def test_live_judgement():
    """真实判卷：用受控题目（主题与答案匹配），验证 mastered / missing 两档。

    说明：不能用 ensure_plan 生成的题目去配固定答案 —— 生成的主题每次不同，
    固定答案会与题目不符（这本身也说明判卷器是看题的）。
    """
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("        [跳过] 未设置 DEEPSEEK_API_KEY，跳过真实判卷用例")
        return

    from assessor import record_answer

    state = _assessment_state(
        questions=[
            {"index": 1, "topic": "列表取值", "difficulty": 1},
            {"index": 2, "topic": "列表切片", "difficulty": 2},
        ]
    )

    good = record_answer(
        state,
        "可以用下标，比如 lst[0] 取第一个元素",
        "第 1 题（列表取值）：Python 里怎么取列表的第一个元素？",
    )
    assert good is not None and good.verdict == "mastered", good

    bad = record_answer(state, "我不会", "第 2 题（列表切片）：说说 lst[1:3] 的含义？")
    assert bad is not None and bad.verdict == "missing", bad


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
