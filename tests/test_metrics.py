r"""S-07 事件级指标采集与导出（PRD §3.5 日志与审计 / §3.1 M-03、M-04 / §8 护栏）。

运行（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\test_metrics.py

覆盖：
- 事件 schema 含 PRD §3.5 规定的全部字段
- 默认**关闭**（库导入不产生副作用）；显式 enable 后才写 JSONL
- **采集 fail-safe**：路径不可写时只累加错误计数，绝不抛异常
- LLM 调用计数、阶段上下文归属
- 成本：**未配置单价返回 None**（不编造价格）；配置后按每百万 token 正确折算
- 汇总：token 合计、p50/p95 延迟、**每轮 LLM 调用次数**、结果/判定/确认门分布
- 损坏行容错；CSV / JSONL 导出与 CLI 入口

不依赖 API Key，全部为确定性用例。
"""

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.config import Settings
from coach.metrics import recorder as metrics
from coach.metrics.export import export_events, main as export_main
from coach.metrics.recorder import (
    EVENT_CONFIRMATION,
    EVENT_LLM_CALL,
    EVENT_TURN,
    REQUIRED_FIELDS,
    SCHEMA_FIELDS,
    MetricsRecorder,
    estimate_cost,
    make_event,
)
from coach.metrics.summary import load_events, render_summary, summarize

TMP_ROOT = Path(__file__).resolve().parent / ".tmp" / "metrics"


def _tmp_file(name: str = "events.jsonl") -> Path:
    if TMP_ROOT.exists():
        shutil.rmtree(TMP_ROOT)
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    return TMP_ROOT / name


def _events_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ---------------------------------------------------------------------------
# 1) schema 与开关
# ---------------------------------------------------------------------------

def test_schema_contains_prd_fields():
    """PRD §3.5 点名的字段一个都不能少（另加扩展字段 label）。"""
    expected = {
        "ts", "session_id", "stage", "event", "model",
        "tokens_in", "tokens_out", "latency_ms", "cost",
        "tool_calls", "result", "verdict",
    }
    assert expected == set(REQUIRED_FIELDS), sorted(set(REQUIRED_FIELDS))
    assert expected <= set(SCHEMA_FIELDS)
    assert "label" in SCHEMA_FIELDS                    # 扩展字段


def test_make_event_fills_all_fields_with_none():
    event = make_event(EVENT_LLM_CALL, model="deepseek-chat")
    assert set(event) == set(SCHEMA_FIELDS), sorted(set(event))
    assert event["event"] == EVENT_LLM_CALL
    assert event["model"] == "deepseek-chat"
    assert event["tokens_in"] is None and event["verdict"] is None
    assert event["ts"] and event["session_id"]


def test_recorder_disabled_writes_nothing():
    path = _tmp_file("disabled.jsonl")
    recorder = MetricsRecorder(path=path, enabled=False)
    assert recorder.record(EVENT_LLM_CALL, model="m") is None
    assert not path.exists()


def test_recorder_enabled_writes_one_line_per_event():
    path = _tmp_file("enabled.jsonl")
    recorder = MetricsRecorder(path=path, enabled=True)
    recorder.record(EVENT_LLM_CALL, model="deepseek-chat", tokens_in=10, tokens_out=20)
    recorder.record(EVENT_TURN, stage="learning")

    lines = _events_jsonl(path)
    assert len(lines) == 2
    assert lines[0]["event"] == EVENT_LLM_CALL
    assert lines[0]["tokens_in"] == 10
    assert lines[0]["session_id"] == recorder.session_id
    assert lines[1]["event"] == EVENT_TURN


def test_recorder_counts_llm_calls():
    path = _tmp_file("counter.jsonl")
    recorder = MetricsRecorder(path=path, enabled=True)
    assert recorder.llm_calls == 0
    recorder.record(EVENT_LLM_CALL)
    recorder.record(EVENT_LLM_CALL)
    recorder.record(EVENT_TURN)
    assert recorder.llm_calls == 2


def test_record_is_fail_safe_when_path_unwritable():
    """路径是目录 -> 写失败，但**绝不抛异常**，只累加错误计数。"""
    bad_dir = _tmp_file("a_directory")
    bad_dir.mkdir(parents=True, exist_ok=True)

    recorder = MetricsRecorder(path=bad_dir, enabled=True)
    event = recorder.record(EVENT_LLM_CALL, model="m")     # 不应抛

    assert event is not None                               # 事件本身仍返回
    assert recorder.write_errors == 1


def test_stage_context_is_attached():
    path = _tmp_file("stage.jsonl")
    recorder = MetricsRecorder(path=path, enabled=True)
    metrics.set_stage("evaluation")
    try:
        recorder.record(EVENT_LLM_CALL, label="evaluation_judge")
    finally:
        metrics.set_stage(None)

    line = _events_jsonl(path)[0]
    assert line["stage"] == "evaluation"
    assert line["label"] == "evaluation_judge"


# ---------------------------------------------------------------------------
# 2) 成本：不编造价格
# ---------------------------------------------------------------------------

def test_cost_is_none_without_configured_price():
    settings = Settings()                                  # 未配置单价
    assert estimate_cost(1000, 2000, settings) is None


def test_cost_computed_when_price_configured():
    settings = Settings(price_in_per_mtok=1.0, price_out_per_mtok=2.0)
    # 1.0 * 1_000_000/1_000_000 + 2.0 * 500_000/1_000_000 = 1.0 + 1.0 = 2.0
    assert estimate_cost(1_000_000, 500_000, settings) == 2.0

    settings2 = Settings(price_in_per_mtok=0.5)
    assert estimate_cost(2_000_000, 999, settings2) == 1.0   # 只配了输入价


# ---------------------------------------------------------------------------
# 3) 汇总
# ---------------------------------------------------------------------------

def _sample_events() -> list[dict]:
    def llm(ms, tin, tout, result="ok", stage="learning", label="coach_chat"):
        return {
            "ts": "2026-09-22T10:00:00.000+08:00", "session_id": "s1", "stage": stage,
            "event": EVENT_LLM_CALL, "label": label, "model": "deepseek-chat",
            "tokens_in": tin, "tokens_out": tout, "latency_ms": ms, "cost": None,
            "tool_calls": None, "result": result, "verdict": None,
        }

    return [
        llm(100, 10, 20),
        llm(200, 30, 40),
        {"ts": "t", "session_id": "s1", "stage": "learning", "event": EVENT_TURN,
         "label": "learning->evaluation", "model": None, "tokens_in": None,
         "tokens_out": None, "latency_ms": None, "cost": None, "tool_calls": None,
         "result": "ok", "verdict": None},
        llm(300, 50, 60, stage="evaluation", label="evaluation_judge"),
        llm(400, 70, 80, result="error:TimeoutError", stage="evaluation",
            label="evaluation_judge"),
        {"ts": "t", "session_id": "s1", "stage": "evaluation", "event": EVENT_TURN,
         "label": "evaluation->profile_update", "model": None, "tokens_in": None,
         "tokens_out": None, "latency_ms": None, "cost": None, "tool_calls": None,
         "result": "ok", "verdict": "pass"},
        {"ts": "t", "session_id": "s1", "stage": None, "event": EVENT_CONFIRMATION,
         "label": "delete_history", "model": None, "tokens_in": None, "tokens_out": None,
         "latency_ms": None, "cost": None, "tool_calls": None, "result": "denied",
         "verdict": None},
    ]


def test_summarize_totals_and_latency():
    summary = summarize(_sample_events())

    assert summary["events"] == 7
    assert summary["llm_calls"] == 4
    assert summary["turns"] == 2
    assert summary["tokens_in"] == 10 + 30 + 50 + 70
    assert summary["tokens_out"] == 20 + 40 + 60 + 80
    assert summary["latency_ms"]["p50"] is not None
    assert summary["latency_ms"]["max"] == 400
    assert summary["cost"] is None                          # 事件里 cost 全为 null
    # result 分布：3 条 ok 的 llm_call + 2 条 ok 的 turn = 5；另 1 error + 1 denied
    assert summary["results"]["ok"] == 5
    assert summary["results"]["error:TimeoutError"] == 1
    assert summary["results"]["denied"] == 1
    assert summary["confirmations"] == {"denied": 1}
    assert summary["llm_labels"]["evaluation_judge"] == 2


def test_summarize_llm_calls_per_turn():
    """每轮调用次数由事件顺序还原：第 1 轮 2 次、第 2 轮 2 次。"""
    summary = summarize(_sample_events())
    assert summary["llm_calls_per_turn"] == {"count": 2, "avg": 2.0, "max": 2.0}


def test_summarize_handles_empty():
    summary = summarize([])
    assert summary["events"] == 0
    assert summary["latency_ms"]["p95"] is None
    assert summary["llm_calls_per_turn"]["avg"] is None
    assert summary["cost"] is None
    assert "事件汇总" in render_summary(summary)


def test_load_events_skips_broken_lines():
    path = _tmp_file("broken.jsonl")
    path.write_text(
        '{"event": "llm_call"}\n'
        '\n'
        'not json at all\n'
        '{"event": "turn"}\n',
        encoding="utf-8",
    )
    events = load_events(path)
    assert [e["event"] for e in events] == ["llm_call", "turn"]


def test_load_events_missing_file_returns_empty():
    assert load_events(TMP_ROOT / "nope.jsonl") == []


# ---------------------------------------------------------------------------
# 4) 导出
# ---------------------------------------------------------------------------

def test_export_csv_and_jsonl():
    path = _tmp_file("export.jsonl")
    recorder = MetricsRecorder(path=path, enabled=True)
    recorder.record(EVENT_LLM_CALL, model="deepseek-chat", tokens_in=1, tokens_out=2)
    recorder.record(EVENT_TURN, stage="learning")
    events = load_events(path)

    csv_path = path.parent / "out.csv"
    export_events(events, csv_path, "csv")
    text = csv_path.read_text(encoding="utf-8-sig")
    header, *rows = [line for line in text.splitlines() if line.strip()]
    assert list(SCHEMA_FIELDS) == header.split(",")
    assert len(rows) == 2

    jsonl_path = path.parent / "out.jsonl"
    export_events(events, jsonl_path, "jsonl")
    assert load_events(jsonl_path) == events


def test_export_cli_handles_missing_file():
    missing = TMP_ROOT / "missing.jsonl"
    assert export_main(["--path", str(missing)]) == 0


def test_export_cli_writes_file():
    path = _tmp_file("cli.jsonl")
    recorder = MetricsRecorder(path=path, enabled=True)
    recorder.record(EVENT_LLM_CALL, model="m", tokens_in=5, tokens_out=6)

    out = path.parent / "cli_out.csv"
    assert export_main(["--path", str(path), "--out", str(out)]) == 0
    assert out.exists()
    assert "llm_call" in out.read_text(encoding="utf-8-sig")


def test_default_recorder_is_disabled():
    """库默认不采集：避免测试/工具误写真实指标文件。"""
    assert MetricsRecorder(path=_tmp_file("x.jsonl"), enabled=False).enabled is False
    if not os.getenv("COACH_METRICS"):
        assert metrics.get_recorder().enabled is False


# ---------------------------------------------------------------------------
# 极简 runner（共用实现见 tests/_runner.py）
# ---------------------------------------------------------------------------

from _runner import SkipTest, run_tests        # noqa: E402


def main() -> int:
    return run_tests(globals())


if __name__ == "__main__":
    raise SystemExit(main())
