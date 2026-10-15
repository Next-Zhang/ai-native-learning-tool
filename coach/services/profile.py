"""画像抽取用例（原 `profile_extractor.py`）。

为什么要单独一次 LLM 调用：聊天要的是"自然、连贯"，抽取要的是"严格、结构化"，
两个目标互相干扰。分开后抽取可用最低温度 + JSON 输出模式，稳定得多。

兜底：任何异常都降级为空画像并把 `ok=False`（**F1**）—— **绝不中断对话**。
"""

from coach.domain.models import UserProfile
from coach.domain.perception import KIND_PROFILE, PerceptionResult
from coach.llm import client
from coach.prompts.tasks import EXTRACT_SYSTEM_PROMPT

__all__ = ["EXTRACT_SYSTEM_PROMPT", "PerceptionResult", "UserProfile", "extract_profile"]


def extract_profile(user_input: str) -> PerceptionResult:
    """从一条用户消息中抽取画像字段（**F1 判定点**：`kind = profile`）。

    **改造点**：失败返回 `ok=False`（payload 仍是空画像）。
    改造前失败与"用户确实没提供信息"的返回值**完全一致** ——
    这正是 `evals/README.md` 记下的那条已知局限。
    """
    text = (user_input or "").strip()
    if not text:
        return PerceptionResult.failure(KIND_PROFILE, error="empty_input")

    try:
        data = client.json_call(EXTRACT_SYSTEM_PROMPT, text, label="profile_extract")
        return PerceptionResult.validated(KIND_PROFILE, UserProfile.model_validate(data))
    except Exception as exc:            # noqa: BLE001 —— 抽取失败绝不能中断对话
        print(f"[画像抽取失败，本轮已跳过] {type(exc).__name__}: {exc}")
        return PerceptionResult.failure(
            KIND_PROFILE,
            payload=UserProfile().model_dump(),   # 兜底值（P-1 允许兜底，但 ok=False）
            error=f"{type(exc).__name__}: {exc}",
        )
