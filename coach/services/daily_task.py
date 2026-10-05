"""每日任务用例（原 `daily.py` 的 LLM 与展示部分）。

游标与任务查找等纯逻辑在 `coach.domain.cursor`；本模块只负责：
1. describe_today_task()  把任务压成可注入对话的文本（教练照实呈现，不另编）
2. describe_progress()    一行进度摘要，用于终端展示
3. detect_submission()    用 LLM 判断用户这句话是否提交了可验收的结果

安全策略：提交判定失败（无 Key／网络异常）时返回 None，**保持 learning 继续对话**，
绝不把普通提问误当成提交。
"""

from coach.domain.cursor import get_progress
from coach.domain.models import SubmissionVerdict
from coach.llm import client
from coach.prompts.tasks import SUBMISSION_SYSTEM_PROMPT

__all__ = [
    "describe_progress",
    "describe_today_task",
    "detect_submission",
]


def describe_today_task(state) -> str:
    """把今日任务压成可注入对话的文本。"""
    task = state.get("today_task") or {}
    if not task:
        return ""
    progress = get_progress(state)
    total_done = len(progress.get("completed") or [])
    lines = [
        f"- 今日任务：第 {task.get('day')} 天 · 第 {task.get('task')} 个"
        f"（主题：{task.get('theme', '')}；已完成 {total_done} 个任务）",
        f"- 目标：{task.get('goal', '')}",
    ]
    if task.get("material"):
        lines.append(f"- 材料：{task['material']}")
    if task.get("exercise"):
        lines.append(f"- 练习：{task['exercise']}")
    if task.get("minutes"):
        lines.append(f"- 预计时间：{task['minutes']} 分钟")
    if task.get("done_criteria"):
        lines.append(f"- 完成标准：{task['done_criteria']}")
    lines.append("- 只围绕这一个任务讲解与引导；用户完成后请其提交结果，不要提前布置后面的任务")
    return "\n".join(lines)


def describe_progress(state) -> str:
    """一行进度摘要，用于终端展示。"""
    progress = get_progress(state)
    if progress.get("finished"):
        return "计划已全部完成"
    total = len((state.get("current_plan") or {}).get("days") or [])
    return (f"第 {progress['day']}/{total or '?'} 天 · "
            f"第 {progress['task']} 个任务（已完成 {len(progress.get('completed') or [])} 个）")


def detect_submission(state, user_input: str) -> SubmissionVerdict | None:
    """判断用户是否提交了结果；是则写入 state["pending_submission"]。

    失败（无 Key／网络异常）返回 None，并保持 learning 状态。
    """
    task = state.get("today_task") or {}
    if not task:
        return None

    if state.get("pending_submission"):
        return None                      # 已经有一个待验收提交，不重复覆盖

    user_content = (
        f"【今日任务】{task.get('goal', '')}\n"
        f"【练习要求】{task.get('exercise', '')}\n"
        f"【完成标准】{task.get('done_criteria', '')}\n\n"
        f"【用户刚才说的话】\n{user_input}\n\n"
        f"请判断用户是否提交了可验收的学习结果。"
    )

    try:
        data = client.json_call(SUBMISSION_SYSTEM_PROMPT, user_content)
        verdict = SubmissionVerdict(
            is_submission=bool(data.get("is_submission")),
            content=str(data.get("content") or ""),
            reason=str(data.get("reason") or ""),
        )
    except Exception as exc:                  # noqa: BLE001 —— 判定失败就继续对话
        print(f"[提交判定失败，保持学习中] {type(exc).__name__}: {exc}")
        return None

    if verdict.is_submission:
        state["pending_submission"] = {
            "content": verdict.content or user_input,
            "reason": verdict.reason,
            "day": task.get("day"),
            "task": task.get("task"),
        }
    return verdict
