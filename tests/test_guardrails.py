r"""内容层护栏（**F4**）的回归测试。

运行（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\test_guardrails.py

覆盖三件事：

1. **三条护栏各自真的会动手**（不是记录一下就完事）—— 尤其 G-1：
   **X-16 的真实原因就是模型在 learning 阶段自己宣布了验收结论**（I-2）。
2. **护栏只在它该管的阶段/内容种类上生效**（不乱改正常内容）。
3. **护栏自己失效不能影响主流程**（与 metrics / trace 同纪律）。
"""

import copy
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.domain import guardrails                                          # noqa: E402
from coach.domain.guardrails import (                                        # noqa: E402
    GUARDRAILS,
    Guardrail,
    GuardrailContext,
    run_guardrails,
    upcoming_task_goals,
)
from coach.domain.stages import STAGE_EVALUATION, STAGE_LEARNING             # noqa: E402
from coach.domain.state_schema import DEFAULT_STATE                          # noqa: E402
from coach.llm import client as llm_client                                   # noqa: E402
from coach.metrics import recorder as metrics                               # noqa: E402
from coach.orchestration.turn import run_turn                                # noqa: E402

metrics.disable()


def _reply_ctx(stage=STAGE_LEARNING, goals=()) -> GuardrailContext:
    return GuardrailContext(stage=stage, kind="reply", upcoming_task_goals=tuple(goals))


# ---------------------------------------------------------------------------
# 1) 清单本身的契约
# ---------------------------------------------------------------------------

def test_guardrails_are_unique_and_documented():
    """每条护栏都要有 id 与说明 —— 否则命中清单里的一个字符串毫无信息量。"""
    ids = [item.id for item in GUARDRAILS]
    assert len(ids) == len(set(ids)), f"id 重复：{ids}"
    for item in GUARDRAILS:
        assert item.id and item.description and callable(item.apply)


def test_only_known_guardrails_can_fire():
    """命中清单里的 id 必须都来自 GUARDRAILS（防拼写漂移）。"""
    known = {item.id for item in GUARDRAILS}
    report = run_guardrails("本轮通过验收！", _reply_ctx())
    assert set(report.hits) <= known


# ---------------------------------------------------------------------------
# 2) G-1 防抢答判定（I-2 / X-16）
# ---------------------------------------------------------------------------

def test_verdict_announcement_is_stripped_in_learning():
    """**learning 阶段不得宣布验收结论** —— 越界的那一句被删掉，其余保留。"""
    report = run_guardrails("这题你写对了，本轮通过验收！继续做下一题。", _reply_ctx())

    assert "verdict_announcement" in report.hits
    assert "通过验收" not in report.text
    assert "继续做下一题" in report.text, "正常内容不能被误删"


def test_verdict_announcement_falls_back_to_safe_text():
    """整条回复都在抢答时，用**确定性安全文本**顶上（绝不能给用户空白）。"""
    report = run_guardrails("验收通过！", _reply_ctx())

    assert report.hits == ["verdict_announcement"]
    assert "验收通过" not in report.text
    assert "由系统在下一步统一给出" in report.text, "必须换成确定性安全文本"

    # 安全文本自己不能再触发护栏（否则会自己套自己）
    again = run_guardrails(report.text, _reply_ctx())
    assert again.hits == [] and again.text == report.text


def test_verdict_announcement_does_not_fire_in_other_stages():
    """**收窄适用范围**：这条护栏只为 learning 而立，别去改别的阶段的内容。"""
    text = "本轮通过验收！"
    report = run_guardrails(text, _reply_ctx(stage=STAGE_EVALUATION))
    assert report.hits == [] and report.text == text


def test_ordinary_wording_is_not_touched():
    """"通过"是个常见词，护栏绝不能把正常讲解也删掉（短清单的意义）。"""
    text = "你可以通过 df.groupby 来聚合；这条路也走得通。"
    report = run_guardrails(text, _reply_ctx())
    assert report.hits == [] and report.text == text


# ---------------------------------------------------------------------------
# 3) G-2 摘要不承载判定（I-14）
# ---------------------------------------------------------------------------

def test_summary_supplement_with_judgement_words_is_dropped():
    """润色段一旦带判定词就**整段丢弃**，只留确定性骨架。"""
    context = GuardrailContext(kind="summary_supplement")

    bad = run_guardrails("用户已掌握 groupby，薄弱点是多列聚合。", context)
    assert bad.hits == ["summary_judgement_words"]
    assert bad.text == ""

    good = run_guardrails("用户练了 groupby，卡在多列取值。", context)
    assert good.hits == [] and good.text


def test_summary_guardrail_does_not_touch_replies():
    """同一个词组在**对话回复**里不算越界（内容种类不同）。"""
    report = run_guardrails("这题考的是掌握度判断。", _reply_ctx())
    assert report.hits == []


# ---------------------------------------------------------------------------
# 4) G-3 不提前布置后续任务
# ---------------------------------------------------------------------------

def test_premature_next_task_appends_a_reminder():
    report = run_guardrails(
        "你先做这个。另外顺便说一下，用 matplotlib 画折线图看趋势。",
        _reply_ctx(goals=("用 matplotlib 画折线图看趋势",)),
    )
    assert report.hits == ["premature_next_task"]
    assert report.text.startswith("你先做这个"), "正文不能被删（那会伤正常讲解）"
    assert "后续任务请等系统下发" in report.text


def test_short_or_current_goal_is_not_flagged():
    """太短的目标文本容易误伤；与当前任务相同的目标更是必须放过。"""
    report = run_guardrails("多列聚合是重点。", _reply_ctx(goals=("多列聚合",)))
    assert report.hits == []


def test_upcoming_task_goals_skips_the_current_task():
    state = {
        "today_task": {"goal": "用 groupby 统计月度销售额"},
        "current_window": {"days": [
            {"tasks": [{"goal": "用 groupby 统计月度销售额"},
                       {"goal": "用 matplotlib 画折线图看趋势"}]},
        ]},
    }
    goals = upcoming_task_goals(state)
    assert goals == ("用 matplotlib 画折线图看趋势",)


# ---------------------------------------------------------------------------
# 5) 失败要 fail-safe
# ---------------------------------------------------------------------------

@contextmanager
def _broken_guardrail():
    """临时塞一条会抛异常的护栏 —— 主流程必须完全不受影响。"""
    original = guardrails.GUARDRAILS

    def boom(text, context):
        raise RuntimeError("护栏自己炸了")

    guardrails.GUARDRAILS = original + (
        Guardrail(id="exploding", description="测试用：一定失败", apply=boom),
    )
    try:
        yield
    finally:
        guardrails.GUARDRAILS = original


def test_a_broken_guardrail_never_breaks_the_text():
    with _broken_guardrail():
        report = run_guardrails("这题你写对了，本轮通过验收！继续。", _reply_ctx())

    assert "exploding" not in report.hits, "炸掉的护栏不该被记成命中"
    assert "通过验收" not in report.text, "其它护栏必须照常生效"


# ---------------------------------------------------------------------------
# 6) 跨层：走真实 run_turn
# ---------------------------------------------------------------------------

@contextmanager
def _no_save():
    from coach.orchestration import executor as executor_module

    original = executor_module.save_state
    executor_module.save_state = lambda state: None
    try:
        yield
    finally:
        executor_module.save_state = original


@contextmanager
def _fixed_reply(text: str):
    original = llm_client.chat
    llm_client.chat = lambda messages, **kwargs: text
    try:
        yield
    finally:
        llm_client.chat = original


def _learning_state() -> dict:
    """已在 learning、画像齐全、还没下发任务 —— 于是本轮只有对话会调模型。"""
    state = copy.deepcopy(DEFAULT_STATE)
    state.update({
        "learning_goal": "用 pandas 做销售分析",
        "current_level": "会一点 Python",
        "session_minutes": 30,
        "target_date": "2026-11-01",
        "current_stage": "learning",
        "plan_confirmed": True,
        "current_window": {"length": 1, "unit": "session", "milestone_id": "M1",
                           "days": [{"theme": "D1", "tasks": [
                               {"goal": "用 groupby 统计月度销售额",
                               "exercise": "按时聚合", "minutes": 20,
                               "done_criteria": "得到月度合计"}]}]},
    })
    return state


def test_turn_strips_the_models_verdict_announcement():
    """**X-16 的回归**：模型抢答时，用户拿到的那句话里不能再有验收结论。"""
    state = _learning_state()

    with _no_save(), _fixed_reply("你写得不错，本轮通过验收！我们接着做下一题。"):
        result = run_turn(state, "我做完了")

    assert "通过验收" not in result.answer
    assert "接着做下一题" in result.answer
    assert result.guardrail_hits == ["verdict_announcement"]
    # 冻结在历史里的也必须是修正后的文本（否则下一轮又会读到抢答）
    assert "通过验收" not in state["conversation_history"][-1]["content"]


def test_turn_records_nothing_when_the_reply_is_clean():
    state = _learning_state()

    with _no_save(), _fixed_reply("我们先把 groupby 的聚合写完吧。"):
        result = run_turn(state, "继续")

    assert result.guardrail_hits == []
    assert result.answer == "我们先把 groupby 的聚合写完吧。"


# ---------------------------------------------------------------------------
# 极简 runner（共用实现见 tests/_runner.py）
# ---------------------------------------------------------------------------

from _runner import SkipTest, run_tests        # noqa: E402,F401


def main() -> int:
    return run_tests(globals())


if __name__ == "__main__":
    raise SystemExit(main())
