r"""单轮因果链（**F5**）的回归测试。

运行（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\test_trace.py

覆盖三件事：

1. **因果链够不够排查** —— 走真实 `run_turn`（打桩模型），断言一轮里
   "跑了哪些能力 / 跳过了哪些 / 各自改了什么 / 调了几次模型 / 回复是什么"都在。
   这正`X-16` 排查时缺的那份证据。
2. **采集是 fail-safe 的** —— 写盘失败绝不能影响主流程（与 metrics 同一纪律）。
3. **有上界** —— 字段截断 + 文件轮转**留痕**（I-13 的同一纪律）。
"""

import copy
import json
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.domain.state_schema import DEFAULT_STATE                     # noqa: E402
from coach.llm import client as llm_client                              # noqa: E402
from coach.metrics import recorder as metrics                          # noqa: E402
from coach.observability import trace                                   # noqa: E402
from coach.orchestration.turn import run_turn                           # noqa: E402

metrics.disable()                       # 本文件不写真实 data/metrics/

TMP_ROOT = Path(__file__).resolve().parent / ".tmp" / "traces"


def _fresh_path(name: str) -> Path:
    """一个干净的临时 trace 文件路径。"""
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TMP_ROOT / name
    if path.exists():
        path.unlink()
    return path


@contextmanager
def _no_save():
    """测试绝不能写真实的 data/user_state.json。"""
    from coach.orchestration import executor as executor_module

    original = executor_module.save_state
    executor_module.save_state = lambda state: None
    try:
        yield
    finally:
        executor_module.save_state = original


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeUsage:
    prompt_tokens = 12
    completion_tokens = 6


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()


class _FakeCompletions:
    """假客户端：按 `response_format` 区分 json_call / chat，按提示词内容分派结果。"""

    def create(self, **kwargs):
        system = ""
        for message in kwargs.get("messages") or []:
            if message.get("role") == "system":
                system = message.get("content") or ""
                break
        if "response_format" not in kwargs:
            return _FakeResponse("（教练回复）")            # `chat()`
        if "提交" in system:
            body = {"is_submission": True, "content": "代码与运行结果", "reason": "有产出"}
        elif "验收员" in system:
            body = {"completion": "completed", "error_types": [], "next_action": "pass",
                    "mastery": 1.0, "feedback": "好", "reason": "符合标准"}
        else:
            body = {}
        return _FakeResponse(json.dumps(body, ensure_ascii=False))


class _FakeClient:
    chat = type("_Chat", (), {"completions": _FakeCompletions()})()


@contextmanager
def _stub_model():
    """打桩**底层客户端**（不是 `json_call`）。

    这一点很关键：换掉 `json_call` 会把真实的实现（含 `_record_llm_call`）一起换掉，
    于是 trace 里**永远没有模型调用** —— 测试会假通过。
    换底层客户端才能让真实路径跑起来，把调用记进因果链。
    """
    original = llm_client.get_client
    llm_client.get_client = lambda settings=None: _FakeClient()
    try:
        yield
    finally:
        llm_client.get_client = original


def _learning_state() -> dict:
    """**已经下发过任务**的学习阶段 —— 于是本轮"提交判定"会真的跑。"""
    state = copy.deepcopy(DEFAULT_STATE)      # 必须深拷贝：浅拷贝会让多个用例共享同一份可变默认值
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


# ---------------------------------------------------------------------------
# 1) 因果链够不够排查
# ---------------------------------------------------------------------------

def test_turn_trace_captures_the_causal_chain():
    """一轮 trace 必须回答：跑了什么、跳了什么、改了什么、调了几次、回了什么。"""
    path = _fresh_path("turn.jsonl")
    trace.configure(path=path, enabled=True)
    try:
        state = _learning_state()
        with _no_save(), _stub_model():
            run_turn(state, "我提交了：代码与运行结果")
    finally:
        trace.configure(enabled=False)

    records = [json.loads(line) for line in
               path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(records) == 1, "一轮应当只落一条 trace"
    rec = records[0]

    # 信封
    assert rec["turn"] == 1
    assert rec["session_id"], "必须带 session_id，才能和指标文件对上"
    assert rec["stage_before"] == "learning"
    assert rec["stage_after"] == "evaluation"
    assert rec["user_input"].startswith("我提交了")
    assert rec["answer"] == "（教练回复）"
    assert rec["elapsed_ms"] >= 0

    steps = {s["capability"]: s for s in rec["steps"]}

    # 跑了的步骤：带了**改过哪些 state 键**
    assert steps["perception.submission_detect"]["status"] == "ran"
    assert "pending_submission" in steps["perception.submission_detect"]["changed"]
    assert "conversation_history" in steps["memory.commit_history"]["changed"]

    # 跳过的步骤：要能看出"被前置条件挡住"（这正是 X-16 类问题的关键证据）
    assert steps["perception.profile_extract"]["status"] == "skipped"
    assert steps["perception.profile_extract"]["reason"] == "precondition"
    assert steps["planning.daily_task_build"]["status"] == "skipped"

    # 只读能力不该报出任何 state 变化
    assert steps["dialogue.coach_reply"]["status"] == "ran"
    assert "changed" not in steps["dialogue.coach_reply"]

    # 模型调用挂在**这一轮**上
    assert rec["llm_calls"], "这一轮至少调过一次模型 —— 空列表会让下面的断言假通过"
    labels = [call["label"] for call in rec["llm_calls"]]
    assert "submission_detect" in labels
    assert all(call["ok"] for call in rec["llm_calls"])

    # 阶段推进也被记下来了
    assert rec["transitions"] == [["learning", "evaluation"]]


class _BoomCompletions:
    def create(self, **kwargs):
        raise RuntimeError("network down")


class _BoomChat:
    completions = _BoomCompletions()


class _BoomClient:
    chat = _BoomChat()


def test_llm_failures_are_recorded_with_their_error():
    """模型调用失败必须留在因果链里 —— 否则"为什么这轮没进展"无从判断。"""
    path = _fresh_path("fail.jsonl")
    trace.configure(path=path, enabled=True)
    original_client = llm_client.get_client
    # 换掉底层客户端（而不是 json_call）：这样能绕开"缺 Key 在计时开始前就抛"的分支，
    # 真正走到 `_create` 的异常处理 —— 那才是要被记录的那条路径。
    llm_client.get_client = lambda settings=None: _BoomClient()
    try:
        trace.start(user_input="x", stage_before="learning")
        try:
            llm_client.json_call("提交", "x", label="submission_detect")
        except RuntimeError:
            pass
        trace.finish(answer="", stage_after="learning")
    finally:
        llm_client.get_client = original_client
        trace.configure(enabled=False)

    rec = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert rec["llm_calls"][-1]["ok"] is False
    assert rec["llm_calls"][-1]["label"] == "submission_detect"
    assert rec["llm_calls"][-1]["error"] == "error:RuntimeError"


# ---------------------------------------------------------------------------
# 2) fail-safe 与上界
# ---------------------------------------------------------------------------

def test_disabled_recorder_writes_nothing():
    path = _fresh_path("disabled.jsonl")
    trace.configure(path=path, enabled=False)

    payload = trace.start(user_input="x", stage_before="learning")
    returned = trace.finish(answer="y", stage_after="learning")

    assert payload is not None, "即使不落盘，trace 对象也必须可用"
    assert returned is not None
    assert not path.exists(), "关闭时绝不能写盘"


def test_write_failure_is_swallowed():
    """写盘失败只累加错误计数，**绝不抛** —— 采集不能掀掉主流程。"""
    bad = TMP_ROOT / "as_dir.jsonl"
    bad.mkdir(parents=True, exist_ok=True)          # 把"文件"指到一个目录上
    recorder = trace.TraceRecorder(path=bad, enabled=True)

    assert recorder.record({"x": 1}) is not None
    assert recorder.write_errors == 1
    assert recorder.turns == 0, "没写成功就不该计数"


def test_brief_truncates_and_never_raises():
    assert trace.brief("abc") == "abc"
    assert trace.brief("x" * 10, limit=4) == "xxxx…"
    assert trace.brief({"a": 1}) == '{"a": 1}'
    assert isinstance(trace.brief(object()), str), "不可序列化的值也不能抛"


def test_rotation_keeps_one_generation_and_leaves_a_mark():
    """超过上限就轮转一代，并在新文件开头**留痕** —— 不静默丢（I-13 同一纪律）。"""
    path = _fresh_path("rotate.jsonl")
    path.write_text("x" * (trace.MAX_BYTES + 10), encoding="utf-8")
    recorder = trace.TraceRecorder(path=path, enabled=True)

    recorder.record({"hello": "world"})

    backup = path.with_name(path.name + ".1")
    assert backup.exists(), "旧文件必须留一代"
    first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert first["event"] == "rotated"
    assert "已轮转" in first["note"]
    assert recorder.turns == 1
    backup.unlink()


# ---------------------------------------------------------------------------
# 极简 runner（共用实现见 tests/_runner.py）
# ---------------------------------------------------------------------------

from _runner import SkipTest, run_tests        # noqa: E402,F401


def main() -> int:
    return run_tests(globals())


if __name__ == "__main__":
    raise SystemExit(main())
