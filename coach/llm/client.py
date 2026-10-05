"""LLM 访问的唯一实现。

为什么集中在这里：
- 此前 `assessor` / `planner` / `daily` / `evaluator` / `profile_extractor` 各自维护一份
  几乎逐字相同的 `_client` + `_get_client()` + `_json_call()`，且都把模型名写死为
  "deepseek-chat"（共 6 处）。现在只有这一处。
- 客户端按 (base_url, api_key) 缓存，避免每个模块各建一个连接池。
- **导入本模块不需要 API Key**；只有真正调用时才要求 Key（见 `Settings.require_api_key`）。
- 每次调用都会记录一条 `llm_call` 指标事件（token / 延迟 / 成本 / 结果），
  供 PRD §3.1/§3.2 的 M-03、M-04 与 §8 护栏读数使用。**采集失败绝不影响调用本身。**
"""

import json
import time
from typing import Any

from coach.config import MissingApiKeyError, Settings, get_settings
from coach.metrics import recorder as metrics

_clients: dict[tuple[str, str], Any] = {}

__all__ = ["MissingApiKeyError", "chat", "get_client", "json_call"]


def get_client(settings: Settings | None = None):
    """返回 OpenAI 兼容客户端；缺少 API Key 时抛 MissingApiKeyError。"""
    settings = settings or get_settings()
    api_key = settings.require_api_key()

    cache_key = (settings.base_url, api_key)
    client = _clients.get(cache_key)
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=settings.base_url)
        _clients[cache_key] = client
    return client


def _record_llm_call(
    settings: Settings,
    started: float,
    label: str | None,
    *,
    result: str,
    response=None,
) -> None:
    """记录一条 llm_call 事件；**任何异常都被吞掉**（采集不影响主流程）。"""
    try:
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = getattr(response, "usage", None) if response is not None else None
        tokens_in = getattr(usage, "prompt_tokens", None)
        tokens_out = getattr(usage, "completion_tokens", None)

        metrics.record(
            metrics.EVENT_LLM_CALL,
            label=label,
            model=settings.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            cost=metrics.estimate_cost(tokens_in, tokens_out, settings),
            result=result,
        )
    except Exception:                      # noqa: BLE001 —— 采集绝不能影响 LLM 调用
        pass


def _create(settings: Settings, messages: list[dict], *, label: str | None, **kwargs):
    """发起一次模型调用，并记录指标。"""
    client = get_client(settings)          # 缺 Key 在这里抛，不计入指标（并非模型调用）
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=settings.model,
            messages=messages,
            **kwargs,
        )
    except Exception as exc:               # noqa: BLE001 —— 记录后原样抛出，由调用方兜底
        _record_llm_call(
            settings, started, label, result=f"error:{type(exc).__name__}"
        )
        raise

    _record_llm_call(settings, started, label, result="ok", response=response)
    return response


def json_call(
    system_prompt: str,
    user_content: str,
    settings: Settings | None = None,
    *,
    label: str | None = None,
) -> dict:
    """一次 JSON 模式调用，返回解析后的 dict。

    `label` 是调用用途标签（如 `assessment_judge`），仅用于指标定位。
    失败（含 JSON 解析失败）由调用方兜底，本函数不吞异常。
    """
    settings = settings or get_settings()
    response = _create(
        settings,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        label=label,
        response_format={"type": "json_object"},
        temperature=settings.temperature,
    )
    return json.loads(response.choices[0].message.content or "{}")


def chat(
    messages: list[dict],
    settings: Settings | None = None,
    *,
    label: str | None = None,
) -> str:
    """普通文本对话（不约束 JSON），用于教练主对话。"""
    settings = settings or get_settings()
    response = _create(settings, messages, label=label or "coach_chat")
    return response.choices[0].message.content or ""
