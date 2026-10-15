"""单轮因果链（**F5**）：把 `输入 → 判定 → 状态变化 → 回复` 记成**可回放**的一行。

为什么需要它
------------
现有指标只有**事件级**粒度。X-16（教练抢答判定）那次排查只能**人肉比对 messages** ——
因为"这一轮到底跑过哪些能力、每个能力改了什么、模型被调了几次"根本没有落盘的地方。

一条 trace = 一轮，形如::

    {"ts","session_id","turn","stage_before","stage_after","user_input",
     "transitions":[["learning","evaluation"]],
     "steps":[{"capability","status":"ran|skipped","reason","changed":{key: 摘要}}],
     "llm_calls":[{"label","ok","latency_ms","tokens_in","tokens_out","error"}],
     "notes":[],"answer","sources","elapsed_ms"}

三条纪律（与 `coach.metrics` 一致）
----------------------------------
1. **采集失败绝不影响主流程** —— 所有写入口都吞异常，只累加错误计数。
2. **默认关闭** —— 导入本模块无副作用；由 `coach.cli.main` 启动时 `enable()`。
   它比指标更"重"（含用户原话与回复），默认关是更保守的选择。
3. **有上界** —— 单个字段截断；文件超过 `MAX_BYTES` 时轮转到 `turns.jsonl.1`（只留一代），
   且轮转**留痕**（在文件开头写一条 `rotated` 记录）。
   无界增长与"静默丢弃"是同一类问题（见 memory-design **I-13**）。

存储：`data/traces/turns.jsonl`（本机；不提交）。
"""

import json
import os
import shutil
import time
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from coach.config import DATA_DIR
from coach.metrics import recorder as metrics

TRACE_DIR = DATA_DIR / "traces"
TRACE_FILENAME = "turns.jsonl"

ENABLED_ENV = "COACH_TRACE"
PATH_ENV = "COACH_TRACE_PATH"

_TRUTHY = {"1", "on", "true", "yes", "y"}

#: 长文本字段（用户原话 / 回复 / note）的截断长度
MAX_TEXT = 600
#: 单条状态摘要的截断长度
MAX_BRIEF = 160
#: 文件超过它就轮转（只保留一代备份）
MAX_BYTES = 2 * 1024 * 1024


def _now_iso() -> str:
    """带本地时区偏移的 ISO 时间戳（与 metrics 同口径）。"""
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _env_enabled() -> bool:
    raw = os.getenv(ENABLED_ENV)
    return bool(raw) and raw.strip().lower() in _TRUTHY


def default_path() -> Path:
    override = os.getenv(PATH_ENV)
    return Path(override) if override else (TRACE_DIR / TRACE_FILENAME)


def brief(value, limit: int = MAX_BRIEF) -> str:
    """把一个值压成**一行短摘要**。

    状态变化的记录**只用于回答"哪个键变了"**，不用于回放具体值 ——
    所以截断是特性不是缺陷：trace 不能因为一个巨大的窗口计划而膨胀。
    """
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:                  # noqa: BLE001 —— 摘要失败不该影响任何东西
            text = repr(value)
    return text if len(text) <= limit else text[:limit] + "…"


class TurnTrace:
    """一轮的因果链记录器。**即使采集关闭也安全可用**（只是最后不落盘）。"""

    def __init__(self, *, user_input: str = "", stage_before: str = ""):
        self._started = time.perf_counter()
        self._data = {
            "ts": _now_iso(),
            "session_id": "",
            "turn": 0,
            "stage_before": stage_before,
            "stage_after": stage_before,
            "user_input": brief(user_input, MAX_TEXT),
            "transitions": [],
            "steps": [],
            "llm_calls": [],
            "notes": [],
            "answer": "",
            "sources": [],
            "elapsed_ms": 0,
        }

    # -- 记录 ---------------------------------------------------------------

    def step(self, capability: str, *, status: str, reason: str = "") -> dict:
        """记一个步骤（`status` = `ran` / `skipped`）。返回条目，便于补 `changed`。"""
        entry = {"capability": capability, "status": status}
        if reason:
            entry["reason"] = reason
        self._data["steps"].append(entry)
        return entry

    def changed(self, entry: dict, changes: dict) -> None:
        """补上该步骤改动过的 state 键（顶层粒度，与 F7 契约测试同一口径）。"""
        if changes:
            entry["changed"] = {key: brief(value) for key, value in changes.items()}

    def transition(self, before: str, after: str) -> None:
        self._data["transitions"].append([before, after])

    def llm_call(self, **fields) -> None:
        self._data["llm_calls"].append(fields)

    def note(self, message: str) -> None:
        """自由文本备注（兜底路径、异常摘要等）。"""
        self._data["notes"].append(brief(message, MAX_TEXT))

    def finish(self, *, answer: str = "", sources=None, stage_after=None) -> dict:
        self._data["answer"] = brief(answer, MAX_TEXT)
        if sources:
            self._data["sources"] = [
                {"title": item.get("title"), "section": item.get("section")}
                for item in sources if isinstance(item, dict)
            ]
        if stage_after is not None:
            self._data["stage_after"] = stage_after
        self._data["elapsed_ms"] = int((time.perf_counter() - self._started) * 1000)
        return self._data


class TraceRecorder:
    """JSONL 追加器：一轮一行。**任何写入异常都不会向上抛。**"""

    def __init__(self, path=None, enabled: bool = False):
        self._path = Path(path) if path is not None else default_path()
        self._enabled = enabled
        self._write_errors = 0
        self._turns = 0

    # -- 配置 ---------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def path(self) -> Path:
        return self._path

    @property
    def write_errors(self) -> int:
        return self._write_errors

    @property
    def turns(self) -> int:
        """自本 recorder 创建以来落盘的轮数。"""
        return self._turns

    def enable(self, path=None) -> None:
        if path is not None:
            self._path = Path(path)
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    # -- 采集 ---------------------------------------------------------------

    def record(self, payload: dict):
        """追加一轮。未启用返回 None；写入失败只累加计数，**绝不抛**。"""
        if not self._enabled:
            return None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed()
            next_turn = self._turns + 1
            payload["turn"] = next_turn
            payload["session_id"] = metrics.current_session_id()
            line = json.dumps(payload, ensure_ascii=False, default=str)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._turns = next_turn      # 只有**真的写成功**才计数
        except Exception:                  # noqa: BLE001 —— 采集绝不能影响主流程
            self._write_errors += 1
        return payload

    def _rotate_if_needed(self) -> None:
        """文件过大就轮转一代，并在新文件开头**留痕**（不静默丢）。"""
        if not self._path.exists() or self._path.stat().st_size < MAX_BYTES:
            return
        backup = self._path.with_name(self._path.name + ".1")
        shutil.move(str(self._path), str(backup))       # 覆盖上一代
        with self._path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "ts": _now_iso(),
                "event": "rotated",
                "note": f"上一条 trace 文件超过 {MAX_BYTES} 字节，已轮转为 {backup.name}",
            }, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 模块级默认实例与便捷函数
# ---------------------------------------------------------------------------

_recorder = TraceRecorder(enabled=_env_enabled())
#: 当前正在记录的那一轮（由 `start` 设置、`finish` 清空）
_current: ContextVar = ContextVar("coach_turn_trace", default=None)


def get_recorder() -> TraceRecorder:
    return _recorder


def configure(path=None, enabled=None) -> TraceRecorder:
    """重设默认记录器（测试与工具用）。"""
    global _recorder
    _recorder = TraceRecorder(path=path, enabled=bool(enabled))
    return _recorder


def enable(path=None) -> TraceRecorder:
    _recorder.enable(path)
    return _recorder


def disable() -> TraceRecorder:
    _recorder.disable()
    return _recorder


def start(user_input: str = "", stage_before: str = "") -> TurnTrace:
    """开始一轮的 trace。返回的对象**总是**可用；是否落盘由 recorder 决定。"""
    trace = TurnTrace(user_input=user_input, stage_before=stage_before)
    _current.set(trace)
    return trace


def current():
    """取当前这一轮的 trace；不在轮内时返回 None（调用方必须容忍 None）。"""
    return _current.get()


def finish(*, answer: str = "", sources=None, stage_after=None):
    """结束当前这一轮并落盘。返回落盘的 payload（未落盘时为那个 dict）。"""
    trace = _current.get()
    _current.set(None)
    if trace is None:
        return None
    payload = trace.finish(answer=answer, sources=sources, stage_after=stage_after)
    _recorder.record(payload)          # 未启用时是 no-op
    return payload


def note_llm_call(**fields) -> None:
    """把一次模型调用挂到当前这一轮上（由 `coach/llm/client.py` 调用）。"""
    trace = _current.get()
    if trace is not None:
        trace.llm_call(**fields)
