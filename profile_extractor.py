"""profile_extractor.py —— V0.2 结构化用户画像抽取。

作用：把用户这句话里的学习需求，抽成结构化字段（第二次 LLM 调用）。

为什么要单独一次 LLM 调用：
- 聊天要的是"自然、连贯"，抽取要的是"严格、结构化"，两个目标互相干扰
- 分开调用后，抽取可以用最低温度 + JSON 输出模式，稳定得多

设计原则（对应 V0.2 方案）：
1. 只抽取**最新一条用户消息**里的信息（增量抽取），累积交给 state.merge_profile
2. 用户没提到的字段一律 null —— "没提到"不等于"不存在"
3. 失败兜底：JSON 解析/类型校验失败时返回空画像，绝不中断对话

用法：
    from profile_extractor import extract_profile
    profile = extract_profile("我想一个月学 Python，每天 30 分钟")
"""

import json
import re

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# LLM 客户端：惰性创建
# 这样只使用 UserProfile（schema/合并/阶段）的单元测试无需 API Key 也能 import
# ---------------------------------------------------------------------------

_client = None


def _get_client():
    """首次真正需要调用模型时才创建客户端（也就才要求 API Key）。"""
    global _client
    if _client is None:
        from openai import OpenAI

        from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

        _client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )
    return _client


# ---------------------------------------------------------------------------
# 结构化 schema（Pydantic 负责类型校验与清洗）
# ---------------------------------------------------------------------------

class UserProfile(BaseModel):
    """学习需求画像的四个字段，全部可选（没提到就是 None）。"""

    learning_goal: str | None = None      # 想学什么
    current_level: str | None = None      # 当前水平
    daily_minutes: int | None = None      # 每天可投入分钟数
    target_date: str | None = None        # 期望期限

    @field_validator("learning_goal", "current_level", "target_date", mode="before")
    @classmethod
    def _blank_to_none(cls, value):
        """空白字符串一律视为"没提到"。"""
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("daily_minutes", mode="before")
    @classmethod
    def _parse_minutes(cls, value):
        """把模型可能给出的各种写法归一成整数分钟。

        容忍："30" / "30分钟" / 30 / "1小时"（->60）/ "半小时"（->30）
        实在无法解析就返回 None（宁缺勿错）。
        """
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            number = re.search(r"(\d+(?:\.\d+)?)", text)
            if number:
                minutes = float(number.group(1))
                if "小时" in text or "h" in text.lower():
                    minutes *= 60
                return int(minutes)
            if "半" in text and ("小时" in text or "h" in text.lower()):
                return 30
        return None


# ---------------------------------------------------------------------------
# 抽取
# ---------------------------------------------------------------------------

EXTRACT_SYSTEM_PROMPT = """
你是信息抽取器。请从用户最新的一句话中抽取学习需求，只输出 JSON。

字段说明：
- learning_goal: 想学习的技能或主题（字符串）
- current_level: 当前水平或基础（字符串）
- daily_minutes: 每天可投入的时间，单位分钟（整数；"半小时"=30，"1小时"=60）
- target_date: 期望达成目标的期限（字符串，如 "1个月"、"三个月"、"年底"）

规则：
- 只抽取用户明确说出的信息，不要推测、不要编造、不要补充常识。
- 没有提到的字段一律输出 null。
- 不要输出任何解释文字，只输出 JSON 对象。
""".strip()


def extract_profile(user_input: str) -> UserProfile:
    """从一条用户消息中抽取画像字段；任何异常都降级为空画像。"""
    text = (user_input or "").strip()
    if not text:
        return UserProfile()

    try:
        response = _get_client().chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            # JSON 输出模式：约束模型只产出 JSON，避免解析自由文本
            response_format={"type": "json_object"},
            temperature=0,      # 抽取要稳定，不要创造性
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        return UserProfile.model_validate(data)

    except Exception as exc:            # noqa: BLE001 —— 抽取失败绝不能中断对话
        print(f"[画像抽取失败，本轮已跳过] {type(exc).__name__}: {exc}")
        return UserProfile()
