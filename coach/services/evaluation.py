"""结果验收与画像更新用例（原 `evaluator.py` 的 LLM 与编排部分）。

流程：
1. evaluate()      把「今日任务 + 完成标准 + 用户提交」交给 LLM，产出结构化判定
2. 一致性守卫      由 `domain.models.EvaluationResult` 强制（掌握度由完成度推导；未完成不许 pass）
3. apply_update()  **代码侧**更新画像（新旧平均）与薄弱点，并决定"推进游标 / 重做当前任务"

判定失败（无 Key／网络异常／返回结构非法）返回 None，保持 evaluation 状态，绝不误推进。
"""

from coach.domain.assessment_rules import derive_weak_points
from coach.domain.cursor import get_progress, mark_task_done
from coach.domain.models import EvaluationResult
from coach.llm import client
from coach.prompts.tasks import EVALUATION_JUDGE_SYSTEM_PROMPT

__all__ = [
    "apply_update",
    "describe_result",
    "evaluate",
]


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
        data = client.json_call(
            EVALUATION_JUDGE_SYSTEM_PROMPT, user_content, label="evaluation_judge"
        )
        # JSON 模式仍可能返回非对象（数组 / 字符串）—— 必须在守卫内归一，
        # 否则下面的 `**data` 会抛 TypeError 并跳出兜底。
        if not isinstance(data, dict):
            raise TypeError(f"判定结果不是 JSON 对象：{type(data).__name__}")
        # topic / day / task 由代码从 today_task 填；模型若重复给出这几个键，
        # 直接 `**data` 会因"关键字重复"抛 TypeError，故先剔除。
        payload = {k: v for k, v in data.items() if k not in ("topic", "day", "task")}
        result = EvaluationResult(
            topic=task.get("theme") or task.get("goal") or "",
            day=task.get("day"),
            task=task.get("task"),
            **payload,
        )
    except Exception as exc:                  # noqa: BLE001 —— 判定失败保持 evaluation
        print(f"[验收判定失败，保持在结果验收] {type(exc).__name__}: {exc}")
        return None

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

    # 4) 记账本次验收**尝试**（含重做）。这是"滚动=重估"唯一的速度信号：
    #    `completed` 按 key 去重，看不出重做；`attempts` 会随重做增长。
    progress["attempts"] = int(progress.get("attempts") or 0) + 1
    state["plan_progress"] = progress

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
