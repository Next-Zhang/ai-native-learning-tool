"""学习计划用例（原 `planner.py` 的 LLM 部分）。

流程：
1. plan_horizon()      窗口天数 = min(7, 期望期限天数)（规则见 domain.plan_rules）
2. generate_plan()     按 目标/水平/每日时间/能力画像/薄弱点 生成结构化计划（LLM + JSON）
3. normalize_plan_data() 清洗（规则见 domain.plan_rules）
4. ensure_plan()       写入 state["current_plan"]
5. confirm_plan()      **用 LLM 判断用户是否确认**；确认后置 plan_confirmed=True

用户确认前，状态机守卫不允许进入 learning（先确认、后教学）。
"""

from datetime import date

from coach.domain.models import ConfirmationVerdict
from coach.domain.plan_rules import (
    fallback_plan,
    normalize_plan_data,
    plan_horizon,
)
from coach.llm import client
from coach.prompts.tasks import CONFIRM_SYSTEM_PROMPT, PLAN_SYSTEM_PROMPT

__all__ = [
    "confirm_plan",
    "describe_plan",
    "ensure_plan",
    "generate_plan",
    "is_confirmed",
]


def is_confirmed(state) -> bool:
    """计划是否已被用户确认。"""
    return bool(state.get("plan_confirmed"))


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
        data = client.json_call(PLAN_SYSTEM_PROMPT, user_content, label="plan_generate")
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


def confirm_plan(state, user_input: str) -> ConfirmationVerdict | None:
    """用 LLM 判断用户是否确认计划；确认则置 plan_confirmed=True。

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
        data = client.json_call(CONFIRM_SYSTEM_PROMPT, user_content, label="plan_confirm")
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
