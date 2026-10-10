r"""记忆管理（v0.18）的回归测试。

运行（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\test_memory.py

覆盖四件事：

1. **事实层**：证据必须带来源与时间（**I-12**），空知识点不得写入，错误类型不被覆盖
2. **行为等价**：把"测评覆盖 + 验收平滑"两条就地写入路径改为"证据回放"之后，
   必须得到**同一份画像**（这是本次改造最硬的一条断言）
3. **降采样**：evidence 有条数上界，但截断不得让画像漂移
4. **迁移**：旧状态文件只有 `skill_profile`、没有 evidence —— 必须补种，
   否则用户已有的掌握度会在第一次运行时被抹掉

以及两条配套项：会话时长钳制（15~120）与状态分区视图（**I-8** 的载体）。
"""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.domain.memory import (                                     # noqa: E402
    EVIDENCE_KEEP_PER_TOPIC,
    REVIEW_UNCOVERED_SESSIONS,
    SOURCE_ASSESSMENT,
    SOURCE_EVALUATION,
    SOURCE_MIGRATED,
    SOURCE_SUMMARY,
    append_to_archive,
    archive_message_count,
    archive_segments,
    current_session,
    derive_due_for_review,
    derive_profile,
    evidence_for,
    mark_cycle_condensed,
    new_session,
    pending_cycle_seq,
    prune_archive,
    record_cycle_summary,
    record_evidence,
    select_history,
    session_records,
    session_summaries,
    upsert_session_record,
)
from coach.domain.state_schema import DEFAULT_STATE, ensure_keys         # noqa: E402
from coach.metrics import recorder as metrics                          # noqa: E402

# 本模块不采集指标（避免测试写真实 data/metrics/）
metrics.disable()


def _state(seq: int = 1) -> dict:
    return {"session_seq": seq, "evidence": {}}


# ---------------------------------------------------------------------------
# 1) 事实层：来源、时间、序号、错误类型（I-12 / 忘-5）
# ---------------------------------------------------------------------------

def test_evidence_carries_source_time_and_session():
    """**I-12**：每条证据都必须带 `at`（时间）与 `session_seq`（单次学习序号）。"""
    state = _state(seq=3)
    entry = record_evidence(state, "pandas 分组聚合", source=SOURCE_EVALUATION,
                            verdict="retry", score=0.5,
                            error_type="概念混淆", task_id="2-1")

    assert entry is not None
    for field in ("at", "session_seq", "source", "verdict", "score",
                  "error_type", "task_id"):
        assert field in entry, f"证据缺少字段 {field}"
    assert entry["session_seq"] == 3
    assert entry["source"] == SOURCE_EVALUATION
    assert entry["score"] == 0.5
    assert entry["at"], "时间戳不能为空 —— 没有时间就没有'遗忘'可言"


def test_blank_topic_is_not_recorded():
    """空知识点不得写入（否则会凭空多出一个画像条目）。"""
    state = _state()
    assert record_evidence(state, "   ", source=SOURCE_EVALUATION, score=1.0) is None
    assert record_evidence(state, None, source=SOURCE_EVALUATION, score=1.0) is None
    assert state["evidence"] == {}


def test_error_type_survives_later_attempts():
    """**忘-5**：重做成功之后，上一次的错误类型仍可查到。

    改造前 `latest_result` 是单槽，第二次判定直接把它覆盖了。
    """
    state = _state()
    record_evidence(state, "pandas", source=SOURCE_EVALUATION,
                    verdict="retry", score=0.0, error_type="概念混淆")
    record_evidence(state, "pandas", source=SOURCE_EVALUATION,
                    verdict="pass", score=1.0, error_type="")

    errors = [e["error_type"] for e in evidence_for(state, "pandas")]
    assert "概念混淆" in errors


# ---------------------------------------------------------------------------
# 2) 行为等价：证据回放 == 改造前的两条就地写入路径
# ---------------------------------------------------------------------------

def _legacy_replay(baseline: dict, evaluations) -> dict:
    """改造前的算法（照抄 `evaluation.apply_update` + `assessment_rules.finalize`）。"""
    profile = dict(baseline)                      # 测评：整体覆盖
    for topic, score in evaluations:
        if topic in profile:
            try:
                old = float(profile[topic])
                profile[topic] = round((old + score) / 2, 2)   # 验收：平滑
            except (TypeError, ValueError):
                profile[topic] = round(score, 2)
        else:
            profile[topic] = round(score, 2)
    return profile


def test_derive_profile_matches_legacy_smoothing():
    """**对拍**：测评基准 + 一串验收，回放结果必须与改造前逐字一致。"""
    baseline = {"pandas": 0.5, "numpy": 1.0}
    evaluations = [("pandas", 1.0), ("pandas", 0.0), ("numpy", 0.5), ("pandas", 0.5)]

    state = _state()
    for topic, score in baseline.items():
        record_evidence(state, topic, source=SOURCE_ASSESSMENT,
                        verdict="assessment", score=score)
    for topic, score in evaluations:
        record_evidence(state, topic, source=SOURCE_EVALUATION, score=score)

    assert derive_profile(state) == _legacy_replay(baseline, evaluations)


def test_assessment_then_evaluation_share_one_derivation():
    """走真实代码路径：`finalize` 写基准 → `apply_update` 写平滑，落在同一处派生。"""
    from coach.domain.assessment_rules import finalize
    from coach.services.evaluation import apply_update

    state = {
        "assessment_progress": {
            "records": [
                {"topic": "pandas", "verdict": "partial"},
                {"topic": "numpy", "verdict": "mastered"},
            ],
            "finished": False,
        }
    }
    finalize(state)
    assert state["skill_profile"] == {"pandas": 0.5, "numpy": 1.0}

    state["latest_result"] = {"topic": "pandas", "mastery": 1.0, "next_action": "retry"}
    apply_update(state)
    assert state["skill_profile"]["pandas"] == 0.75        # (0.5 + 1.0) / 2
    assert state["skill_profile"]["numpy"] == 1.0          # 不受影响


def test_weak_points_are_derived_too():
    """薄弱点同样由画像派生（阈值 <0.6 不变）。"""
    state = _state()
    record_evidence(state, "会了", source=SOURCE_EVALUATION, score=1.0)
    record_evidence(state, "不会", source=SOURCE_EVALUATION, score=0.2)
    from coach.domain.memory import derive_weak_points_from_state
    assert derive_weak_points_from_state(state) == ["不会"]


# ---------------------------------------------------------------------------
# 3) 降采样：有上界，但画像不得随截断漂移
# ---------------------------------------------------------------------------

def test_truncation_does_not_drift_profile():
    """evidence 有条数上界；截断必须**降采样成锚点**，否则是静默的画像污染。"""
    def replay(history):
        acc = None
        for source, score in history:
            if source in (SOURCE_ASSESSMENT, SOURCE_MIGRATED, SOURCE_SUMMARY) or acc is None:
                acc = round(score, 2)
            else:
                acc = round((acc + score) / 2, 2)
        return acc

    state = _state()
    record_evidence(state, "t", source=SOURCE_ASSESSMENT, score=1.0)
    history = [(SOURCE_ASSESSMENT, 1.0)]

    for i in range(12):
        score = round(i / 10, 2)
        record_evidence(state, "t", source=SOURCE_EVALUATION, score=score)
        history.append((SOURCE_EVALUATION, score))

    entries = state["evidence"]["t"]
    assert len(entries) <= EVIDENCE_KEEP_PER_TOPIC, "明细没有封顶"
    assert entries[0]["source"] == SOURCE_SUMMARY, "被丢掉的明细没有留下锚点"
    assert derive_profile(state)["t"] == replay(history), "截断让画像漂移了"


# ---------------------------------------------------------------------------
# 4) 迁移：旧状态只有画像、没有证据
# ---------------------------------------------------------------------------

def test_legacy_state_seeds_evidence_and_keeps_profile():
    """旧用户不能被抹掉掌握度：`skill_profile` 必须补种成证据。"""
    state = {"current_stage": "learning", "skill_profile": {"pandas": 0.7, "numpy": 0.4}}

    changed = ensure_keys(state)
    assert any("evidence" in item for item in changed), "没有补种 evidence"
    assert set(state["evidence"]) == {"pandas", "numpy"}
    assert state["evidence"]["pandas"][0]["source"] == SOURCE_MIGRATED,         "补种来源必须如实标记为 migrated，不能伪装成测评"
    assert derive_profile(state) == {"pandas": 0.7, "numpy": 0.4}

    # 幂等：第二次不得重复补种
    assert not any("evidence" in item for item in ensure_keys(state))
    assert len(state["evidence"]["pandas"]) == 1


def test_empty_profile_is_not_seeded():
    """新用户（画像为空）不该被塞进任何证据。"""
    state = {"current_stage": "goal_clarification"}
    ensure_keys(state)
    assert state["evidence"] == {}


# ---------------------------------------------------------------------------
# 5) 待复验（复习调度的最小内核）
# ---------------------------------------------------------------------------

def test_topic_becomes_due_after_n_uncovered_sessions():
    """**连续 N 次单次学习未覆盖** → 待复验；被覆盖的知识点不算。"""
    state = {"session_seq": 0, "evidence": {}}
    new_session(state)
    record_evidence(state, "老知识点", source=SOURCE_EVALUATION, score=1.0)
    record_evidence(state, "新知识点", source=SOURCE_EVALUATION, score=1.0)

    for _ in range(REVIEW_UNCOVERED_SESSIONS):
        new_session(state)
        record_evidence(state, "新知识点", source=SOURCE_EVALUATION, score=1.0)

    assert current_session(state) == REVIEW_UNCOVERED_SESSIONS + 1
    due = derive_due_for_review(state)
    assert "老知识点" in due
    assert "新知识点" not in due


def test_no_due_before_threshold_and_before_any_session():
    state = {"session_seq": 0, "evidence": {}}
    record_evidence(state, "t", source=SOURCE_EVALUATION, score=1.0)
    assert derive_due_for_review(state) == [], "还没开始过任何一次学习，不该有复验项"


# ---------------------------------------------------------------------------
# 6) 单次学习记录（L2 定稿摘要的落点）
# ---------------------------------------------------------------------------

def test_session_record_upsert_is_idempotent():
    """按序号唯一：同一序号重复写入是**更新**，不是追加。"""
    state = {"session_seq": 3, "session_records": []}
    upsert_session_record(state, summary="第一次")
    upsert_session_record(state, summary="第二次", topics=["a"])

    assert len(session_records(state)) == 1
    assert state["session_records"][0]["summary"] == "第二次"
    assert state["session_records"][0]["seq"] == 3


# ---------------------------------------------------------------------------
# 7) 单次学习时长钳制（15 ~ 120 分钟）
# ---------------------------------------------------------------------------

def test_clamp_session_minutes_bounds():
    from coach.domain.profile_rules import (
        SESSION_MINUTES_MAX,
        SESSION_MINUTES_MIN,
        clamp_session_minutes,
        merge_profile,
    )

    assert clamp_session_minutes(30) == 30
    assert clamp_session_minutes(240) == SESSION_MINUTES_MAX, "超过 120 必须被钳制"
    assert clamp_session_minutes(5) == SESSION_MINUTES_MIN, "低于 15 必须被抬到 15"
    assert clamp_session_minutes(None) is None
    assert clamp_session_minutes("") is None
    assert clamp_session_minutes("abc") is None

    state: dict = {}
    updated = merge_profile(state, {"learning_goal": "学 pandas", "session_minutes": 240})
    assert state["session_minutes"] == SESSION_MINUTES_MAX
    assert "session_minutes" in updated


# ---------------------------------------------------------------------------
# 8) 状态分区视图（I-8 的载体）
# ---------------------------------------------------------------------------

def test_zones_cover_every_default_state_key():
    """每个 state 键都必须归区、每个区都必须有保留策略 —— 否则拆文件时必漏。"""
    from coach.domain.zones import RETENTION, ZONES, keys_in, unknown_keys, zone_of

    assert unknown_keys(DEFAULT_STATE.keys()) == (), "有键没有归属"
    for key in DEFAULT_STATE:
        assert zone_of(key) in ZONES, f"{key} 归到了未知的区"
    for zone in ZONES:
        assert zone in RETENTION, f"{zone} 缺少保留策略"
        assert keys_in(zone), f"{zone} 是空区"


def test_zone_view_tolerates_legacy_keys():
    """迁移遗留的旧键（只搬不删）不该被当成"未归区"。"""
    from coach.domain.zones import unknown_keys

    assert unknown_keys(["daily_minutes", "current_plan"]) == ()
    assert unknown_keys(["没听说过的键"]) == ("没听说过的键",)


# ---------------------------------------------------------------------------
# 9) 单次学习的边界：跨天 = 跨次（M1 的最后一环）
# ---------------------------------------------------------------------------

def _window() -> dict:
    """两天的执行窗口，每天 1~2 个任务。"""
    return {
        "length": 2, "unit": "session", "milestone_id": "M1",
        "days": [
            {"theme": "第一天", "tasks": [
                {"goal": "t1", "done_criteria": "c1"},
                {"goal": "t2", "done_criteria": "c2"},
            ]},
            {"theme": "第二天", "tasks": [
                {"goal": "t3", "done_criteria": "c3"},
            ]},
        ],
    }


def test_day_boundary_opens_exactly_one_new_session():
    """**跨天 = 跨一次学习**：`session_seq` 前进一位，同一天重复调用**幂等**。

    没有这一步，`session_seq` 会永远停在 0，待复验（"连续 N 次未覆盖"）就永不触发。
    """
    from coach.domain.cursor import build_today_task, get_progress, mark_task_done

    state = copy.deepcopy(DEFAULT_STATE)
    state["current_stage"] = "learning"
    state["current_window"] = _window()

    assert state["session_seq"] == 0, "还没开始学习，序号应为 0"

    build_today_task(state)
    assert state["session_seq"] == 1, "第一天开课 -> 第 1 次学习"
    assert get_progress(state)["session_day"] == 1

    mark_task_done(state)                       # 完成 1-1，仍在第一天
    assert state["session_seq"] == 1, "同一天内不得重复开新的一次学习"

    mark_task_done(state)                       # 完成 1-2 -> 跨到第二天
    assert state["session_seq"] == 2, "跨天必须开新的一次学习"
    assert get_progress(state)["session_day"] == 2

    build_today_task(state)                     # 第二天取任务，不得再加一次
    assert state["session_seq"] == 2


def test_evidence_records_the_session_it_belongs_to():
    """证据上的 `session_seq` 必须跟着游标走（待复验就靠它算）。"""
    from coach.domain.cursor import build_today_task, mark_task_done

    state = copy.deepcopy(DEFAULT_STATE)
    state["current_stage"] = "learning"
    state["current_window"] = _window()
    build_today_task(state)
    mark_task_done(state)
    mark_task_done(state)                       # 已进入第 2 次学习

    record_evidence(state, "旧知识点", source=SOURCE_EVALUATION, score=1.0)
    assert evidence_for(state, "旧知识点")[0]["session_seq"] == 2


# ---------------------------------------------------------------------------
# 10) 原文层：分段归档 + 丢弃留痕（I-13）
# ---------------------------------------------------------------------------

def test_archive_is_segmented_by_session_and_counts_pruning():
    """归档按**单次学习**分段；丢弃**必须返回条数**（否则没法留痕）。"""
    state = {"session_seq": 1, "conversation_archive": []}
    append_to_archive(state, [{"role": "user", "content": "a"}])
    assert archive_message_count(state) == 1

    new_session(state)                          # 第 2 次学习
    append_to_archive(state, [{"role": "user", "content": "b"},
                              {"role": "assistant", "content": "c"}])
    assert archive_message_count(state) == 3
    assert [seg["session_seq"] for seg in archive_segments(state)] == [1, 2]
    assert len(archive_segments(state)[1]["messages"]) == 2

    for _ in range(3):                          # 再开三次学习
        new_session(state)
        append_to_archive(state, [{"role": "user", "content": "x"}])

    dropped = prune_archive(state, keep=2)
    assert dropped == 4, "被丢弃的条数必须可数（1+2+1）—— 否则没法留痕"
    assert [seg["session_seq"] for seg in archive_segments(state)] == [4, 5]
    assert prune_archive(state, keep=2) == 0, "没得丢时必须返回 0"


def test_flat_archive_is_migrated_to_segments():
    """v0.17 的扁平归档必须升级为分段，否则"保留最近 N 次学习"无从谈起。"""
    from coach.domain.state_schema import upgrade_archive_shape

    flat = {"conversation_archive": [{"role": "user", "content": "old1"},
                                     {"role": "user", "content": "old2"}]}
    assert upgrade_archive_shape(flat) == ["conversation_archive(segmented)"]
    assert flat["conversation_archive"][0]["session_seq"] == 0
    assert len(flat["conversation_archive"][0]["messages"]) == 2
    assert upgrade_archive_shape(flat) == [], "已是分段结构时必须幂等"
    assert upgrade_archive_shape({}) == []
    assert upgrade_archive_shape({"conversation_archive": []}) == []


# ---------------------------------------------------------------------------
# 11) 注入预算：按**字符**而不是条数（§6.1）
# ---------------------------------------------------------------------------

def test_select_history_respects_char_budget():
    history = [{"role": "user", "content": "x" * 100} for _ in range(50)]

    # 预算说了算：500 字符只装得下 5 条约 100 字符的消息
    picked = select_history(history, budget=500, min_messages=1)
    assert len(picked) == 5
    assert sum(len(m["content"]) for m in picked) <= 500

    # 下限说了算：预算再小，最近 6 条也**无论如何都保留**
    # （少于 3 轮对话，模型接不上话 —— 这是有意的取舍，允许略超预算）
    assert len(select_history(history, budget=1, min_messages=6)) == 6
    assert select_history([], budget=100) == []


def test_select_history_keeps_the_most_recent_messages():
    history = [{"role": "user", "content": str(i)} for i in range(10)]
    picked = select_history(history, budget=5, min_messages=1)
    assert picked[-1]["content"] == "9", "必须取**最近**的，而不是最早的"


# ---------------------------------------------------------------------------
# 12) 待复验进入生成计划入参（M4）
# ---------------------------------------------------------------------------

def _with_one_due_topic():
    state = {"session_seq": 0, "evidence": {}}
    new_session(state)
    record_evidence(state, "老知识点", source=SOURCE_EVALUATION, score=1.0)
    record_evidence(state, "新知识点", source=SOURCE_EVALUATION, score=1.0)
    for _ in range(REVIEW_UNCOVERED_SESSIONS):
        new_session(state)
        record_evidence(state, "新知识点", source=SOURCE_EVALUATION, score=1.0)
    return state


def test_review_hint_is_empty_until_something_is_due():
    """没有待复验项时必须返回空串 —— 触发前对行为**零影响**。"""
    from coach.services.planning import review_hint

    assert review_hint({"session_seq": 0, "evidence": {}}) == ""


def test_review_hint_lists_due_topics_only():
    from coach.services.planning import review_hint

    hint = review_hint(_with_one_due_topic())
    assert "老知识点" in hint
    assert "新知识点" not in hint
    assert str(REVIEW_UNCOVERED_SESSIONS) in hint


# ---------------------------------------------------------------------------
# 13) 两级压缩（M8 / M9）—— 叙事可以压，事实不能压（§3 / I-14）
# ---------------------------------------------------------------------------

def _one_recorded_cycle():
    state = copy.deepcopy(DEFAULT_STATE)
    state["session_seq"] = 1
    record_evidence(state, "groupby 聚合", source=SOURCE_EVALUATION,
                    verdict="retry", score=0.5,
                    error_type="概念混淆", task_id="2-1")
    return state


def test_pending_cycle_seq_fires_once_per_boundary():
    """L2 的触发：刚跨过一次边界才定稿，定稿后**幂等**。"""
    state = {"session_seq": 1, "plan_progress": {}}
    assert pending_cycle_seq(state) is None, "当前这一次还在进行中"

    new_session(state)                              # 跨到第 2 次 -> 第 1 次结束
    assert pending_cycle_seq(state) == 1

    mark_cycle_condensed(state, 1)
    assert pending_cycle_seq(state) is None, "定稿之后不得重复触发"

    new_session(state)
    assert pending_cycle_seq(state) == 2


def test_pending_cycle_seq_is_not_confused_by_window_rolls():
    """定稿标记用**全局序号**而不是 `day` —— 计划块滚动会把 day 重置。"""
    state = {"session_seq": 5, "plan_progress": {"day": 1}, "condensed_through_seq": 4}
    assert pending_cycle_seq(state) is None

    new_session(state)                              # 新计划块的第 1 天
    assert state["session_seq"] == 6
    assert pending_cycle_seq(state) == 5, "跨计划块也必须正确"


def test_session_summaries_are_bounded():
    from coach.domain.memory import SESSION_SUMMARIES_KEEP

    state = {"session_summaries": []}
    for seq in range(1, SESSION_SUMMARIES_KEEP + 6):
        record_cycle_summary(state, seq, f"第 {seq} 次学习")

    assert len(session_summaries(state)) == SESSION_SUMMARIES_KEEP
    assert state["session_summaries"][-1]["seq"] == SESSION_SUMMARIES_KEEP + 5


def test_condense_capabilities_never_write_judgement_fields():
    """**I-14**：叙事层（压缩）不得写任何判定字段。

    真正的一条红线是画像与验收结论。
    """
    from coach.domain.capabilities import REGISTRY_BY_NAME

    forbidden = {"skill_profile", "weak_points", "latest_result",
                 "latest_result_applied", "assessment_progress"}
    for name in ("memory.condense_progress", "memory.condense_cycle"):
        cap = REGISTRY_BY_NAME[name]
        overlap = set(cap.writes) & forbidden
        assert not overlap, f"{name} 会写判定字段 {sorted(overlap)}，违反 I-14"


def test_summarize_cycle_puts_the_deterministic_skeleton_first():
    """**I-14 的结构保障**：摘要 = 骨架在前 + 模型润色在后。

    知识点名与验收动作永远来自代码，模型替换不了事实、也引入不了新知识点。
    """
    from coach.llm import client as llm_client
    from coach.services import memory as memory_service

    state = _one_recorded_cycle()
    original = llm_client.json_call
    llm_client.json_call = lambda *a, **kw: {"summary": "用户练了分组聚合，卡在多列取值。"}
    try:
        text = memory_service.summarize_cycle(state, 1)
    finally:
        llm_client.json_call = original

    assert text.startswith("[单次学习 1]"), "骨架必须在前 —— 它才是事实来源"
    assert "groupby 聚合" in text.split("【补充】")[0], "知识点名必须来自代码"
    assert "【补充】" in text and "卡在多列取值" in text


def test_summarize_cycle_falls_back_when_the_model_fails():
    """**§6.4**：模型失败必须退化为**确定性摘要** —— 绝不留空、绝不抛出。"""
    from coach.llm import client as llm_client
    from coach.services import memory as memory_service

    state = _one_recorded_cycle()
    original = llm_client.json_call

    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    llm_client.json_call = boom
    try:
        text = memory_service.summarize_cycle(state, 1)
    finally:
        llm_client.json_call = original

    assert text.strip(), "兜底摘要不能是空的 —— 记忆不能空着"
    assert "groupby 聚合" in text
    assert "【补充】" not in text


def test_summarize_progress_keeps_the_previous_summary_on_failure():
    """L1 失败时优先保留**已有的**滚动摘要（它至少是上一轮的结论）。"""
    from coach.llm import client as llm_client
    from coach.services import memory as memory_service

    state = _one_recorded_cycle()
    original = llm_client.json_call
    llm_client.json_call = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        text = memory_service.summarize_progress(
            state, [{"role": "user", "content": "我们先看看数据"}], "此前的进展")
    finally:
        llm_client.json_call = original

    assert text == "此前的进展"


def test_memory_is_injected_before_the_authoritative_state():
    """叙事层要进注入，且**权威状态仍在最后**（I-3 不变，§6.1 的 ② 与 ④）。"""
    from coach.llm import client as llm_client
    from coach.services.coach import chat_with_coach

    state = copy.deepcopy(DEFAULT_STATE)
    state["learning_goal"] = "用 pandas 做销售分析"
    state["rolling_summary"] = "本次学习进行到一半。"
    record_cycle_summary(state, 1, "第一次学习：读了 CSV。", ["pandas"])

    captured = {}
    original = llm_client.chat

    def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        return "ok"

    llm_client.chat = fake_chat
    try:
        chat_with_coach("继续", history=[], state=state, stage="learning")
    finally:
        llm_client.chat = original

    contents = [m["content"] for m in captured["messages"]]
    idx_rolling = next(i for i, c in enumerate(contents) if "本次学习进行到一半。" in c)
    idx_history = next(i for i, c in enumerate(contents) if "第一次学习：读了 CSV。" in c)
    # 注意：用"【当前权威状态】\n"而不是裸的四个字 ——
    # 记忆提示词正文里也提到了"【当前权威状态】"（那是它引用它，不是它本身）。
    idx_known = next(i for i, c in enumerate(contents) if "【当前权威状态】\n" in c)

    assert idx_rolling < idx_known, "记忆摘要必须排在权威状态之前"
    assert idx_history < idx_known
    assert captured["messages"][-1]["content"] == "继续", "用户输入必须在最后"


# ---------------------------------------------------------------------------
# 极简 runner（共用实现见 tests/_runner.py）
# ---------------------------------------------------------------------------

from _runner import SkipTest, run_tests        # noqa: E402,F401


def main() -> int:
    return run_tests(globals())


if __name__ == "__main__":
    raise SystemExit(main())
