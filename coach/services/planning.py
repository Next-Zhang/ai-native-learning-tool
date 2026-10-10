"""学习计划用例（原 `planner.py` 的 LLM 部分）。

双层结构（见 `docs/architecture.md` §11）
----------------------------------------
1. `generate_roadmap()`  目标 → **里程碑**（长期，**不滚动**）；LLM + 清洗 + 确定性兜底
2. `ensure_window()`     当前里程碑 → **执行窗口**（短期，**滚动**）
3. `generate_plan()`     窗口内的具体任务内容（LLM + 清洗 + 兜底）
4. `ensure_plan()`       = 确保路线图 + 确保窗口（编排层只需调它）
5. `confirm_plan()`      **用 LLM 判断用户是否确认**；确认后置 `plan_confirmed=True`
6. `roll_window()`       窗口走完 → 进入下一里程碑，**并按实际速度重估后续估计**
   （⚠️ 已知缺陷：重估的分子/分母量纲不同且重做未被计数，见 `window_usage` 的说明）

用户确认前，状态机守卫不允许进入 learning（先确认、后教学）。
"""

from datetime import date

from coach.domain.cursor import fresh_progress, is_plan_finished
from coach.domain.memory import REVIEW_UNCOVERED_SESSIONS, derive_due_for_review
from coach.domain.models import ConfirmationVerdict
from coach.domain.profile import render_profile
from coach.domain.plan_rules import (
    DEFAULT_WINDOW_LENGTH,
    MAX_MILESTONE_COUNT,
    MAX_WINDOW_LENGTH,
    MILESTONE_DONE,
    MIN_WINDOW_LENGTH,
    UNIT_SESSION,
    advance_milestone,
    current_milestone,
    fallback_plan,
    fallback_roadmap,
    normalize_plan_data,
    normalize_roadmap,
    plan_unit,
    window_length,
)
from coach.llm import client
from coach.prompts.tasks import (
    CONFIRM_SYSTEM_PROMPT,
    PLAN_SYSTEM_PROMPT,
    ROADMAP_SYSTEM_PROMPT,
)
from coach.services import to_bool

__all__ = [
    "confirm_plan",
    "describe_plan",
    "ensure_plan",
    "ensure_window",
    "generate_plan",
    "generate_roadmap",
    "is_confirmed",
    "roll_window",
    "unit_label",
]


def is_confirmed(state) -> bool:
    """路线图是否已被用户确认（确认后其**所有**里程碑都视为已授权）。

    用 `to_bool` 而不是 `bool(...)`：该标志是状态机守卫
    （`_guard_plan_confirmed`）放行 teaching 的唯一依据，任何"假装真"的写法
    （如旧状态文件里的 `"false"` 字符串）都不该被当成已确认。
    """
    return to_bool(state.get("plan_confirmed"))


def unit_label(state) -> str:
    """给用户看的单位：碎片化 = "次"，整块时间 = "天"。"""
    return "次" if plan_unit(state) == UNIT_SESSION else "天"


def review_hint(state) -> str:
    """待复验知识点 → 提示词片段（没有待复验项时返回**空串**）。

    见 docs/memory-design.md §7：**标记待复验**是复习调度的最小内核 ——
    它不是独立阶段，而是"生成下一个计划块时优先安排"的一条排序规则。
    没有待复验项时返回空串，因此这个功能在**触发前对行为完全无影响**。
    """
    due = derive_due_for_review(state)
    if not due:
        return ""
    return (
        f"**待复验的知识点**（已连续 {REVIEW_UNCOVERED_SESSIONS} 次学习未覆盖，"
        f"请优先安排任务覆盖）：{'、'.join(due)}\n"
    )


# ---------------------------------------------------------------------------
# 1) 路线图（长期）
# ---------------------------------------------------------------------------

def generate_roadmap(state) -> dict:
    """生成路线图（不写入 state）。**失败一定有兜底**，绝不返回空。"""
    # 上下文走**统一渲染出口**：五个维度都会自动带上（含学习偏好），
    # 不再手工挑字段 —— 那样正是"漏维度"的来源（见 domain/profile.py）。
    user_content = (
        f"【学习者画像】\n{render_profile(state)}\n\n"
        f"请把目标拆解成 3~5 个里程碑（由易到难，覆盖整个目标）。"
    )

    try:
        data = client.json_call(ROADMAP_SYSTEM_PROMPT, user_content, label="roadmap_generate")
        # 上限用 `MAX_MILESTONE_COUNT`（=5），**不要**复用 `DEFAULT_MILESTONE_COUNT` ——
        # 后者的语义是"兜底时切几个"，用它会让提示词要的 3~5 个里第 4、5 个被静默裁掉。
        return normalize_roadmap(data, state, count=MAX_MILESTONE_COUNT)
    except Exception as exc:                  # noqa: BLE001 —— 出路线图失败必须有兜底
        print(f"[路线图生成失败，已使用兜底路线图] {type(exc).__name__}: {exc}")
        return fallback_roadmap(state)


# ---------------------------------------------------------------------------
# 2) 执行窗口（短期）
# ---------------------------------------------------------------------------

def generate_plan(state) -> list[dict]:
    """生成本窗口的可执行单元列表（不写入 state）。

    带上**当前里程碑**上下文，让任务内容围绕该里程碑的知识点，而不是泛泛而谈。
    """
    length = window_length(state)
    milestone = current_milestone(state) or {}
    minutes = state.get("session_minutes")          # **单次**可投入时长（任务粒度硬上限）
    weak = [t for t in (state.get("weak_points") or []) if t]
    goal = state.get("learning_goal") or ""
    unit = unit_label(state)

    # 同上：上下文统一走渲染出口
    user_content = (
        f"【学习者画像】\n{render_profile(state)}\n\n"
        f"**单次可投入 {minutes} 分钟是硬上限**：每个任务的 minutes 不得超过它。\n"
        f"{review_hint(state)}"
        f"**当前里程碑**：{milestone.get('title', '')}"
        f"（知识点：{'、'.join(milestone.get('topics') or []) or '未指定'}）\n"
        f"请只规划连续 {length} {unit}。"
    )

    try:
        data = client.json_call(PLAN_SYSTEM_PROMPT, user_content, label="plan_generate")
        return normalize_plan_data(data, length, goal=goal, weak_points=weak,
                                   session_minutes=minutes)
    except Exception as exc:                  # noqa: BLE001 —— 出计划失败必须有兜底
        print(f"[窗口生成失败，已使用兜底窗口] {type(exc).__name__}: {exc}")
        return fallback_plan(length, goal=goal, weak_points=weak, session_minutes=minutes)


def ensure_window(state, *, reset_confirmed: bool = True) -> bool:
    """没有执行窗口就按当前里程碑生成一个。返回是否新生成。

    `reset_confirmed=False` 用于**滚动**：用户已经确认过路线图，不必重复确认。
    """
    if state.get("current_window"):
        return False
    if not state.get("roadmap"):
        return False                          # 没有路线图就无从生成窗口

    milestone = current_milestone(state) or {}
    state["current_window"] = {
        "milestone_id": milestone.get("id"),
        "unit": plan_unit(state),
        "length": window_length(state),
        "start_date": date.today().isoformat(),
        "days": generate_plan(state),
        "version": 1,
    }
    if reset_confirmed:
        state["plan_confirmed"] = False        # 新窗口需要用户确认
    return True


def ensure_plan(state) -> bool:
    """确保**路线图 + 执行窗口**都存在。返回是否新生成了窗口。

    编排层的 `planning.plan_generate` 只调它，不关心里面是几次模型调用。
    """
    if not state.get("roadmap"):
        state["roadmap"] = generate_roadmap(state)
    return ensure_window(state)


# ---------------------------------------------------------------------------
# 3) 滚动（"滚动 = 重估"，不只是换下一批）
# ---------------------------------------------------------------------------

def _recalibrate_pending(roadmap: dict, ratio: float) -> None:
    """按 `ratio` 校正**后续未完成**里程碑的 `sessions_est`（温和，限制在 ±50%）。"""
    if ratio <= 0:
        return
    ratio = max(0.5, min(1.5, ratio))
    for item in roadmap.get("milestones") or []:
        if item.get("status") == MILESTONE_DONE:
            continue
        base = item.get("sessions_est") or DEFAULT_WINDOW_LENGTH
        scaled = int(round(float(base) * ratio))
        item["sessions_est"] = max(MIN_WINDOW_LENGTH, min(MAX_WINDOW_LENGTH, scaled))


def window_usage(state) -> tuple[int, int]:
    """返回 (窗口内**验收尝试次数**, 窗口**任务总数**)，供 `roll_window` 估速度。

    **口径（v0.14 修正）：两个数都是任务粒度**，可以直接相除。
    - 分子 `plan_progress["attempts"]`：每经历一次验收判定 +1（**含重做**）
    - 分母：窗口内任务总数 = `sum(len(day["tasks"]))`

    无重做时 `ratio == 1`；重做越多 `ratio` 越大；**不会 < 1**（每个任务至少判定一次）。

    **历史缺陷（审计发现，已修）**：分子原用 `len(progress["completed"])` ——
    那是**去重后的任务位置数**，其上限恰好等于分母（窗口跑完时两者相等），
    而且**重做根本不计入**（`mark_task_done` 按 key 去重、retry 分支不调用它）。
    于是若模型每单元写 2 个任务，`ratio` 会恒为 2 并被钳到 1.5 ——
    后续里程碑被**无条件放大 50%**，而真正的"变慢"信号反而丢失。
    """
    window = state.get("current_window") or {}
    days = window.get("days") or []
    total_tasks = sum(
        len(day.get("tasks") or []) for day in days if isinstance(day, dict)
    )
    if total_tasks <= 0:
        total_tasks = int(window.get("length") or 1) or 1

    progress = state.get("plan_progress") or {}
    try:
        attempts = int(progress.get("attempts"))
    except (TypeError, ValueError):
        # 旧状态文件没有 `attempts`（`upgrade_plan_progress` 没跑过）：
        # **按"没有重做"处理**（中性，ratio = 1）。
        # 绝不能改用去重的 `completed` 冒充 —— 那会被误读成"更快"，反而缩短估计。
        attempts = total_tasks
    return max(0, attempts), max(1, total_tasks)


def roll_window(state) -> bool:
    """窗口已完成后**滚动**到下一个里程碑，并按实际速度重估后续估计。

    返回是否成功滚动。路线图已走完（没有下一个里程碑）或窗口未完成 → False。
    """
    if not state.get("current_window"):
        return False
    if not is_plan_finished(state):
        return False

    used, planned = window_usage(state)
    ratio = (used / planned) if planned else 1.0

    if not advance_milestone(state):
        return False                          # 整张路线图走完：交给调用方提示用户

    roadmap = state.get("roadmap") or {}
    _recalibrate_pending(roadmap, ratio)

    # 清空窗口与游标，交给 ensure_window 按**新里程碑**重建
    state["current_window"] = None
    state["plan_progress"] = fresh_progress()
    state["today_task"] = None
    state["pending_submission"] = None
    state["latest_result"] = None
    state["latest_result_applied"] = False
    return ensure_window(state, reset_confirmed=False)


# ---------------------------------------------------------------------------
# 4) 展示与确认
# ---------------------------------------------------------------------------

def describe_plan(state, max_days: int = 7) -> str:
    """把**路线图 + 执行窗口**压缩成可注入对话的摘要，让教练照着呈现而不是另编一份。"""
    roadmap = state.get("roadmap") or {}
    milestones = roadmap.get("milestones") or []
    window = state.get("current_window") or {}
    days = window.get("days") or []

    lines: list[str] = []
    if milestones:
        done = sum(1 for item in milestones if item.get("status") == "done")
        current = current_milestone(state) or {}
        lines.append(f"- 路线图：共 {len(milestones)} 个里程碑，已完成 {done} 个")
        lines.append(
            f"- 当前里程碑：{current.get('id', '')} {current.get('title', '')}"
            f"（知识点：{'、'.join(current.get('topics') or []) or '未指定'}）"
        )
    if days:
        unit = unit_label(state)
        lines.append(
            f"- 执行窗口：{window.get('length', len(days))} {unit}"
            f"（起始 {window.get('start_date', '')}）"
        )
        for day in days[:max_days]:
            theme = day.get("theme", "")
            tasks = day.get("tasks") or []
            first_goal = tasks[0].get("goal", "") if tasks else ""
            lines.append(f"- 第{day.get('day')}{unit}：{theme}｜{len(tasks)} 个任务"
                         + (f"（首个任务：{first_goal}）" if first_goal else ""))
    if not lines:
        return ""

    if not is_confirmed(state):
        lines.append("- 用户尚未确认该计划：请先把计划讲清楚并请用户确认，不要直接开始教学")
    else:
        lines.append("- 用户已确认路线图（其下所有里程碑都已授权），可以继续执行")
    return "\n".join(lines)


def confirm_plan(state, user_input: str) -> ConfirmationVerdict | None:
    """用 LLM 判断用户是否确认计划；确认则置 plan_confirmed=True。

    返回判定结果；判定失败（无 Key / 网络异常）返回 None，并**保持等待状态**。
    """
    window = state.get("current_window") or {}
    if not window:
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
            confirmed=to_bool(data.get("confirmed")),
            reason=str(data.get("reason") or ""),
        )
    except Exception as exc:                  # noqa: BLE001 —— 判定失败就继续等待
        print(f"[计划确认判定失败，保持等待] {type(exc).__name__}: {exc}")
        return None

    if verdict.confirmed:
        state["plan_confirmed"] = True
    return verdict
