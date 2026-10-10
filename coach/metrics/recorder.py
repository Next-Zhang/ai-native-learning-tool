"""事件级指标采集（PRD **S-07** / §3.5 日志与审计）。

职责
----
把每轮交互的关键量化事实写成**本机 JSONL**（一行一条），供 §3.1/§3.2 的指标
（token 成本、P95 延迟、平均每轮 LLM 调用次数、判定分布）与 §3.3 的评测读数使用。

设计约束（都来自 PRD）
--------------------
1. **采集失败绝不能影响主流程**（§2.7）：`record()` 吞掉一切异常，只累加内部错误计数。
2. **字段固定**（§3.5）：`ts / session_id / stage / event / model / tokens_in /
   tokens_out / latency_ms / cost / tool_calls / result / verdict`
   —— 另加一个扩展字段 `label`（调用用途，如 `assessment_judge`），便于定位是哪个判定点慢/贵。
3. **不编造价格**：未配置单价时 `cost` 记为 `null`，只记录 token 用量。
4. **默认关闭**：导入本模块无副作用；由 `coach.cli.main` 启动时显式 `enable()`，
   因此测试/工具不会误写真实指标文件。可用 `COACH_METRICS=on` 覆盖。

存储：`data/metrics/events.jsonl`（本机；不做实时看板）。
"""

import json
import os
import uuid
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from coach.config import DATA_DIR, get_settings

METRICS_DIR = DATA_DIR / "metrics"
EVENTS_FILENAME = "events.jsonl"

ENABLED_ENV = "COACH_METRICS"
PATH_ENV = "COACH_METRICS_PATH"

_TRUTHY = {"1", "on", "true", "yes", "y"}

# PRD §3.5 规定的最小字段集
REQUIRED_FIELDS = (
    "ts", "session_id", "stage", "event", "model",
    "tokens_in", "tokens_out", "latency_ms", "cost",
    "tool_calls", "result", "verdict",
)
# 本项目扩展字段（PRD 必填字段之外）
EXTRA_FIELDS = ("label",)
#: 事件字段全集；**顺序即 CSV 导出的列顺序**（`coach.metrics.export`）
SCHEMA_FIELDS = ("ts", "session_id", "stage", "event", *EXTRA_FIELDS, "model",
                 "tokens_in", "tokens_out", "latency_ms", "cost",
                 "tool_calls", "result", "verdict")

# 事件名
EVENT_LLM_CALL = "llm_call"
EVENT_TURN = "turn"
EVENT_CONFIRMATION = "confirmation"
#: v0.18：归档裁剪**必须留痕**（I-13）—— 静默丢弃是"窗口化退化成截断"的根源。
EVENT_ARCHIVE_PRUNED = "archive_pruned"

# 当前阶段（由 orchestration 设置，供 llm_call 事件归属阶段）
_stage_var: ContextVar[str | None] = ContextVar("coach_metrics_stage", default=None)


def set_stage(stage: str | None) -> None:
    _stage_var.set(stage)


def current_stage() -> str | None:
    return _stage_var.get()


def default_events_path() -> Path:
    override = os.getenv(PATH_ENV)
    return Path(override) if override else (METRICS_DIR / EVENTS_FILENAME)


def _env_enabled() -> bool:
    raw = os.getenv(ENABLED_ENV)
    return bool(raw) and raw.strip().lower() in _TRUTHY


def _now_iso() -> str:
    """带本地时区偏移的 ISO 时间戳（毫秒精度）。"""
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def estimate_cost(tokens_in, tokens_out, settings=None) -> float | None:
    """按配置的每百万 token 单价估算成本。

    **未配置单价则返回 None** —— 本项目不编造价格（PRD §3.7 O-03 待定）。
    """
    settings = settings or get_settings()
    if settings.price_in_per_mtok is None and settings.price_out_per_mtok is None:
        return None
    total = 0.0
    if settings.price_in_per_mtok is not None:
        total += (tokens_in or 0) / 1_000_000 * settings.price_in_per_mtok
    if settings.price_out_per_mtok is not None:
        total += (tokens_out or 0) / 1_000_000 * settings.price_out_per_mtok
    return round(total, 6)


def make_event(event: str, **fields) -> dict:
    """构造一条扁平事件；未提供的字段一律为 None。"""
    payload = {name: None for name in SCHEMA_FIELDS}
    payload["event"] = event
    payload["ts"] = fields.pop("ts", None) or _now_iso()
    payload["session_id"] = fields.pop("session_id", None) or current_session_id()
    if "stage" not in fields:
        fields["stage"] = current_stage()
    for key, value in fields.items():
        if key in payload:
            payload[key] = value
    return payload


class MetricsRecorder:
    """JSONL 事件记录器。**任何写入异常都不会向上抛。**"""

    def __init__(self, path: Path | None = None, enabled: bool = False):
        self._path = Path(path) if path is not None else default_events_path()
        self._enabled = enabled
        self._write_errors = 0
        self._llm_calls = 0
        self._session_id = new_session_id()

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
    def llm_calls(self) -> int:
        """自本 recorder 创建以来的 LLM 调用次数（用于"平均每轮调用次数"护栏）。"""
        return self._llm_calls

    @property
    def session_id(self) -> str:
        return self._session_id

    def enable(self, path: Path | None = None) -> None:
        if path is not None:
            self._path = Path(path)
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def reset_session(self, session_id: str | None = None) -> str:
        self._session_id = session_id or new_session_id()
        self._llm_calls = 0
        return self._session_id

    # -- 采集 ---------------------------------------------------------------

    def record(self, event: str, **fields) -> dict | None:
        """写入一条事件。

        未启用时返回 None（不写盘）。**写入失败只累加错误计数，绝不抛异常**。
        无论是否写成功都返回事件 dict，便于测试与调用方检查内容。
        """
        if not self._enabled:
            return None

        if event == EVENT_LLM_CALL:
            self._llm_calls += 1

        fields.setdefault("session_id", self._session_id)
        payload = make_event(event, **fields)

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:                  # noqa: BLE001 —— 采集绝不能影响主流程
            self._write_errors += 1

        return payload


# ---------------------------------------------------------------------------
# 模块级默认实例与便捷函数
# ---------------------------------------------------------------------------

_recorder = MetricsRecorder(enabled=_env_enabled())


def get_recorder() -> MetricsRecorder:
    return _recorder


def configure(path: Path | None = None, enabled: bool | None = None) -> MetricsRecorder:
    """重设默认记录器（测试与工具用）。"""
    global _recorder
    _recorder = MetricsRecorder(path=path, enabled=bool(enabled))
    return _recorder


def enable(path: Path | None = None) -> MetricsRecorder:
    _recorder.enable(path)
    return _recorder


def disable() -> MetricsRecorder:
    _recorder.disable()
    return _recorder


def record(event: str, **fields) -> dict | None:
    """便捷入口；等价于 `get_recorder().record(...)`。"""
    return _recorder.record(event, **fields)


def current_session_id() -> str:
    return _recorder.session_id
