r"""感知契约（**F1**）的回归测试。

运行（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\test_perception.py

把 `docs/architecture.md` §7 的四条不变量变成可执行断言：

- **P-1** `ok=False` 时不得把 payload 当判定结果用（不得写判定性字段）
- **P-2** payload 必须经 Pydantic 校验（`validated()`）
- **P-3** `raw` 只进日志/trace，不进 state
- **P-4** 判定失败保持当前阶段、不推进
"""

import copy
import json
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.domain.models import UserProfile                                 # noqa: E402
from coach.domain.perception import (                                       # noqa: E402
    KIND_EVALUATION_VERDICT,
    KIND_PROFILE,
    PERCEPTION_KINDS,
    PerceptionResult,
)
from coach.domain.state_schema import DEFAULT_STATE                          # noqa: E402
from coach.llm import client as llm_client                                   # noqa: E402
from coach.metrics import recorder as metrics                               # noqa: E402
from coach.orchestration.turn import run_turn                                # noqa: E402

metrics.disable()


# ---------------------------------------------------------------------------
# 契约本身
# ---------------------------------------------------------------------------

def test_kinds_are_registered_and_unique():
    """每个判定点都要登记 kind —— 新增判定点却忘了登记，这条会失败。"""
    assert len(PERCEPTION_KINDS) == len(set(PERCEPTION_KINDS))
    assert "profile" in PERCEPTION_KINDS
    assert "evaluation_verdict" in PERCEPTION_KINDS


def test_success_and_failure_shapes():
    ok = PerceptionResult.success("profile", {"learning_goal": "x"})
    assert ok.ok is True and ok.payload["learning_goal"] == "x"
    assert ok.error == "" and ok.needs_confirm is False

    bad = PerceptionResult.failure("profile", error="boom")
    assert bad.ok is False and bad.error == "boom" and bad.payload == {}


def test_truthiness_follows_ok():
    """`if result:` 必须等价于 `if result.ok:`。

    PerceptionResult 永远是非空对象；若沿用默认真值语义，
    `if result:` 会在**失败时也成立** —— 那正是 P-1 要防的误用。
    """
    assert bool(PerceptionResult.success("profile")) is True
    assert bool(PerceptionResult.failure("profile", error="x")) is False


def test_validated_requires_a_pydantic_model():
    """**P-2**：payload 必须经校验；普通 dict 不许走 `validated()`。"""
    result = PerceptionResult.validated(KIND_PROFILE, UserProfile(learning_goal="x"))
    assert result.ok and result.payload["learning_goal"] == "x"

    try:
        PerceptionResult.validated(KIND_PROFILE, {"learning_goal": "x"})
    except TypeError:
        pass
    else:
        raise AssertionError("普通 dict 不该被当成『已校验』")


# ---------------------------------------------------------------------------
# 跨层：四条不变量走真实 run_turn
# ---------------------------------------------------------------------------

class _BoomCompletions:
    def create(self, **kwargs):
        raise RuntimeError("network down")


class _BoomClient:
    chat = type("_Chat", (), {"completions": _BoomCompletions()})()


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
def _failing_model():
    """打桩**底层客户端**让每次调用都失败 —— 于是每个判定点都走兜底分支。"""
    original = llm_client.get_client
    llm_client.get_client = lambda settings=None: _BoomClient()
    try:
        yield
    finally:
        llm_client.get_client = original


def _learning_state() -> dict:
    state = copy.deepcopy(DEFAULT_STATE)
    state.update({
        "learning_goal": "用 pandas 做销售分析",
        "current_level": "会一点 Python",
        "session_minutes": 30,
        "target_date": "2026-11-01",
        "current_stage": "learning",
        "plan_confirmed": True,
        "today_task": {"day": 1, "task": 1, "theme": "D1", "goal": "读 CSV",
                       "exercise": "打印前 5 行", "minutes": 20,
                       "done_criteria": "能打印出前 5 行"},
        "current_window": {"length": 1, "unit": "session", "milestone_id": "M1",
                           "days": [{"theme": "D1", "tasks": [
                               {"goal": "读 CSV", "exercise": "e", "minutes": 20,
                                "done_criteria": "c"}]}]},
    })
    return state


def test_failed_judgement_keeps_stage_and_writes_nothing():
    """**P-1 + P-4**：提交判定失败时，**不写 pending_submission、不推进阶段**。"""
    state = _learning_state()

    with _no_save(), _failing_model():
        result = run_turn(state, "我提交了：代码在附件里")

    assert state["pending_submission"] is None, "P-1：失败不得写判定性字段"
    assert state["current_stage"] == "learning", "P-4：失败不得推进阶段"
    assert result.transitions == [], "没有推进"


def test_failed_judgement_is_visible_on_the_turn_result():
    """**F1 的可见性**：判定失败必须出现在 `perception_errors` 上。

    改造前这类失败**完全不可见** —— 返回值与"正常但为空"无法区分。
    """
    state = _learning_state()

    with _no_save(), _failing_model():
        result = run_turn(state, "我提交了：代码在附件里")

    kinds = [item.split(":")[0] for item in result.perception_errors]
    assert "submission" in kinds, f"降级没被记录：{result.perception_errors}"
    assert all("network down" in item for item in result.perception_errors)


def test_raw_and_result_objects_never_enter_state():
    """**P-3**：trace/日志用的东西与判定对象本身，都不许进 state。"""
    state = _learning_state()

    with _no_save(), _failing_model():
        run_turn(state, "我提交了：代码在附件里")

    for key, value in state.items():
        assert not isinstance(value, PerceptionResult), f"{key} 里混进了判定对象（P-3）"

    # 而且整个 state 必须仍然可 JSON 序列化（撞上不可序列化对象就说明混进了对象）
    json.dumps(state, ensure_ascii=False, default=str)


def test_evaluation_failure_does_not_write_latest_result():
    """**P-1**：验收判定失败时 `latest_result` 必须保持 None（不写假判定）。"""
    state = _learning_state()
    state["current_stage"] = "evaluation"
    state["pending_submission"] = {"content": "我的代码", "day": 1, "task": 1}

    with _no_save(), _failing_model():
        result = run_turn(state, "看看我的提交")

    assert state["latest_result"] is None
    assert state["latest_result_applied"] is False
    assert state["current_stage"] == "evaluation", "P-4：保持 evaluation"
    assert KIND_EVALUATION_VERDICT + ":RuntimeError: network down" in result.perception_errors


# ---------------------------------------------------------------------------
# 极简 runner（共用实现见 tests/_runner.py）
# ---------------------------------------------------------------------------

from _runner import SkipTest, run_tests        # noqa: E402,F401


def main() -> int:
    return run_tests(globals())


if __name__ == "__main__":
    raise SystemExit(main())
