"""LLM 访问的唯一实现。

为什么集中在这里：
- 此前 `assessor` / `planner` / `daily` / `evaluator` / `profile_extractor` 各自维护一份
  几乎逐字相同的 `_client` + `_get_client()` + `_json_call()`，且都把模型名写死为
  "deepseek-chat"（共 6 处）。现在只有这一处。
- 客户端按 (base_url, api_key) 缓存，避免每个模块各建一个连接池。
- **导入本模块不需要 API Key**；只有真正调用时才要求 Key（见 `Settings.require_api_key`）。
"""

import json
from typing import Any

from coach.config import MissingApiKeyError, Settings, get_settings

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


def json_call(
    system_prompt: str,
    user_content: str,
    settings: Settings | None = None,
) -> dict:
    """一次 JSON 模式调用，返回解析后的 dict。

    失败（含 JSON 解析失败）由调用方兜底，本函数不吞异常。
    """
    settings = settings or get_settings()
    response = get_client(settings).chat.completions.create(
        model=settings.model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=settings.temperature,
    )
    return json.loads(response.choices[0].message.content or "{}")


def chat(messages: list[dict], settings: Settings | None = None) -> str:
    """普通文本对话（不约束 JSON），用于教练主对话。"""
    settings = settings or get_settings()
    response = get_client(settings).chat.completions.create(
        model=settings.model,
        messages=messages,
    )
    return response.choices[0].message.content or ""
