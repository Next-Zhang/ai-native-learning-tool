"""学习计划的确定性规则（原 `planner.py` 的纯函数部分）。

双层结构（见 `docs/architecture.md` §11）
----------------------------------------
- **路线图 `roadmap`**：目标 → **里程碑**，**不滚动**；只有里程碑达成或目标变更才更新。
- **执行窗口 `current_window`**：可执行单元列表，**滚动**；窗口长度 = 当前里程碑的
  `sessions_est`（所以**不固定 3/7 天**）。

**单位是"次"不是"天"**：碎片化用户可能一天学 3 次、也可能 3 天学 1 次。
`plan_unit()` 按单次时长决定单位 —— `>= 45 分钟`视为"整块时间"，切回 `day`，
这样**旧的 7 天窗口模型仍然可用**（旧资产不废弃）。

其他关键设计：
- 结构与清洗都在代码里完成，LLM 只负责"写内容"。
- **任务粒度由代码强制**：单任务时长 ≤ 单次可投入时长（`session_minutes`）。
"""

import re

from coach.domain.models import PlanTask

# 参数
MAX_TASKS_PER_DAY = 3

#: 模型没给任务时长时的兜底（分钟）
DEFAULT_TASK_MINUTES = 30
#: 单任务时长的下限（避免被压成 0 或负数）
MIN_TASK_MINUTES = 5

# --- 计划单位 ---------------------------------------------------------------
UNIT_SESSION = "session"      # 碎片化（默认）：一个执行单元 = 一次坐下来
UNIT_DAY = "day"              # 整块时间：一个执行单元 = 一天

#: 单次时长达到此值即视为"整块时间"，单位切回 `day`
UNIT_DAY_THRESHOLD_MINUTES = 45

# --- 窗口长度 ---------------------------------------------------------------
DEFAULT_WINDOW_LENGTH = 3
MIN_WINDOW_LENGTH = 1
MAX_WINDOW_LENGTH = 7

# --- 里程碑状态 -------------------------------------------------------------
MILESTONE_PENDING = "pending"
MILESTONE_IN_PROGRESS = "in_progress"
MILESTONE_DONE = "done"

#: 兜底路线图切几个里程碑（**确定性兜底**用）
DEFAULT_MILESTONE_COUNT = 3

#: 模型产出的里程碑**上限**，与 `ROADMAP_SYSTEM_PROMPT` 的"3~5 个"对齐。
#: **与 `DEFAULT_MILESTONE_COUNT` 语义不同**：后者是"兜底时切几个"。
#: 若拿它当产出上限，提示词要的第 4、5 个会被静默裁掉。
MAX_MILESTONE_COUNT = 5

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


def plan_unit(state) -> str:
    """计划单位：`session`（碎片化，默认）或 `day`（整块时间）。

    `session_minutes >= UNIT_DAY_THRESHOLD_MINUTES` 视为整块时间 ——
    这样旧的 7 天窗口模型仍然可用（**旧资产不废弃**）。
    """
    try:
        minutes = int(state.get("session_minutes") or 0)
    except (TypeError, ValueError):
        minutes = 0
    return UNIT_DAY if minutes >= UNIT_DAY_THRESHOLD_MINUTES else UNIT_SESSION


# ---------------------------------------------------------------------------
# 路线图（长期，不滚动）
# ---------------------------------------------------------------------------

def _to_estimate(value) -> int:
    """把 `sessions_est` 归一成 [MIN_WINDOW_LENGTH, MAX_WINDOW_LENGTH] 内的整数。"""
    try:
        number = int(value) if value else DEFAULT_WINDOW_LENGTH
    except (TypeError, ValueError):
        number = DEFAULT_WINDOW_LENGTH
    return max(MIN_WINDOW_LENGTH, min(MAX_WINDOW_LENGTH, number))


def _roadmap_payload(state, milestones: list[dict], *, source: str = "generated") -> dict:
    """组装路线图结构，并把第一个里程碑置为进行中。"""
    for item in milestones:
        item["status"] = MILESTONE_PENDING
    if milestones:
        milestones[0]["status"] = MILESTONE_IN_PROGRESS
    return {
        "goal": state.get("learning_goal") or "",
        "unit": plan_unit(state),
        "milestones": milestones,
        "current_milestone": milestones[0]["id"] if milestones else None,
        # generated | fallback | user_provided（I-7：用户自带计划时 original 存原稿）
        "source": source,
        "original": None,
        "version": 1,
    }


def fallback_roadmap(state, count: int = DEFAULT_MILESTONE_COUNT) -> dict:
    """模型不可用时的**确定性**路线图：按薄弱点（没有则按目标）切分里程碑。"""
    goal = state.get("learning_goal") or "基础内容"
    topics = [t for t in (state.get("weak_points") or []) if t] or [goal]

    milestones: list[dict] = []
    for index in range(max(1, count)):
        topic = topics[index % len(topics)]
        milestones.append({
            "id": f"M{index + 1}",
            "title": f"{topic} 强化",
            "topics": [topic],
            "sessions_est": DEFAULT_WINDOW_LENGTH,
            "status": MILESTONE_PENDING,
        })
    return _roadmap_payload(state, milestones, source="fallback")


def normalize_roadmap(data, state, *, count: int = DEFAULT_MILESTONE_COUNT) -> dict:
    """清洗 LLM 产出的路线图：限制数量、重编号、丢弃空里程碑、归一估计值。"""
    raw = data.get("milestones") if isinstance(data, dict) else None

    milestones: list[dict] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        topics = [str(t).strip() for t in (item.get("topics") or []) if str(t).strip()]
        if not title and not topics:
            continue                                  # 全空里程碑丢弃
        milestones.append({
            "id": f"M{len(milestones) + 1}",
            "title": title or (topics[0] if topics else f"阶段 {len(milestones) + 1}"),
            "topics": topics,
            "sessions_est": _to_estimate(item.get("sessions_est")),
            "status": MILESTONE_PENDING,
        })
        if len(milestones) >= count:
            break

    if not milestones:
        return fallback_roadmap(state, count=count)   # 一个可用里程碑都没有 -> 整体兜底
    return _roadmap_payload(state, milestones)


def current_milestone(state) -> dict | None:
    """路线图里**正在进行**的里程碑；没有路线图返回 None。"""
    roadmap = state.get("roadmap") or {}
    milestones = roadmap.get("milestones") or []
    if not milestones:
        return None

    target = roadmap.get("current_milestone")
    for item in milestones:
        if target and item.get("id") == target:
            return item
    for item in milestones:                            # 没标记就取第一个未完成的
        if item.get("status") != MILESTONE_DONE:
            return item
    return None


def advance_milestone(state) -> bool:
    """把当前里程碑标记为完成并切到下一个；**没有下一个则返回 False**。

    返回 False 表示"整张路线图已走完" —— 调用方据此决定是否提示用户重排目标。
    """
    roadmap = state.get("roadmap") or {}
    milestones = roadmap.get("milestones") or []
    current = current_milestone(state)
    if not current:
        return False

    current["status"] = MILESTONE_DONE
    for item in milestones:
        if item.get("status") != MILESTONE_DONE:
            item["status"] = MILESTONE_IN_PROGRESS
            roadmap["current_milestone"] = item["id"]
            return True
    roadmap["current_milestone"] = None
    return False


def window_length(state) -> int:
    """本执行窗口的长度（单位由 `plan_unit` 决定）。

    - **有路线图** → = 当前里程碑的 `sessions_est`（所以**不固定 3/7**）
    - **无路线图** → = min(3, 期望期限天数)；期限不足 3 天按实际
    """
    milestone = current_milestone(state)
    if milestone:
        return _to_estimate(milestone.get("sessions_est"))

    days = parse_target_days(state.get("target_date"))
    base = DEFAULT_WINDOW_LENGTH if days is None else min(DEFAULT_WINDOW_LENGTH, days)
    return max(MIN_WINDOW_LENGTH, min(MAX_WINDOW_LENGTH, base))


def clamp_task_minutes(minutes, session_minutes, *, default: int = DEFAULT_TASK_MINUTES) -> int:
    """把单任务时长**限制在单次可用时长之内**（代码强制，不靠模型自觉）。

    模型可以想要 60 分钟的任务，但用户只有 15 分钟 —— 超出的部分由代码砍掉，
    而不是让用户做不完。**这也是 I-10 的同类思路：约束由代码定，不由模型裁量。**
    """
    try:
        cap = int(session_minutes) if session_minutes else default
    except (TypeError, ValueError):
        # 与 `plan_unit()` 相同的容错：state 里的 session_minutes 可能是脏值
        # （手工改过的状态文件、"30分钟" 这类字符串），不能让它炸掉整条计划生成链路
        cap = default
    cap = max(MIN_TASK_MINUTES, cap)

    try:
        value = int(minutes) if minutes else cap
    except (TypeError, ValueError):
        value = cap
    if value <= 0:
        value = cap
    return min(value, cap)


def _placeholder_day(day_no: int, session_minutes) -> dict:
    """补齐窗口用的确定性占位日（模型给的天数不足时）。"""
    minutes = clamp_task_minutes(None, session_minutes)
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


def fallback_plan(horizon: int, goal: str = "", weak_points=None,
                  session_minutes=None) -> list[dict]:
    """模型不可用时的确定性兜底计划：优先围绕薄弱点安排。"""
    topics = [t for t in (weak_points or []) if t] or [f"{goal or '基础内容'}"]
    minutes = clamp_task_minutes(None, session_minutes)
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
                        weak_points=None, session_minutes=None) -> list[dict]:
    """清洗 LLM 产出的计划：对齐天数、重编号、限制任务数、丢弃空任务、**钳制任务时长**、
    **强制可检验标准**（v0.16）。
    """
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
            if not task.done_criteria:
                # **可检验标准是验收的锚点（PRD §2.3 硬约束）**：没有它，任务无法被验收，
                # 闭环即断。这里**丢弃该任务**而不是编一个假的完成标准；若因此整天无任务，
                # 下面的整体兜底会接管（兜底任务本身是带 done_criteria 的）。
                continue
            payload = task.model_dump()
            # **任务粒度约束（代码强制）**：不得超过单次可用时长
            payload["minutes"] = clamp_task_minutes(payload.get("minutes"), session_minutes)
            tasks.append(payload)
            if len(tasks) >= MAX_TASKS_PER_DAY:
                break

        days.append({"theme": theme or f"第 {len(days) + 1} 天", "tasks": tasks})
        if len(days) >= horizon:
            break

    # 模型没给出任何可用的一天（或有天数但全无任务）-> 整体兜底，优先围绕薄弱点
    if not days or not any(day["tasks"] for day in days):
        return fallback_plan(horizon, goal=goal, weak_points=weak_points,
                             session_minutes=session_minutes)

    # 天数不足：用确定的占位日补齐（保证窗口天数真的排满）
    while len(days) < horizon:
        days.append(_placeholder_day(len(days) + 1, session_minutes))

    for index, day in enumerate(days, start=1):
        day["day"] = index
    return days
