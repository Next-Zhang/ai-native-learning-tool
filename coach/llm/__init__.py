"""模型访问层：全项目唯一的 LLM 出口。

对外只需 `client` 模块的四个符号：
    get_client()  —— 原始 OpenAI 客户端
    json_call()   —— JSON 模式单次调用（结构性输出统一走这里）
    chat()        —— 普通文本对话（教练主对话）
    MissingApiKeyError

模型名、温度、base_url 一律取自 `coach.config.Settings`，不再散落各处。
"""

from coach.llm.client import MissingApiKeyError, chat, get_client, json_call

__all__ = ["MissingApiKeyError", "chat", "get_client", "json_call"]
