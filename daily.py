"""daily.py —— V0.3d 每日任务（today_task）。

流程：
1. build_today_task()    按计划游标 (day, task) 取出**一个**任务写入 state["today_task"]
2. describe_today_task() 把任务压成可注入对话的文本（教练照实呈现，不另编）
3. detect_submission()   用 LLM 判断用户这句话是否提交了可验收的结果
4. 提交后写入 state["pending_submission"]，守卫随即放行到 evaluation（V0.3e 验收）
5. mark_task_done()      验收通过后推进游标（V0.3e 调用）

游标模型（每次只给一个任务）：
    plan_progress = {"day": 1, "task": 1, "completed": ["1-1"], "finished": false}
    - 当天还有任务 -> task + 1
    - 当天任务都完成 -> 下一天 task = 1
    - 全部完成 -> finished = true

安全策略：提交判定失败（无 Key／网络异常）时返回 None，**保持 learning 继续对话**，
绝不把普通提问误当成提交。
"""

import json

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

class SubmissionVerdict(BaseModel):
    is_submission: bool = False
    content: str = ""
    reason: str = ""


DEFAULT_PROGRESS = {"day": 1, "task": 1, "completed": [], "finished": False}


# ---------------------------------------------------------------------------
# 纯函数：游标与任务查找
# ---------------------------------------------------------------------------

def get_progress(state) -> dict:
    """取计划游标（缺失字段用默认值补齐），不修改 state。"""
    progress = dict(DEFAULT_PROGRESS)
    stored = state.get("plan_progress") or {}
    if isinstance(stored, dict):
        progress.update({k: v for k, v in stored.items() if k in DEFAULT_PROGRESS})
    if not isinstance(progress.get("completed"), list):
        progress["completed"] = []
    return progress


def lookup_task(plan, day: int, task: int) -> dict | None:
    """从计划里取出「第 day 天第 task 个」任务，合并为可直接使用的结构。"""
    days = (plan or {}).get("days") or []
    if day < 1 or day > len(days):
        return None
    day_item = days[day - 1]
    tasks = day_item.get("tasks") or []
    if task < 1 or task > len(tasks):
        return None
    item = tasks[task - 1] or {}
    return {
        "day": day,
        "task": task,
        "theme": day_item.get("theme", ""),
        "goal": item.get("goal", ""),
        "material": item.get("material", ""),
        "exercise": item.get("exercise", ""),
        "minutes": item.get("minutes", 0),
        "done_criteria": item.get("done_criteria", ""),
    }


def next_position(plan, day: int, task: int) -> tuple[int, int] | None:
    """下一个位置；计划已排完返回 None。"""
    days = (plan or {}).get("days") or []
    if day < 1 or day > len(days):
        return None
    tasks = days[day - 1].get("tasks") or []
    if task < len(tasks):
        return (day, task + 1)
    if day < len(days):
        return (day + 1, 1)
    return None


def first_valid_position(plan, day: int, task: int) -> tuple[int, int] | None:
    """从 (day, task) 起找到第一个真的有任务的位置（跳过空白天）。"""
    position = (day, task)
    while position is not None:
        if lookup_task(plan, *position):
            return position
        position = next_position(plan, *position)
    return None


def is_plan_finished(state) -> bool:
    """计划是否已全部完成。"""
    if get_progress(state).get("finished"):
        return True
    plan = state.get("current_plan") or {}
    if not (plan.get("days")):
        return False
    progress = get_progress(state)
    return first_valid_position(plan, progress["day"], progress["task"]) is None


def is_day_complete(state, day: int) -> bool:
    """该天的任务是否都已完成。"""
    progress = get_progress(state)
    done = {int(key.split("-")[0]) for key in progress.get("completed", [])
            if isinstance(key, str) and "-" in key and key.split("-")[0].isdigit()}
    return day in done


# ---------------------------------------------------------------------------
# 任务构建与推进
# ---------------------------------------------------------------------------

def build_today_task(state) -> dict | None:
    """按游标取出一个任务写入 state["today_task"]；计划已排完返回 None。"""
    plan = state.get("current_plan") or {}
    progress = get_progress(state)

    if not plan.get("days"):
        return None

    # 计划已排完：不要再把最后一个任务重复发一次
    if progress.get("finished"):
        state["plan_progress"] = progress
        state["today_task"] = None
        return None

    position = first_valid_position(plan, progress["day"], progress["task"])
    if position is None:
        progress["finished"] = True
        state["plan_progress"] = progress
        state["today_task"] = None
        return None

    task = lookup_task(plan, *position)
    progress["day"], progress["task"] = position
    progress["finished"] = False
    state["plan_progress"] = progress
    state["today_task"] = task
    return task


def mark_task_done(state) -> dict:
    """把当前任务记为已完成并推进游标（V0.3e 验收通过后调用）。

    同时清空 today_task 与 pending_submission，准备下一个任务。
    """
    plan = state.get("current_plan") or {}
    progress = get_progress(state)

    key = f"{progress['day']}-{progress['task']}"
    completed = list(progress.get("completed") or [])
    if key not in completed:
        completed.append(key)

    nxt = next_position(plan, progress["day"], progress["task"])
    progress["completed"] = completed
    progress["finished"] = nxt is None
    if nxt is not None:
        progress["day"], progress["task"] = nxt

    state["plan_progress"] = progress
    state["today_task"] = None
    state["pending_submission"] = None
    return progress


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


# ---------------------------------------------------------------------------
# 提交识别（LLM）
# ---------------------------------------------------------------------------

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

        _client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    return _client


SUBMISSION_SYSTEM_PROMPT = """
你在判断用户是否**提交了可验收的学习结果**。

只输出 JSON：{"is_submission":true 或 false,"content":"用户提交内容的要点或代码摘录","reason":"一句话理由"}

判定标准：
- true：用户给出了自己的答案、代码、运行结果、作业说明等可检验的产出。
- false：用户在提问、要提示、闲聊、表示还没开始、或只是在确认要求。
- 只有真的给出产出才算 true；"我在做了""快好了""这样对吗（没给内容）"一律 false。
- content 要保留用户提交的关键内容（代码可原样摘录），便于后续验收。
- 只输出 JSON，不要解释。
""".strip()


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
        data = _json_call(SUBMISSION_SYSTEM_PROMPT, user_content)
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
