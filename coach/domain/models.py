"""全项目的数据契约（Pydantic 模型）。

集中在一处的好处：模型的结构化输出契约可以被统一评审、统一校验，
不会像以前那样分散在 `profile_extractor` / `assessor` / `planner` / `daily` / `evaluator` 五个文件里。

注意：本模块只定义"数据长什么样"与字段级清洗/归一，不做 IO、不调 LLM。
"""

import re

from pydantic import BaseModel, field_validator, model_validator

from coach.domain.assessment_rules import VERDICT_ALIASES
from coach.domain.evaluation_rules import (
    ACTION_ALIASES,
    COMPLETION_ALIASES,
    completion_score,
    normalize_action,
    normalize_error_types,
)


#: 中文数字 → 次数（用于"每周三次"这类写法）
_CN_COUNTS = {
    "一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


# ---------------------------------------------------------------------------
# 学习需求画像
# ---------------------------------------------------------------------------

class UserProfile(BaseModel):
    """学习需求画像。

    **必填四项**（见 `profile_rules.PROFILE_FIELDS`）：目标 / 水平 / **单次可投入时长** / 期限。
    `sessions_per_week` 是**可选**的——碎片化场景下"每周几次"常无法承诺，
    强制追问只会增加摩擦（UR-08：一次只问 1~2 个关键问题）。
    """

    learning_goal: str | None = None      # 想学什么
    current_level: str | None = None      # 当前水平
    session_minutes: int | None = None    # **单次**可投入分钟数（碎片化的基本单位）
    target_date: str | None = None        # 期望期限
    sessions_per_week: int | None = None  # 每周大约几次（可选；None = 不作承诺）

    @field_validator("learning_goal", "current_level", "target_date", mode="before")
    @classmethod
    def _blank_to_none(cls, value):
        """空白字符串一律视为"没提到"。"""
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("session_minutes", mode="before")
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

    @field_validator("sessions_per_week", mode="before")
    @classmethod
    def _parse_count(cls, value):
        """把"每周几次"归一成整数（可选字段）。

        容忍："3" / "3次" / "每周三次" / 3；无法解析 → None（宁缺勿错）。
        """
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return max(1, int(value))
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            number = re.search(r"(\d+(?:\.\d+)?)", text)
            if number:
                return max(1, int(float(number.group(1))))
            chinese = re.search(r"([一两二三四五六七八九十])", text)
            if chinese:
                return _CN_COUNTS[chinese.group(1)]
        return None


# ---------------------------------------------------------------------------
# 能力测评
# ---------------------------------------------------------------------------

class AssessmentQuestion(BaseModel):
    index: int = 0
    topic: str = ""
    difficulty: int = 1


class AssessmentPlan(BaseModel):
    questions: list[AssessmentQuestion] = []


class AnswerRecord(BaseModel):
    index: int
    topic: str = ""
    answer: str = ""
    verdict: str = "missing"
    note: str = ""

    @field_validator("verdict", mode="before")
    @classmethod
    def _normalize_verdict(cls, value):
        key = str(value or "").strip().lower()
        return VERDICT_ALIASES.get(key, "missing")

    @field_validator("answer", "note", mode="before")
    @classmethod
    def _clean_text(cls, value):
        if isinstance(value, str):
            return value.strip()
        return "" if value is None else str(value)


# ---------------------------------------------------------------------------
# 学习计划
# ---------------------------------------------------------------------------

class PlanTask(BaseModel):
    goal: str = ""
    material: str = ""
    exercise: str = ""
    minutes: int = 0
    done_criteria: str = ""

    @field_validator("minutes", mode="before")
    @classmethod
    def _parse_minutes(cls, value):
        if value is None or isinstance(value, bool):
            return 0
        if isinstance(value, (int, float)):
            return max(0, int(value))
        if isinstance(value, str):
            match = re.search(r"(\d+(?:\.\d+)?)", value)
            if match:
                return max(0, int(float(match.group(1))))
        return 0

    @field_validator("goal", "material", "exercise", "done_criteria", mode="before")
    @classmethod
    def _clean_text(cls, value):
        if isinstance(value, str):
            return value.strip()
        return "" if value is None else str(value)


class ConfirmationVerdict(BaseModel):
    confirmed: bool = False
    reason: str = ""


# ---------------------------------------------------------------------------
# 学习任务
# ---------------------------------------------------------------------------

class SubmissionVerdict(BaseModel):
    is_submission: bool = False
    content: str = ""
    reason: str = ""


# ---------------------------------------------------------------------------
# 结果验收
# ---------------------------------------------------------------------------

class EvaluationResult(BaseModel):
    completion: str = "not_completed"
    mastery: float = 0.0
    error_types: list[str] = []
    next_action: str = "retry"
    feedback: str = ""
    reason: str = ""
    topic: str = ""
    day: int | None = None
    task: int | None = None

    @field_validator("completion", mode="before")
    @classmethod
    def _normalize_completion(cls, value):
        key = str(value or "").strip().lower()
        return COMPLETION_ALIASES.get(key, "not_completed")

    @field_validator("next_action", mode="before")
    @classmethod
    def _normalize_action_field(cls, value):
        key = str(value or "").strip().lower()
        return ACTION_ALIASES.get(key, "")

    @field_validator("error_types", mode="before")
    @classmethod
    def _normalize_errors(cls, value):
        return normalize_error_types(value)

    @field_validator("feedback", "reason", "topic", mode="before")
    @classmethod
    def _clean_text(cls, value):
        if isinstance(value, str):
            return value.strip()
        return "" if value is None else str(value)

    @field_validator("day", "task", mode="before")
    @classmethod
    def _to_int_or_none(cls, value):
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @model_validator(mode="after")
    def _apply_consistency(self):
        # 掌握度由完成度推导（确定性，不让模型自己给分）
        self.mastery = completion_score(self.completion)
        # 动作一致性：没做完不能通过
        self.next_action = normalize_action(self.completion, self.next_action)
        return self
