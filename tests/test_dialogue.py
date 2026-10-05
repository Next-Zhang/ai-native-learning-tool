r"""对话装配与单轮编排的回归测试（真实运行缺陷 A / B / C）。

运行（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\test_dialogue.py

背景：一次真实 API 会话暴露了两个结构性缺陷——

**缺陷 A（教练抢答判定）**：`run_turn` 里状态推进发生在对话**之前**，于是"用户刚提交"
那一轮 `current_stage` 已经是 `evaluation`，模型拿到验收阶段提示词后**自己写出了
"验收结果：通过 ✅"**，而代码的判定要到下一轮才算。本次恰好一致，但结构上允许
"先告诉用户通过、再被代码推翻"。

**缺陷 B（教练自述覆盖状态）**：状态注入原先放在消息前部，当历史里模型自己承诺过
"下一个任务是 X"时，它会**继续那条自造的故事线**，无视注入的真实任务——直接违反
"状态驱动"。

**C（空跑）**：画像四项齐全后，每轮仍无条件调一次 `profile_extract`。
"""

import json
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.domain.models import UserProfile
from coach.domain.stages import (
    STAGE_EVALUATION,
    STAGE_GOAL_CLARIFICATION,
    STAGE_LEARNING,
)
from coach.domain.state_schema import DEFAULT_STATE
from coach.metrics import recorder as metrics
from coach.orchestration.turn import run_turn
from coach.prompts.stages import STAGE_PROMPTS
from coach.services.coach import describe_known_profile
from coach.services.daily_task import describe_today_task

# 本模块不采集指标（避免测试写真实 data/metrics/）
metrics.disable()


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

@contextmanager
def _patched_chat(captured: dict, answer: str = "（测试回答）"):
    """替换 `coach.llm.client.chat`，捕获真实组装出来的 messages。"""
    from coach.llm import client as llm_client

    original = llm_client.chat

    def fake(messages, settings=None, *, label=None):
        captured["messages"] = messages
        captured["label"] = label
        return answer

    llm_client.chat = fake
    try:
        yield
    finally:
        llm_client.chat = original


@contextmanager
def _no_save():
    """阻断落盘，避免测试写真实 data/user_state.json。"""
    from coach.orchestration import turn as turn_module

    original = turn_module.save_state
    turn_module.save_state = lambda state: None
    try:
        yield
    finally:
        turn_module.save_state = original


@contextmanager
def _counting_extract(counter: dict):
    """替换画像抽取，统计调用次数。"""
    from coach.services import profile as profile_service

    original = profile_service.extract_profile

    def fake(text):
        counter["calls"] += 1
        return UserProfile()

    profile_service.extract_profile = fake
    try:
        yield
    finally:
        profile_service.extract_profile = original


def _state(**extra) -> dict:
    state = json.loads(json.dumps(DEFAULT_STATE))
    state.update(extra)
    return state


def _plan() -> dict:
    return {
        "horizon_days": 1,
        "start_date": "2026-09-22",
        "days": [{"day": 1, "theme": "列表与字典", "tasks": [{"goal": "掌握列表常用操作"}]}],
    }


def _learning_state_with_submission(**extra) -> dict:
    """learning 阶段、已有今日任务、且用户已提交 —— 即缺陷 A 的发生现场。"""
    state = _state(
        learning_goal="Python 数据分析",
        current_level="有一点基础",
        daily_minutes=30,
        target_date="1个月",
        current_stage=STAGE_LEARNING,
        plan_confirmed=True,
        current_plan=_plan(),
        today_task={
            "day": 1, "task": 1, "theme": "列表与字典", "goal": "掌握列表常用操作",
        },
        pending_submission={"content": "print([x for x in range(3)])"},
        plan_progress={"day": 1, "task": 1, "completed": [], "finished": False},
    )
    state.update(extra)
    return state


def _system_messages(messages) -> list[str]:
    return [m["content"] for m in messages if m["role"] == "system"]


# ---------------------------------------------------------------------------
# 缺陷 A：教练不得抢在代码判定之前扮演验收员
# ---------------------------------------------------------------------------

def test_coach_uses_turn_start_stage_not_advanced_stage():
    """状态机本轮推进了，但教练必须仍按**本轮起始阶段**说话。"""
    state = _learning_state_with_submission()
    captured: dict = {}

    with _no_save(), _patched_chat(captured):
        result = run_turn(state, "这是我的提交", use_rag=False)

    assert result.stage_before == STAGE_LEARNING
    assert result.stage_after == STAGE_EVALUATION, "本轮应已推进到验收阶段"

    first_system = captured["messages"][0]["content"]
    assert first_system == STAGE_PROMPTS[STAGE_LEARNING], (
        "教练使用了推进后的阶段提示词 —— 会抢答验收结论"
    )
    assert first_system != STAGE_PROMPTS[STAGE_EVALUATION]


def test_coach_stage_override_changes_injected_context():
    """阶段覆盖必须同时作用于**注入的状态内容**，不能只换提示词。"""
    state = _learning_state_with_submission(
        current_stage=STAGE_EVALUATION,
        latest_result={
            "completion": "completed", "mastery": 1.0, "next_action": "pass",
            "error_types": [], "feedback": "很好", "reason": "达标",
            "topic": "列表与字典", "day": 1, "task": 1,
        },
    )

    as_learning = describe_known_profile(state, stage=STAGE_LEARNING)
    as_evaluation = describe_known_profile(state, stage=STAGE_EVALUATION)

    assert "今日任务" in as_learning, "learning 阶段应注入今日任务"
    assert "本次验收判定" not in as_learning, "learning 阶段不应注入尚未产生的判定"

    assert "本次验收判定" in as_evaluation, "evaluation 阶段应注入真实判定"


def test_learning_stage_injection_forbids_premature_verdict():
    """提交轮（learning）**不得**把提交正文喂给模型，也不得允许它下结论。

    真实运行缺陷 A 的第二次翻车就在这里：即使换了 learning 提示词，注入里写着
    "用户已提交待验收内容：<代码>"，模型照样自己写了"验收结果：通过 ✅"，
    而下一轮代码判的是 partial —— 用户先被告知通过，随后被推翻。
    """
    state = _learning_state_with_submission()
    body = state["pending_submission"]["content"]

    learning_view = describe_known_profile(state, stage=STAGE_LEARNING)
    assert "已收到提交" in learning_view
    assert "通过与否" in learning_view and "不要" in learning_view
    assert body not in learning_view, "learning 轮不得把提交正文交给模型去评判"

    evaluation_view = describe_known_profile(state, stage=STAGE_EVALUATION)
    assert "用户已提交待验收内容" in evaluation_view, "验收阶段才需要看到提交正文"


def test_learning_stage_prompt_forbids_verdict():
    """双重保险：阶段提示词本身也写明不准判定。"""
    prompt = STAGE_PROMPTS[STAGE_LEARNING]
    assert "不要判定通过与否" in prompt
    assert "验收环节给出" in prompt


# ---------------------------------------------------------------------------
# 缺陷 B：权威状态必须压过历史里的自述
# ---------------------------------------------------------------------------

def test_authoritative_state_message_follows_history():
    state = _learning_state_with_submission()
    state["conversation_history"] = [
        {"role": "user", "content": "开始今天的任务吧"},
        {"role": "assistant", "content": "进入第 2 天 · 第 2 个任务：多条件筛选"},
        {"role": "user", "content": "好的"},
        {"role": "assistant", "content": "那我们就做多条件筛选"},
    ]
    captured: dict = {}

    with _no_save(), _patched_chat(captured):
        run_turn(state, "继续", use_rag=False)

    messages = captured["messages"]
    authority_index = next(
        i for i, m in enumerate(messages)
        if m["role"] == "system" and "【当前权威状态】" in m["content"]
    )
    history_indexes = [
        i for i, m in enumerate(messages)
        if m["role"] in ("user", "assistant") and "第 2 天" in m.get("content", "")
    ]

    assert history_indexes, "历史应包含模型自述的旧任务"
    assert authority_index > max(history_indexes), "权威状态必须排在历史之后"
    assert authority_index == len(messages) - 2, "权威状态应紧贴本轮用户输入"


def test_authoritative_prompt_declares_precedence():
    from coach.prompts.tasks import KNOWN_INFO_PROMPT

    assert "优先于" in KNOWN_INFO_PROMPT
    assert "以本节的“今日任务”为准" in KNOWN_INFO_PROMPT or "以本节" in KNOWN_INFO_PROMPT


def test_today_task_injection_forbids_stale_narration():
    text = describe_today_task(_learning_state_with_submission())
    assert "【权威】" in text
    assert "【防冲突】" in text
    assert "不要沿用" in text


# ---------------------------------------------------------------------------
# C：画像齐全后不再每轮空跑抽取
# ---------------------------------------------------------------------------

def test_extract_profile_skipped_when_profile_complete():
    state = _learning_state_with_submission()          # 四项齐全
    counter = {"calls": 0}
    captured: dict = {}

    with _no_save(), _patched_chat(captured), _counting_extract(counter):
        result = run_turn(state, "继续", use_rag=False)

    assert counter["calls"] == 0, "画像齐全时不应再调画像抽取"
    assert result.updated_fields == []


def test_extract_profile_runs_when_profile_incomplete():
    state = _state(learning_goal="Python 数据分析")     # 其余三项缺失
    state["current_stage"] = STAGE_GOAL_CLARIFICATION
    counter = {"calls": 0}
    captured: dict = {}

    with _no_save(), _patched_chat(captured), _counting_extract(counter):
        result = run_turn(state, "我想学 Python", use_rag=False)

    assert counter["calls"] == 1, "画像未齐时必须抽取"
    assert result.updated_fields == []                  # 假抽取返回空画像


# ---------------------------------------------------------------------------
# 极简 runner（共用实现见 tests/_runner.py）
# ---------------------------------------------------------------------------

from _runner import SkipTest, run_tests        # noqa: E402


def main() -> int:
    return run_tests(globals())


if __name__ == "__main__":
    raise SystemExit(main())
