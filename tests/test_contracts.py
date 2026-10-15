r"""状态读写的**契约测试**（`docs/architecture.md` 附录 A.2 的 **F7**）。

运行（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\test_contracts.py

解决什么问题
------------
`Capability.reads` / `writes` 一直**只是文档**。architecture.md 附录 A.3 曾列出
**8 处欠声明**（声明少于实现实际改动的键）—— 它们能长期存在，正是因为
"声明"与"实现"之间**没有任何强制力**。v0.18 的契约测试要把这条规则变成可执行的。

    对每个已启用的能力，用**运行时探针**跑一遍它的 handler，
    断言「它真的写过的键 ⊆ 它声明的 writes」。

为什么只做 `writes`、不做 `reads`
--------------------------------
读没有风险面：任何防御性的 `state.get("x")` 都会算成一次"读"，噪声大到无法维护。
**写**才会污染状态，所以它值得一条契约；`reads` 暂时只作为给人看的文档
（但它也有防错别字的断言，见最后一条用例）。

探针的粒度
----------
`_TrackedDict` 只记**顶层键**。嵌套键不在其列，但所有代码路径最终都会把整个嵌套
结构赋回顶层（如 `state["plan_progress"] = progress`），所以顶层粒度足以覆盖真实风险。

缺 fixture 会直接失败
--------------------
加能力就必须同时给出**可驱动的上下文**。静默跳过会让这条契约退化成文档 ——
那正是它要防的事。
"""

import copy
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.domain.capabilities import REGISTRY                          # noqa: E402
from coach.domain.memory import (                                       # noqa: E402
    SOURCE_EVALUATION,
    new_session,
    record_evidence,
)
from coach.domain.state_schema import DEFAULT_STATE                     # noqa: E402
from coach.llm import client as llm_client                              # noqa: E402
from coach.metrics import recorder as metrics                          # noqa: E402
from coach.orchestration.executor import HANDLERS, TurnContext           # noqa: E402

metrics.disable()          # 契约测试不写真实 metrics

#: **骨架推进点**写的键。它不属于任何能力 —— 推进是状态机契约（**I-1**）的载体，
#: 由 `executor._advance` 负责，所以任何 handler 都可能"顺带"写它。
SKELETON_WRITES = frozenset({"current_stage"})


# ---------------------------------------------------------------------------
# 探针：记录顶层键的写入
# ---------------------------------------------------------------------------

class _TrackedDict(dict):
    """一个 dict，额外记录**被写入**的顶层键。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.written = set()

    def __setitem__(self, key, value):
        self.written.add(key)
        return super().__setitem__(key, value)

    def __delitem__(self, key):
        self.written.add(key)
        return super().__delitem__(key)

    def update(self, *args, **kwargs):
        for source in args:
            if hasattr(source, "keys"):
                self.written.update(source.keys())
        self.written.update(kwargs.keys())
        return super().update(*args, **kwargs)

    def setdefault(self, key, default=None):
        self.written.add(key)
        return super().setdefault(key, default)

    def pop(self, *args, **kwargs):
        if args:
            self.written.add(args[0])
        return super().pop(*args, **kwargs)


def trace_writes(cap_name: str, state: dict, user_input: str = "") -> set:
    """跑一遍该能力的 handler，返回它**真的写过**的顶层键。"""
    tracked = _TrackedDict(copy.deepcopy(state))
    ctx = TurnContext(state=tracked, user_input=user_input)
    HANDLERS[cap_name](ctx)
    return tracked.written


# ---------------------------------------------------------------------------
# 隔离：绝不联网、绝不写真实状态文件
# ---------------------------------------------------------------------------

@contextmanager
def _no_save():
    """`memory.commit_history` 会落盘 —— 测试绝不能写真实的 user_state.json。"""
    from coach.orchestration import executor as executor_module

    original = executor_module.save_state
    executor_module.save_state = lambda state: None
    try:
        yield
    finally:
        executor_module.save_state = original


@contextmanager
def _stub_model():
    """打桩两个模型出口：返回**类型正确的最小超集**。

    Pydantic v2 默认忽略未知字段（extra="ignore"），所以一份超集能同时喂饱
    画像抽取 / 计划确认 / 提交判定 / 验收判定 / 出题 / 摘要压缩 ——
    不需要为每个能力写一份精确的桩，也就不会因为桩写错而让契约"假通过"。
    """
    original_json = llm_client.json_call
    original_chat = llm_client.chat

    def fake_json_call(system_prompt, user_content, settings=None, *, label=None):
        return {
            "learning_goal": "用 pandas 做销售分析",
            "current_level": "会一点 Python",
            "session_minutes": 30,
            "target_date": "2026-11-01",
            "confirmed": True, "reason": "明确同意",
            "is_submission": True, "content": "代码与运行结果",
            "completion": "completed", "error_types": ["边界情况遗漏"],
            "next_action": "pass", "mastery": 1.0, "feedback": "好的",
            "questions": [{"topic": "groupby", "difficulty": 1}],
            "verdict": "mastered",
            "summary": "（模型润色的一句话）",
        }

    llm_client.json_call = fake_json_call
    llm_client.chat = lambda messages, **kwargs: "（教练回复）"
    try:
        yield
    finally:
        llm_client.json_call = original_json
        llm_client.chat = original_chat


# ---------------------------------------------------------------------------
# Fixtures：每个已启用能力一份可驱动的上下文
# ---------------------------------------------------------------------------

def _window() -> dict:
    return {"length": 2, "unit": "session", "milestone_id": "M1",
            "days": [
                {"theme": "D1", "tasks": [
                    {"goal": "t1", "exercise": "e", "minutes": 20, "done_criteria": "c"},
                    {"goal": "t2", "exercise": "e", "minutes": 20, "done_criteria": "c"},
                ]},
                {"theme": "D2", "tasks": [
                    {"goal": "t3", "exercise": "e", "minutes": 30, "done_criteria": "c"},
                ]},
            ]}


def _task() -> dict:
    return {"day": 1, "task": 1, "theme": "D1", "goal": "读 CSV",
            "material": "文档", "exercise": "打印前 5 行", "minutes": 20,
            "done_criteria": "能打印出前 5 行"}


def _ready(**overrides) -> dict:
    state = copy.deepcopy(DEFAULT_STATE)
    state.update({
        "learning_goal": "用 pandas 做销售分析",
        "current_level": "会一点 Python",
        "session_minutes": 30,
        "target_date": "2026-11-01",
        "sessions_per_week": 3,
        "current_stage": "learning",
        "plan_confirmed": True,
        "roadmap": {"current_milestone": "M1",
                    "milestones": [{"id": "M1", "title": "基础", "topics": ["pandas"],
                                    "sessions_est": 3, "status": "active"}]},
        "current_window": _window(),
    })
    state.update(overrides)
    return state


def _assessment(records) -> dict:
    return {"plan": [{"index": 1, "topic": "groupby", "difficulty": 1}],
            "records": records, "finished": False}


def _condense_cycle_state() -> dict:
    """L2 的触发态：**已经跨到第 2 次学习**、且第 1 次还没定稿。"""
    state = _ready(session_seq=1)
    record_evidence(state, "groupby", source=SOURCE_EVALUATION,
                    verdict="retry", score=0.5, task_id="1-1")
    new_session(state)
    return state


def _long_history_state() -> dict:
    """L1 的触发态：注入装不下的原文攒够了门槛。"""
    return _ready(session_seq=1,
                  conversation_history=[{"role": "user", "content": "x" * 400}
                                        for _ in range(40)])


#: 能力 → (state, user_input)。**每个已启用能力都必须在这里。**
FIXTURES = {
    "perception.profile_extract":
        (copy.deepcopy(DEFAULT_STATE), "我想学 pandas 做销售分析"),
    "perception.plan_confirm":
        (_ready(plan_confirmed=False), "可以，就这样"),
    "planning.plan_generate":
        (_ready(roadmap=None, current_window=None), "开始吧"),
    "perception.submission_detect":
        (_ready(today_task=_task()), "我提交了：打印前 5 行"),
    "planning.daily_task_build":
        (_ready(), "继续"),
    "evaluation.judge":
        (_ready(today_task=_task(), pending_submission={"content": "代码"}), "看看"),
    "planning.assessment_outline":
        (_ready(current_stage="assessment"), "开始测评"),
    "dialogue.coach_reply":
        (_ready(), "你好"),
    "perception.assessment_verdict":
        (_ready(current_stage="assessment", assessment_progress=_assessment([])), "我的答案是……"),
    "memory.assessment_finalize":
        (_ready(current_stage="assessment",
                assessment_progress=_assessment([{"topic": "groupby", "verdict": "mastered"}])), ""),
    "memory.profile_apply":
        (_ready(latest_result={"topic": "groupby", "mastery": 1.0,
                               "next_action": "pass", "day": 1, "task": 1}), ""),
    "planning.window_finish_check":
        (_ready(), ""),
    "planning.window_roll":
        (_ready(plan_progress={"day": 2, "task": 1, "completed": ["1-1", "1-2", "2-1"],
                               "finished": True, "attempts": 2, "session_day": 2}), ""),
    "memory.condense_progress":
        (_long_history_state(), ""),
    "memory.condense_cycle":
        (_condense_cycle_state(), ""),
    "memory.commit_history":
        (_ready(), "你好"),
}


# ---------------------------------------------------------------------------
# 1) 契约本体
# ---------------------------------------------------------------------------

def test_handlers_only_write_what_they_declare():
    """**F7 / 声明即契约**：handler 真的写过的键 ⊆ 它声明的 `writes`。

    这条用例就是 architecture.md A.3 那 8 处欠声明的解药。
    """
    problems = []
    with _no_save(), _stub_model():
        for cap in REGISTRY:
            if not cap.enabled:
                continue
            if cap.name not in FIXTURES:
                problems.append(f"{cap.name}: 缺少 fixture")
                continue
            state, user_input = FIXTURES[cap.name]
            written = trace_writes(cap.name, state, user_input)
            extra = written - (set(cap.writes) | SKELETON_WRITES)
            if extra:
                problems.append(
                    f"{cap.name}: 写了**未声明**的键 {sorted(extra)}"
                    f"（已声明 {sorted(cap.writes)}）"
                )

    assert problems == [], (
        "writes 契约被破坏（声明必须与实现一致）：\n  - " + "\n  - ".join(problems)
    )


def test_every_enabled_capability_has_a_fixture():
    """缺 fixture = 契约对它**形同虚设** —— 故意让它失败，而不是静默跳过。"""
    missing = sorted(c.name for c in REGISTRY if c.enabled and c.name not in FIXTURES)
    assert missing == [], "以下能力没有 fixture：\n  - " + "\n  - ".join(missing)


def test_fixtures_have_no_stale_capabilities():
    """反向：fixture 表里不能留下已删除的能力（否则表会腐烂）。"""
    known = {c.name for c in REGISTRY}
    stale = sorted(set(FIXTURES) - known)
    assert stale == [], f"fixture 表里有不存在的能力：{stale}"


def test_declared_keys_exist_in_the_state_schema():
    """`reads` / `writes` 里声明的键必须真的存在（防错别字 —— 它们全是字符串）。"""
    from coach.domain.zones import LEGACY_TOLERATED, ZONE_OF

    known = set(DEFAULT_STATE) | set(LEGACY_TOLERATED) | set(ZONE_OF)
    bad = []
    for cap in REGISTRY:
        if not cap.enabled:
            continue
        for key in cap.writes:
            if key not in known:
                bad.append(f"{cap.name}.writes 含未知键 {key!r}")
        for key in cap.reads:
            if key != "*" and key not in known:
                bad.append(f"{cap.name}.reads 含未知键 {key!r}")
    assert bad == [], "\n  - " + "\n  - ".join(bad)


# ---------------------------------------------------------------------------
# 2) 探针自身的用例（否则探针悄悄失效，契约就成了摆设）
# ---------------------------------------------------------------------------

def test_tracker_records_all_mutation_shapes():
    tracked = _TrackedDict({"a": 1, "b": 2})
    tracked["c"] = 3
    tracked.update({"d": 4})
    tracked.setdefault("e", 5)
    tracked.pop("a")
    del tracked["b"]
    assert tracked.written == {"c", "d", "e", "a", "b"}


def test_tracker_does_not_count_reads():
    """读不算写 —— 否则每条 `state.get(...)` 都会污染契约。"""
    tracked = _TrackedDict({"a": 1})
    _ = tracked["a"]
    _ = tracked.get("a")
    _ = "a" in tracked
    assert tracked.written == set()


# ---------------------------------------------------------------------------
# 极简 runner（共用实现见 tests/_runner.py）
# ---------------------------------------------------------------------------

from _runner import SkipTest, run_tests        # noqa: E402,F401


def main() -> int:
    return run_tests(globals())


if __name__ == "__main__":
    raise SystemExit(main())
