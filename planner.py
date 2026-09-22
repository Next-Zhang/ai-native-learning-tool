"""planner.py —— V0.3c 学习计划（7 天滚动窗口）。

流程：
1. plan_horizon()      窗口天数 = min(7, 期望期限天数)；期限解析不出则默认 7 天
2. generate_plan()     按 目标/水平/每日时间/能力画像/薄弱点 生成结构化计划（LLM + JSON）
3. normalize_plan_data() 清洗：对齐天数、重编号、限制每天任务数、丢空任务、失败兜底
4. ensure_plan()       写入 state["current_plan"] = {horizon_days, start_date, days, version}
5. confirm_plan()      **B2：用 LLM 判断用户是否确认计划**；确认后置 plan_confirmed=True

关键设计：
- 窗口是"步长"不是"总时长"：目标是 3 个月，也每次只排最近 7 天（期限不足 7 天按实际天数）
- 天数与结构清洗都在代码里完成，LLM 只负责"写内容"
- 用户确认前，状态机守卫不允许进入 learning（先确认、后教学）
"""

import json
import re
from datetime import date

from pydantic import BaseModel, field_validator

# ---------------------------------------------------------------------------
# 参数
# ---------------------------------------------------------------------------

DEFAULT_HORIZON_DAYS = 7
MAX_HORIZON_DAYS = 7
MIN_HORIZON_DAYS = 1
MAX_TASKS_PER_DAY = 3

# 中文数字（含"两""半"）
_CN_DIGITS = {
    "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "半": 0.5,
}


# ---------------------------------------------------------------------------
# 数据结构
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
# 纯函数：期限解析 / 窗口天数
# ---------------------------------------------------------------------------

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


def is_confirmed(state) -> bool:
    """计划是否已被用户确认。"""
    return bool(state.get("plan_confirmed"))


# ---------------------------------------------------------------------------
# 纯函数：计划清洗与兜底
# ---------------------------------------------------------------------------

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


def describe_plan(state, max_days: int = 7) -> str:
    """把计划压缩成可注入对话的摘要，让教练照着呈现而不是另编一份。"""
    plan = state.get("current_plan") or {}
    days = plan.get("days") or []
    if not days:
        return ""
    lines = [
        f"- 计划窗口：{plan.get('horizon_days', len(days))} 天"
        f"（起始 {plan.get('start_date', '')}）"
    ]
    for day in days[:max_days]:
        theme = day.get("theme", "")
        tasks = day.get("tasks") or []
        first_goal = tasks[0].get("goal", "") if tasks else ""
        lines.append(f"- 第{day.get('day')}天：{theme}｜{len(tasks)} 个任务"
                     + (f"（首个任务：{first_goal}）" if first_goal else ""))
    if not is_confirmed(state):
        lines.append("- 用户尚未确认该计划：请先把计划讲清楚并请用户确认，不要直接开始教学")
    else:
        lines.append("- 用户已确认计划，可以开始执行")
    return "\n".join(lines)


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


PLAN_SYSTEM_PROMPT = """
你是学习计划设计者。请为用户生成一份**滚动学习计划**（只规划给定天数，不要规划整个目标周期）。

只输出 JSON：
{"days":[{"theme":"当天主题","tasks":[
  {"goal":"目标","material":"材料","exercise":"练习","minutes":30,"done_criteria":"完成标准"}]}]}

规则：
- 只输出指定的天数，从第 1 天开始连续排。
- 每天 1~3 个任务；每个任务必须写清 goal / material / exercise / minutes / done_criteria。
- 单个任务的 minutes 不超过用户的每日可投入时间；当天任务合计不要明显超出。
- 由易到难，优先覆盖**薄弱点**与能力画像中得分低的知识点。
- 任务要具体可执行、可验收（"能独立写出…"），不要写"了解/熟悉一下"这类空话。
- 只输出 JSON，不要解释。
""".strip()

CONFIRM_SYSTEM_PROMPT = """
你在判断用户是否**确认了这份学习计划、准备开始执行**。

只输出 JSON：{"confirmed":true 或 false,"reason":"一句话理由"}

判定标准：
- confirmed=true：用户明确同意开始（如"可以""没问题""就这样""开始吧""按这个来"）。
- confirmed=false：用户在提问、要求修改计划、表示犹豫、或聊了别的事情。
- 只有明确同意才算 true；含糊、反问、质疑一律 false。
- 只输出 JSON，不要解释。
""".strip()


# ---------------------------------------------------------------------------
# 对外流程函数
# ---------------------------------------------------------------------------

def generate_plan(state) -> list[dict]:
    """生成并清洗计划天列表（不写入 state）。"""
    horizon = plan_horizon(state)
    goal = state.get("learning_goal") or "Python"
    level = state.get("current_level") or "未知"
    minutes = state.get("daily_minutes")
    deadline = state.get("target_date")
    weak = [t for t in (state.get("weak_points") or []) if t]
    profile = state.get("skill_profile") or {}

    user_content = (
        f"学习目标：{goal}\n当前水平：{level}\n每天可投入：{minutes} 分钟\n"
        f"期望期限：{deadline}\n能力画像：{profile}\n薄弱点：{weak}\n"
        f"请只规划连续 {horizon} 天。"
    )

    try:
        data = _json_call(PLAN_SYSTEM_PROMPT, user_content)
        return normalize_plan_data(data, horizon, goal=goal, weak_points=weak,
                                   daily_minutes=minutes)
    except Exception as exc:                  # noqa: BLE001 —— 出计划失败必须有兜底
        print(f"[计划生成失败，已使用兜底计划] {type(exc).__name__}: {exc}")
        return fallback_plan(horizon, goal=goal, weak_points=weak, daily_minutes=minutes)


def ensure_plan(state) -> bool:
    """还没有计划就生成一份写入 state。返回是否新生成。"""
    if state.get("current_plan"):
        return False

    horizon = plan_horizon(state)
    days = generate_plan(state)

    state["current_plan"] = {
        "horizon_days": horizon,
        "start_date": date.today().isoformat(),
        "days": days,
        "version": 1,
    }
    state["plan_confirmed"] = False          # 新计划需要重新确认
    return True


def confirm_plan(state, user_input: str) -> ConfirmationVerdict | None:
    """B2：用 LLM 判断用户是否确认计划；确认则置 plan_confirmed=True。

    返回判定结果；判定失败（无 Key / 网络异常）返回 None，并**保持等待状态**。
    """
    plan = state.get("current_plan") or {}
    if not plan:
        return None

    summary = describe_plan(state)
    user_content = (
        f"【当前计划摘要】\n{summary}\n\n"
        f"【用户刚才说的话】\n{user_input}\n\n"
        f"请判断用户是否在确认这份计划、准备开始执行。"
    )

    try:
        data = _json_call(CONFIRM_SYSTEM_PROMPT, user_content)
        verdict = ConfirmationVerdict(
            confirmed=bool(data.get("confirmed")),
            reason=str(data.get("reason") or ""),
        )
    except Exception as exc:                  # noqa: BLE001 —— 判定失败就继续等待
        print(f"[计划确认判定失败，保持等待] {type(exc).__name__}: {exc}")
        return None

    if verdict.confirmed:
        state["plan_confirmed"] = True
    return verdict
