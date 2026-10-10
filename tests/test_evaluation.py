r"""V0.3e 结果验收与画像更新验收测试（纯 Python 断言脚本）。

运行（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\test_evaluation.py

覆盖：
- 完成度 -> 掌握度映射、中文/英文别名归一
- 掌握度由完成度推导（模型给的分不作数，保证口径确定）
- **动作一致性守卫**：pass 只在 completed 时允许；partial -> supplement；not_completed -> retry
- 错误类型归一（None / 字符串 / 列表 / 非法类型）
- apply_update：pass 分支推进游标并更新画像；retry 分支保留任务、清空提交
- 画像新旧平均、薄弱点按 < 0.6 重算
- 守卫链：未应用验收结论不得回 learning（v0.16 合并了 profile_update 阶段）
- 无 Key 时判定失败不误推进；真实用例：提交正确代码判通过、乱答判重做
"""

import copy
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.domain.evaluation_rules import (
    completion_score,
    normalize_action,
    normalize_error_types,
)
from coach.domain.models import EvaluationResult
from coach.domain.stages import (
    STAGE_EVALUATION,
    STAGE_LEARNING,
    try_advance,
)
from coach.domain.state_schema import DEFAULT_STATE, ensure_keys
from coach.services.evaluation import apply_update, evaluate


def _plan() -> dict:
    """执行窗口用**当前结构**（`length`；`horizon_days` 是 v0.14 之前的旧名）。"""
    return {
        "length": 2,
        "unit": "session",
        "start_date": "2026-01-01",
        "days": [
            {"day": 1, "theme": "读取数据", "tasks": [
                {"goal": "读 CSV 并看前 5 行", "material": "教程", "exercise": "写代码",
                 "minutes": 30, "done_criteria": "能输出前 5 行"},
                {"goal": "查看数据形状", "material": "教程", "exercise": "用 shape",
                 "minutes": 20, "done_criteria": "能解释 shape"},
            ]},
            {"day": 2, "theme": "分组聚合", "tasks": [
                {"goal": "分组求均值", "material": "教程", "exercise": "groupby",
                 "minutes": 30, "done_criteria": "能算出分组均值"},
            ]},
        ],
    }


def _evaluation_state(**extra) -> dict:
    state = copy.deepcopy(DEFAULT_STATE)
    state.update({
        "learning_goal": "Python 数据分析",
        "current_stage": STAGE_EVALUATION,
        "current_window": _plan(),
        "plan_confirmed": True,
        "plan_progress": {"day": 1, "task": 1, "completed": [], "finished": False},
        "today_task": {
            "day": 1, "task": 1, "theme": "读取数据",
            "goal": "读 CSV 并看前 5 行", "material": "教程",
            "exercise": "写代码", "minutes": 30, "done_criteria": "能输出前 5 行",
        },
        "pending_submission": {"content": "df = pd.read_csv('a.csv'); print(df.head())",
                               "reason": "提交了代码"},
    })
    state.update(extra)
    return state


def _latest(completion: str, action: str, topic: str = "读取数据") -> dict:
    return EvaluationResult(
        completion=completion, next_action=action, topic=topic,
        feedback="反馈", reason="理由",
    ).model_dump()


# ---------------------------------------------------------------------------
# 1) 映射与一致性
# ---------------------------------------------------------------------------

def test_completion_score_mapping():
    assert completion_score("completed") == 1.0
    assert completion_score("partial") == 0.5
    assert completion_score("not_completed") == 0.0
    assert completion_score("unknown") == 0.0


def test_completion_aliases():
    assert EvaluationResult(completion="完成").completion == "completed"
    assert EvaluationResult(completion="已完成").completion == "completed"
    assert EvaluationResult(completion="DONE").completion == "completed"
    assert EvaluationResult(completion="部分完成").completion == "partial"
    assert EvaluationResult(completion="未完成").completion == "not_completed"
    assert EvaluationResult(completion="乱写").completion == "not_completed"   # 兜底为最保守


def test_mastery_is_derived_from_completion():
    # 即使模型给出 mastery=0.9，只要完成度是 partial，掌握度必须是 0.5
    result = EvaluationResult(completion="partial", mastery=0.9)
    assert result.mastery == 0.5
    assert EvaluationResult(completion="completed", mastery=0.1).mastery == 1.0


def test_action_consistency_guard():
    # 没做完不能通过
    assert normalize_action("completed", "pass") == "pass"
    assert normalize_action("partial", "pass") == "supplement"
    assert normalize_action("not_completed", "pass") == "retry"
    # 非法/缺省动作按完成度推导
    assert normalize_action("completed", "") == "pass"
    assert normalize_action("partial", "") == "supplement"
    assert normalize_action("not_completed", "xx") == "retry"
    # 中文别名
    assert EvaluationResult(completion="completed", next_action="通过").next_action == "pass"
    assert EvaluationResult(completion="not_completed", next_action="重做").next_action == "retry"
    # 模型"自相矛盾"时由代码纠正
    assert EvaluationResult(completion="partial", next_action="pass").next_action == "supplement"


def test_error_types_normalization():
    assert normalize_error_types(None) == []
    assert normalize_error_types("语法错误") == ["语法错误"]
    assert normalize_error_types(["概念混淆", "", "  边界情况遗漏 "]) == ["概念混淆", "边界情况遗漏"]
    assert normalize_error_types({"a": 1}) == []


# ---------------------------------------------------------------------------
# 2) apply_update
# ---------------------------------------------------------------------------

def test_apply_update_pass_advances_cursor():
    state = _evaluation_state(latest_result=_latest("completed", "pass"))
    # v0.18：画像**由证据派生**，所以"已有知识点"必须作为证据存在。
    # 直接写 `skill_profile` 是改造前的写法，现在会被派生覆盖 ——
    # 走一次 `ensure_keys`（与 `load_state` 同路径）才是真实场景：
    # 旧用户的画像就是这样被补种成证据的。
    state["skill_profile"] = {"读取数据": 0.5}
    ensure_keys(state)

    summary = apply_update(state)

    assert summary["action"] == "pass"
    # 画像：已有知识点取新旧平均 (0.5 + 1.0)/2
    assert state["skill_profile"]["读取数据"] == 0.75
    assert state["weak_points"] == []                      # 0.75 >= 0.6 不算薄弱
    # 游标推进：记录已完成、准备下一个任务
    assert state["plan_progress"]["completed"] == ["1-1"]
    assert (state["plan_progress"]["day"], state["plan_progress"]["task"]) == (1, 2)
    assert state["today_task"] is None
    assert state["pending_submission"] is None
    assert state["latest_result_applied"] is True


def test_apply_update_retry_keeps_same_task():
    state = _evaluation_state(latest_result=_latest("not_completed", "retry", topic="读取数据"))

    summary = apply_update(state)

    assert summary["action"] == "retry"
    # 游标不动、任务保留、提交清空（让用户重做）
    assert state["plan_progress"]["completed"] == []
    assert (state["plan_progress"]["day"], state["plan_progress"]["task"]) == (1, 1)
    assert state["today_task"] is not None
    assert state["pending_submission"] is None
    # 画像写入 0.0 -> 成为薄弱点
    assert state["skill_profile"]["读取数据"] == 0.0
    assert state["weak_points"] == ["读取数据"]


def test_apply_update_new_topic_and_partial():
    state = _evaluation_state(latest_result=_latest("partial", "supplement", topic="分组聚合"))

    apply_update(state)

    assert state["skill_profile"]["分组聚合"] == 0.5
    assert state["weak_points"] == ["分组聚合"]            # 0.5 < 0.6
    assert state["today_task"] is not None                 # 未通过 -> 保留任务


# ---------------------------------------------------------------------------
# 3) 守卫链
# ---------------------------------------------------------------------------

def test_guard_chain_evaluation_to_learning():
    state = _evaluation_state()          # 有提交，但没有判定结论

    # 无结论 -> 不能推进
    assert try_advance(state) is None
    assert state["current_stage"] == STAGE_EVALUATION

    # 有结论但**未应用到画像** -> 仍不能推进
    # （v0.16：evaluation → learning 是直接回路，守卫是"已应用"，防止跳过画像更新）
    state["latest_result"] = _latest("completed", "pass")
    assert state["latest_result_applied"] is False
    assert try_advance(state) is None
    assert state["current_stage"] == STAGE_EVALUATION

    # 应用后 -> 回到学习任务
    apply_update(state)
    assert try_advance(state) == STAGE_LEARNING


def test_evaluate_without_llm_keeps_state():
    """强制"无 Key"环境（注入 `api_key=None`），验证失败兜底。

    不再依赖真实环境变量：以前写成 `if os.getenv(...): return`，
    结果是**配了 Key 就什么都不验**（审计发现的反向守卫）。
    """
    from coach.config import Settings, get_settings, set_settings

    original = get_settings()
    set_settings(Settings(api_key=None))          # 模拟"无 Key"
    try:
        state = _evaluation_state()
        result = evaluate(state)

        assert result is None
        assert state["latest_result"] is None                  # 绝不写入假判定
        assert state["current_stage"] == STAGE_EVALUATION
        assert try_advance(state) is None                      # 因此不能推进
    finally:
        set_settings(original)


# ---------------------------------------------------------------------------
# 4) 真实用例（需 Key）
# ---------------------------------------------------------------------------

def test_live_evaluate_pass_and_retry():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SkipTest("未设置 DEEPSEEK_API_KEY，跳过真实验收判定")

    # 正确提交 -> completed / pass
    good = _evaluation_state(pending_submission={
        "content": "import pandas as pd\ndf = pd.read_csv('sales.csv')\nprint(df.head())",
        "reason": "提交代码",
    })
    result = evaluate(good)
    print("        正确提交判定:", result.completion, result.next_action, result.error_types)
    assert result is not None
    assert result.completion == "completed"
    assert result.next_action == "pass"
    assert good["latest_result"]["mastery"] == 1.0
    assert good["latest_result_applied"] is False
    assert try_advance(good) is None       # v0.16：未应用不得推进（回 learning 的唯一守卫）

    # 乱答 -> not_completed / retry
    bad = _evaluation_state(pending_submission={"content": "我不会，随便写点", "reason": "提交"})
    result2 = evaluate(bad)
    print("        乱答判定:", result2.completion, result2.next_action)
    assert result2 is not None
    assert result2.completion == "not_completed"
    assert result2.next_action == "retry"


# ---------------------------------------------------------------------------
# 极简 runner（共用实现见 tests/_runner.py）
# ---------------------------------------------------------------------------

from _runner import SkipTest, run_tests        # noqa: E402


def main() -> int:
    return run_tests(globals())


if __name__ == "__main__":
    raise SystemExit(main())
