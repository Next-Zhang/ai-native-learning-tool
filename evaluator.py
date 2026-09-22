"""evaluator.py —— V0.3e 结果验收与画像更新。

流程：
1. evaluate()      把「今日任务 + 完成标准 + 用户提交」交给 LLM，产出结构化判定
2. 完成度三档       completed / partial / not_completed -> 掌握度 1.0 / 0.5 / 0.0（代码映射）
3. 一致性守卫       pass 只在 completed 时允许；partial -> supplement；not_completed -> retry
4. apply_update()  **代码侧**更新画像（新旧平均）与薄弱点，并决定"推进游标 / 重做当前任务"

设计要点：
- 判定结果写 state["latest_result"]；应用后置 latest_result_applied=True（守卫据此放行回 learning）
- 画像更新规则与测评阶段一致：薄弱点复用 assessor.derive_weak_points（阈值 < 0.6）
- 判定失败（无 Key／网络异常）返回 None，保持 evaluation 状态，绝不误推进
"""

import json

from pydantic import BaseModel, field_validator, model_validator

from assessor import derive_weak_points
from daily import get_progress, mark_task_done

# ---------------------------------------------------------------------------
# 映射与别名
# ---------------------------------------------------------------------------

COMPLETION_SCORES = {
    "completed": 1.0,
    "partial": 0.5,
    "not_completed": 0.0,
}

COMPLETION_ALIASES = {
    "completed": "completed", "完成": "completed", "已完成": "completed",
    "done": "completed", "通过": "completed",
    "partial": "partial", "部分完成": "partial", "部分": "partial",
    "partially": "partial", "不完整": "partial",
    "not_completed": "not_completed", "未完成": "not_completed",
    "没完成": "not_completed", "失败": "not_completed", "incomplete": "not_completed",
}

ACTION_ALIASES = {
    "pass": "pass", "通过": "pass", "通过验收": "pass", "approved": "pass",
    "retry": "retry", "重试": "retry", "重做": "retry", "redo": "retry",
    "supplement": "supplement", "补充": "supplement", "补充学习": "supplement",
    "补课": "supplement", "remedial": "supplement",
}

# 完成度 -> 缺省动作（模型没给或给了非法值时使用）
DEFAULT_ACTIONS = {
    "completed": "pass",
    "partial": "supplement",
    "not_completed": "retry",
}


def completion_score(completion: str) -> float:
    """完成度 -> 掌握度分数。"""
    return COMPLETION_SCORES.get(completion, 0.0)


def normalize_action(completion: str, action: str) -> str:
    """动作一致性守卫：不允许"没做完却通过"。"""
    if action == "pass" and completion != "completed":
        # 部分完成 -> 补充学习后再试；未完成 -> 重做
        return "supplement" if completion == "partial" else "retry"
    if action not in DEFAULT_ACTIONS.values():
        return DEFAULT_ACTIONS.get(completion, "retry")
    return action


def normalize_error_types(value) -> list[str]:
    """错误类型归一：字符串 / 列表 / None 都能处理。"""
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        return []
    return [str(item).strip() for item in items if str(item).strip()]


# ---------------------------------------------------------------------------
# 判定结果
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


# ---------------------------------------------------------------------------
# LLM 调用
# ---------------------------------------------------------------------------

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

        _client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    return _client


def _json_call(system_prompt: str, user_content: str) -> dict:
    response = _get_client().chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(response.choices[0].message.content or "{}")


JUDGE_SYSTEM_PROMPT = """
你是严格的学习结果验收员。根据【今日任务】【完成标准】和【用户提交的内容】给出判定。

只输出 JSON：
{"completion":"completed|partial|not_completed",
 "error_types":["错误类型标签"],
 "next_action":"pass|retry|supplement",
 "feedback":"给用户的一句话反馈",
 "reason":"判定理由"}

判定标准：
- completed：完全达成完成标准，答案/代码正确且完整。
- partial：部分达成，有小错、缺步骤或边界情况未处理。
- not_completed：未达成：答案错误、答非所问、或没有实际产出。
- error_types 用简短标签，如"概念混淆""语法错误""边界情况遗漏""格式错误"；没有错误就输出 []。
- next_action 与完成度保持一致：completed -> pass；partial -> supplement；not_completed -> retry。
- 用户只说"我会了/做好了"但没有实际产出时，按 not_completed 处理。
- 只输出 JSON，不要解释。
""".strip()


# ---------------------------------------------------------------------------
# 对外流程函数
# ---------------------------------------------------------------------------

def evaluate(state) -> EvaluationResult | None:
    """对 pending_submission 做结构化判定；成功则写入 latest_result。"""
    task = state.get("today_task") or {}
    submission = state.get("pending_submission") or {}
    if not task or not submission.get("content"):
        return None

    user_content = (
        f"【今日任务】{task.get('goal', '')}\n"
        f"【练习要求】{task.get('exercise', '')}\n"
        f"【完成标准】{task.get('done_criteria', '')}\n"
        f"【预计时间】{task.get('minutes', 0)} 分钟\n\n"
        f"【用户提交的内容】\n{submission.get('content', '')}\n\n"
        f"请判定这次学习结果。"
    )

    try:
        data = _json_call(JUDGE_SYSTEM_PROMPT, user_content)
    except Exception as exc:                  # noqa: BLE001 —— 判定失败保持 evaluation
        print(f"[验收判定失败，保持在结果验收] {type(exc).__name__}: {exc}")
        return None

    result = EvaluationResult(
        topic=task.get("theme") or task.get("goal") or "",
        day=task.get("day"),
        task=task.get("task"),
        **data,
    )
    state["latest_result"] = result.model_dump()
    state["latest_result_applied"] = False
    return result


def apply_update(state) -> dict:
    """把验收结论应用到画像，并决定推进游标还是重做当前任务（纯代码）。"""
    result = state.get("latest_result") or {}
    topic = str(result.get("topic") or "").strip()
    score = float(result.get("mastery") or 0.0)
    action = str(result.get("next_action") or "retry")

    # 1) 更新能力画像：已有知识点取新旧平均（平滑），新知识点直接写入
    profile = dict(state.get("skill_profile") or {})
    if topic:
        if topic in profile:
            try:
                old_score = float(profile[topic])
                profile[topic] = round((old_score + score) / 2, 2)
            except (TypeError, ValueError):
                profile[topic] = round(score, 2)
        else:
            profile[topic] = round(score, 2)
    state["skill_profile"] = profile

    # 2) 薄弱点：与测评阶段同一套阈值规则
    state["weak_points"] = derive_weak_points(profile)

    # 3) 通过 -> 推进游标（下一个任务）；未通过 -> 保留当前任务让用户重做
    if action == "pass":
        progress = mark_task_done(state)          # 内部会清空 today_task 与 pending_submission
    else:
        state["pending_submission"] = None        # 清空提交，保留 today_task
        progress = get_progress(state)

    state["latest_result_applied"] = True
    return {
        "action": action,
        "topic": topic,
        "score": score,
        "skill_profile": profile,
        "weak_points": state["weak_points"],
        "progress": progress,
    }


def describe_result(state) -> str:
    """把最近一次验收结论压成可注入对话的文本。"""
    result = state.get("latest_result") or {}
    if not result:
        return ""
    lines = [
        f"- 本次验收判定：完成度={result.get('completion')}"
        f"｜掌握度={result.get('mastery')}｜下一步={result.get('next_action')}",
        f"- 错误类型：{'、'.join(result.get('error_types') or []) or '（无）'}",
    ]
    if result.get("feedback"):
        lines.append(f"- 给用户的反馈：{result['feedback']}")
    if result.get("reason"):
        lines.append(f"- 判定理由：{result['reason']}")
    lines.append("- 请按上述判定与用户沟通：通过则确认并进入下一任务；未通过则说明问题并让用户重做")
    return "\n".join(lines)
