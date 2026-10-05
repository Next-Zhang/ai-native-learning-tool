"""读取事件并汇总成 PRD §3.1/§3.2 需要的指标。

汇总项与 PRD 的对应：
- token 用量与成本 → M-03「单轮 token 成本」
- 延迟 p50/p95     → M-04「P95 延迟」
- 每轮 LLM 调用次数 → §8 护栏「平均每轮 LLM 调用次数」（对抗 workflow 膨胀）
- 结果/判定分布     → §9 系统可靠性与判定可观测性
- 确认门分布       → S-08 的人机介入可观测性
"""

import json
from collections import Counter
from pathlib import Path

from coach.metrics.recorder import (
    EVENT_CONFIRMATION,
    EVENT_LLM_CALL,
    EVENT_TURN,
    default_events_path,
)


def load_events(path: Path | None = None) -> list[dict]:
    """读取 JSONL 事件；跳过空行与损坏行（不抛异常）。"""
    target = Path(path) if path is not None else default_events_path()
    if not target.exists():
        return []

    events: list[dict] = []
    for raw in target.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def _llm_calls_per_turn(events: list[dict]) -> list[int]:
    """按事件顺序还原"每轮发生了多少次 LLM 调用"。

    `turn` 事件在**每轮结束时**写入，因此两次 turn 之间的 llm_call 数量
    就是那一轮的调用次数（事件 schema 里没有 per-turn 计数字段）。
    """
    counts: list[int] = []
    pending = 0
    for item in events:
        kind = item.get("event")
        if kind == EVENT_LLM_CALL:
            pending += 1
        elif kind == EVENT_TURN:
            counts.append(pending)
            pending = 0
    return counts


def percentile(values: list[float], ratio: float) -> float | None:
    """最近的秩方法（nearest-rank），不插值 —— 小样本下更直观。"""
    if not values:
        return None
    ordered = sorted(values)
    if ratio <= 0:
        return ordered[0]
    if ratio >= 1:
        return ordered[-1]
    index = max(0, min(len(ordered) - 1, int(round(ratio * len(ordered))) - 1))
    return ordered[index]


def _numbers(events, field: str) -> list[float]:
    out: list[float] = []
    for item in events:
        value = item.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append(float(value))
    return out


def summarize(events: list[dict]) -> dict:
    """把事件列表汇总成一份可直接读数的字典。"""
    llm_events = [e for e in events if e.get("event") == EVENT_LLM_CALL]
    turn_events = [e for e in events if e.get("event") == EVENT_TURN]
    confirm_events = [e for e in events if e.get("event") == EVENT_CONFIRMATION]

    latency = _numbers(llm_events, "latency_ms")
    costs = _numbers(llm_events, "cost")
    per_turn = _llm_calls_per_turn(events)

    tokens_in = sum(v for v in _numbers(llm_events, "tokens_in"))
    tokens_out = sum(v for v in _numbers(llm_events, "tokens_out"))

    results = Counter(str(e.get("result")) for e in events if e.get("result") is not None)
    verdicts = Counter(
        str(e.get("verdict")) for e in events if e.get("verdict") is not None
    )
    confirmations = Counter(
        str(e.get("result")) for e in confirm_events if e.get("result") is not None
    )
    labels = Counter(
        str(e.get("label")) for e in llm_events if e.get("label") is not None
    )

    return {
        "events": len(events),
        "llm_calls": len(llm_events),
        "turns": len(turn_events),
        "sessions": len({e.get("session_id") for e in events if e.get("session_id")}),
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "tokens_total": int(tokens_in + tokens_out),
        # 未配置单价时这里会是 None —— 不编造价格
        "cost": round(sum(costs), 6) if costs else None,
        "latency_ms": {
            "count": len(latency),
            "avg": round(sum(latency) / len(latency), 1) if latency else None,
            "p50": percentile(latency, 0.50),
            "p95": percentile(latency, 0.95),
            "max": max(latency) if latency else None,
        },
        "llm_calls_per_turn": {
            "count": len(per_turn),
            "avg": round(sum(per_turn) / len(per_turn), 2) if per_turn else None,
            "max": max(per_turn) if per_turn else None,
        },
        "results": dict(results),
        "verdicts": dict(verdicts),
        "confirmations": dict(confirmations),
        "llm_labels": dict(labels),
    }


def render_summary(summary: dict) -> str:
    """把汇总渲染成终端可读文本。"""
    latency = summary["latency_ms"]
    per_turn = summary["llm_calls_per_turn"]
    lines = [
        "事件汇总（M-03 / M-04 / §8 护栏）",
        f"  事件总数        : {summary['events']}（LLM 调用 {summary['llm_calls']}，轮次 {summary['turns']}，会话 {summary['sessions']}）",
        f"  token 用量      : in={summary['tokens_in']} out={summary['tokens_out']} 合计={summary['tokens_total']}",
        f"  成本            : {summary['cost'] if summary['cost'] is not None else '未知（未配置 COACH_PRICE_*，不编造价格）'}",
        f"  延迟 ms (LLM)   : p50={latency['p50']} p95={latency['p95']} avg={latency['avg']} max={latency['max']}",
        f"  每轮 LLM 调用数 : avg={per_turn['avg']} max={per_turn['max']}（护栏：不应持续增长）",
        f"  结果分布        : {summary['results'] or '（无）'}",
        f"  判定分布        : {summary['verdicts'] or '（无）'}",
        f"  确认门分布      : {summary['confirmations'] or '（无）'}",
        f"  调用用途分布    : {summary['llm_labels'] or '（无）'}",
    ]
    return "\n".join(lines)
