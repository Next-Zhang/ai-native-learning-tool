"""学习计划的确定性规则（原 `planner.py` 的纯函数部分）。

关键设计：
- 窗口是"步长"不是"总时长"：目标是 3 个月，也每次只排最近 7 天（期限不足 7 天按实际天数）。
- 天数与结构清洗都在代码里完成，LLM 只负责"写内容"。
"""

import re

from coach.domain.models import PlanTask

# 参数
DEFAULT_HORIZON_DAYS = 7
MAX_HORIZON_DAYS = 7
MIN_HORIZON_DAYS = 1
MAX_TASKS_PER_DAY = 3

# 中文数字（含"两""半"）
_CN_DIGITS = {
    "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "半": 0.5,
}


def parse_target_days(text) -> int | None:
    """把用户的期限描述解析成天数；无法解析返回 None。

    支持："1个月"→30、"一个月"→30、"2周"→14、"两周"→14、"10天"→10、
         "半年"→182、"半个月"→15、"一年"→365。
    "年底""尽快"这类模糊表达返回 None（由调用方走默认值）。
    """
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return max(1, int(round(float(text))))

    raw = str(text).strip()
    if not raw:
        return None

    number = re.search(r"(\d+(?:\.\d+)?)", raw)
    if number:
        value = float(number.group(1))
    else:
        chinese = re.search(r"([一二两三四五六七八九十半])", raw)
        if not chinese:
            return None
        value = _CN_DIGITS[chinese.group(1)]

    if "年" in raw:
        days = value * 365
    elif "个月" in raw or "月" in raw:
        days = value * 30
    elif "周" in raw or "星期" in raw or "礼拜" in raw:
        days = value * 7
    elif "天" in raw or "日" in raw:
        days = value
    else:
        return None                      # 只有数字没有单位，无法判断

    return max(1, int(round(days)))


def plan_horizon(state) -> int:
    """本轮计划窗口天数：min(7, 期望期限)；解析不出则默认 7 天。"""
    days = parse_target_days(state.get("target_date"))
    if days is None:
        return DEFAULT_HORIZON_DAYS
    return max(MIN_HORIZON_DAYS, min(MAX_HORIZON_DAYS, days))


def _placeholder_day(day_no: int, daily_minutes) -> dict:
    """补齐窗口用的确定性占位日（模型给的天数不足时）。"""
    minutes = int(daily_minutes) if daily_minutes else 30
    return {
        "day": day_no,
        "theme": "复习与巩固",
        "tasks": [
            {
                "goal": "复习并巩固前面所学",
                "material": "已学教程章节与自己写的代码",
                "exercise": "重做关键练习，并用自己的话复述要点",
                "minutes": minutes,
                "done_criteria": "能不看资料复述要点并独立完成练习",
            }
        ],
    }


def fallback_plan(horizon: int, goal: str = "", weak_points=None, daily_minutes=None) -> list[dict]:
    """模型不可用时的确定性兜底计划：优先围绕薄弱点安排。"""
    topics = [t for t in (weak_points or []) if t] or [f"{goal or '基础内容'}"]
    minutes = int(daily_minutes) if daily_minutes else 30
    days: list[dict] = []
    for index in range(horizon):
        topic = topics[index % len(topics)]
        days.append(
            {
                "day": index + 1,
                "theme": f"{topic} 强化",
                "tasks": [
                    {
                        "goal": f"掌握：{topic}",
                        "material": "runoob 教程对应章节",
                        "exercise": f"完成 {topic} 的 2~3 个练习",
                        "minutes": minutes,
                        "done_criteria": f"能独立解释并用代码演示 {topic}",
                    }
                ],
            }
        )
    return days


def normalize_plan_data(data, horizon: int, goal: str = "",
                        weak_points=None, daily_minutes=None) -> list[dict]:
    """清洗 LLM 产出的计划：对齐天数、重编号、限制任务数、丢弃空任务。"""
    raw_days = data.get("days") if isinstance(data, dict) else None

    days: list[dict] = []
    for item in raw_days or []:
        if not isinstance(item, dict):
            continue
        theme = str(item.get("theme") or "").strip()

        tasks: list[dict] = []
        for raw_task in item.get("tasks") or []:
            if not isinstance(raw_task, dict):
                continue
            task = PlanTask.model_validate(raw_task)
            if not any([task.goal, task.material, task.exercise, task.done_criteria]):
                continue                      # 全空任务丢弃
            tasks.append(task.model_dump())
            if len(tasks) >= MAX_TASKS_PER_DAY:
                break

        days.append({"theme": theme or f"第 {len(days) + 1} 天", "tasks": tasks})
        if len(days) >= horizon:
            break

    # 模型没给出任何可用的一天（或有天数但全无任务）-> 整体兜底，优先围绕薄弱点
    if not days or not any(day["tasks"] for day in days):
        return fallback_plan(horizon, goal=goal, weak_points=weak_points,
                             daily_minutes=daily_minutes)

    # 天数不足：用确定的占位日补齐（保证窗口天数真的排满）
    while len(days) < horizon:
        days.append(_placeholder_day(len(days) + 1, daily_minutes))

    for index, day in enumerate(days, start=1):
        day["day"] = index
    return days
