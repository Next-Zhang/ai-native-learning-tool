"""计划游标：每次只给一个任务（原 `daily.py` 的纯函数部分）。

游标模型：
    plan_progress = {"day": 1, "task": 1, "completed": ["1-1"], "finished": false}
    - 当天还有任务 -> task + 1
    - 当天任务都完成 -> 下一天 task = 1
    - 全部完成 -> finished = true

纯逻辑：不调 LLM、不落盘；`build_today_task` / `mark_task_done` 只写传入的 state dict。
"""

DEFAULT_PROGRESS = {"day": 1, "task": 1, "completed": [], "finished": False}


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
