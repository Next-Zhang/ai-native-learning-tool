"""终端界面层（原 `app.py` 的展示与交互部分）。

本层只做三件事：读输入、调 `run_turn()`、渲染 `TurnResult`。
业务流程一律不在这里——那是 `coach.orchestration.turn` 的职责。
"""

from coach.config import API_KEY_ENV, get_settings
from coach.domain.plan_rules import current_milestone
from coach.domain.profile_rules import OPTIONAL_PROFILE_FIELDS, PROFILE_FIELDS
from coach.domain.stages import stage_label
from coach.metrics import recorder as metrics
from coach.orchestration.turn import TurnResult, run_turn
from coach.services.daily_task import describe_progress
from coach.services.maintenance import SCOPE_ALL, SCOPE_HISTORY, perform_reset
from coach.services.planning import is_confirmed
from coach.storage.state_store import load_state

__all__ = ["ask_confirmation", "format_plan_status", "format_profile", "main", "render_turn"]

# 确认提示接受的肯定/否定写法；其它一律视为"未确认"（fail-closed）
_CONFIRM_YES = ("y", "yes", "是", "确认", "确定", "好", "可以")
_CONFIRM_NO = ("n", "no", "否", "取消", "不", "不用", "不要")

FIELD_LABELS = {
    "learning_goal": "学习目标",
    "current_level": "当前水平",
    "session_minutes": "单次可投入",
    "target_date": "期望期限",
    "sessions_per_week": "每周约",
}


def format_profile(state) -> str:
    """把已收集的画像字段格式化成一行，便于肉眼确认。

    必填四项 + **已知的**可选项（每周几次）。
    """
    parts = []
    for field in PROFILE_FIELDS + OPTIONAL_PROFILE_FIELDS:
        value = state.get(field)
        if value in (None, "", []):
            continue
        if field == "session_minutes":
            value = f"{value} 分钟"
        elif field == "sessions_per_week":
            value = f"{value} 次"
        parts.append(f"{FIELD_LABELS[field]}={value}")
    return " | ".join(parts) if parts else "（尚未收集到任何信息）"


def _window_length(window: dict) -> int:
    """执行窗口的长度（单位见 `unit`；单位是"次"或"天"）。

    `length` 缺失/为 None 时退回 `days` 的实际条数 —— 旧状态文件只有 `horizon_days`
    （由 `domain.state_schema.upgrade_window_shape` 补出 `length`），展示层必须容错，
    否则会打印成 "None 次"。
    """
    return window.get("length") or len(window.get("days") or []) or 1


def format_plan_status(state) -> str:
    """计划状态一句话，用于终端展示（**路线图进度 + 执行窗口**）。"""
    window = state.get("current_window") or {}
    if not window:
        return "未生成"

    # "当前里程碑"的定义只有一个来源：`domain.plan_rules.current_milestone`
    # （它在 `roadmap.current_milestone` 缺失时会退回第一个未完成的里程碑）。
    roadmap = state.get("roadmap") or {}
    milestones = roadmap.get("milestones") or []
    current = current_milestone(state)

    status = "已确认" if is_confirmed(state) else "待确认"
    unit = "次" if (window.get("unit") or "session") == "session" else "天"
    length = _window_length(window)

    if current and milestones:
        index = milestones.index(current) + 1
        return (f"{index}/{len(milestones)} {current.get('title', '')}"
                f" · 本窗口 {length} {unit} / {status}")
    return f"{length} {unit} / {status}"


def _format_sources(sources) -> str:
    """来源列表 -> 一行文本（惰性导入 RAG，缺失时退化为原文）。"""
    try:
        from rag.tool import format_sources
    except Exception:                       # noqa: BLE001 —— RAG 不在范围时不影响主流程
        return "；".join(str(s) for s in sources)
    return format_sources(sources)


def render_turn(result: TurnResult, state) -> None:
    """把一轮结果渲染到终端（顺序与 V0.3 保持一致：先回答，再事件，最后状态）。"""
    print("\nCoach：", result.answer)

    # 本次使用了知识库时，打印来源章节（便于核对回答依据）
    if result.sources:
        print("\n[参考资料]", _format_sources(result.sources))

    if result.updated_fields:
        labels = "、".join(FIELD_LABELS[f] for f in result.updated_fields)
        print(f"\n[画像] 本轮新增：{labels}")

    if result.assessment_plan_created:
        topics = "、".join(result.assessment_topics)
        print(f"[测评] 已生成测评大纲：{len(result.assessment_topics)} 题（{topics}）")

    if result.record:
        print(f"[测评] 第 {result.record.index} 题「{result.record.topic}」判定："
              f"{result.record.verdict}（{result.record.note}）")

    if result.summary:
        print(f"[测评] 测评完成：知识点得分 {result.summary['skill_profile']}")
        print(f"[测评] 薄弱点：{'、'.join(result.summary['weak_points']) or '（无）'}")

    if result.plan_created:
        roadmap = state.get("roadmap") or {}
        plan = state.get("current_window") or {}
        milestones = roadmap.get("milestones") or []
        if milestones:
            titles = " → ".join(m.get("title", "") for m in milestones)
            print(f"[路线图] {len(milestones)} 个里程碑：{titles}")
        unit = "次" if (plan.get("unit") or "session") == "session" else "天"
        themes = "、".join(day.get("theme", "") for day in (plan.get("days") or []))
        print(f"[窗口] 已生成 {_window_length(plan)} {unit} 计划"
              f"（起始 {plan.get('start_date')}）：{themes}")

    if result.confirmation is not None:
        if result.confirmation.confirmed:
            print(f"[计划] 用户已确认计划（{result.confirmation.reason}）")
        else:
            print(f"[计划] 尚未确认：{result.confirmation.reason}")

    if result.task_created:
        window_unit = ((state.get("current_window") or {}).get("unit") or "session")
        unit = "次" if window_unit == "session" else "天"
        print(f"[任务] 当前任务（第 {result.task_created['day']} {unit} · "
              f"第 {result.task_created['task']} 个）："
              f"{result.task_created['goal']}（预计 {result.task_created.get('minutes', 0)} 分钟）")

    if result.submission is not None and result.submission.is_submission:
        print(f"[任务] 收到提交（{result.submission.reason}）：{result.submission.content[:80]}")

    if result.evaluation_result is not None:
        evaluation = result.evaluation_result
        print(f"[验收] 判定：完成度={evaluation.completion} | 掌握度={evaluation.mastery} "
              f"| 下一步={evaluation.next_action}")
        print(f"[验收] 错误类型：{'、'.join(evaluation.error_types) or '（无）'}")
        if evaluation.feedback:
            print(f"[验收] 反馈：{evaluation.feedback}")

    if result.update_summary is not None:
        summary = result.update_summary
        action_text = "已通过，推进到下一个任务" if summary["action"] == "pass" \
            else "未通过，重做当前任务"
        print(f"[画像] 已更新「{summary['topic']}」= {summary['score']}"
              f" → 画像：{summary['skill_profile']}")
        print(f"[画像] 薄弱点：{'、'.join(summary['weak_points']) or '（无）'}")
        print(f"[任务] {action_text}")

    if result.plan_finished:
        print("[计划] 本窗口计划已全部完成")
    if result.window_rolled:
        # S-12 已实现：窗口走完后由 `planning.window_roll` 滚动到下一个里程碑。
        # （旧文案写"滚动重排将在后续版本实现"，与实现不符。）
        print("[计划] 已滚动到下一个里程碑（按实际速度重估了后续估计）")

    for from_stage, to_stage in result.transitions:
        print(f"[阶段] {stage_label(from_stage)} → {stage_label(to_stage)}")

    print(f"[状态] 阶段={stage_label(state.get('current_stage'))} | {format_profile(state)}")
    if state.get("skill_profile"):
        print(f"[状态] 能力画像={state['skill_profile']} | 薄弱点={state.get('weak_points') or []}")
    print(f"[状态] 学习计划={format_plan_status(state)}")
    if state.get("current_window"):
        print(f"[状态] 计划进度={describe_progress(state)}")


def ask_confirmation(prompt: str) -> bool | None:
    """CLI 的确认提示（S-08 的 `confirm_fn` 实现）。

    - `y`/`是`/`确认` 等 → True
    - `n`/`否`/`取消` 等 → False
    - 其它（含直接回车、EOF、Ctrl+C）→ None，表示**未明确确认** → 按不执行处理
    """
    print(prompt)
    try:
        answer = input("你的选择 [y/N]：").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if answer in _CONFIRM_YES:
        return True
    if answer in _CONFIRM_NO:
        return False
    return None


def _handle_command(state, user_input: str, use_rag: bool):
    """处理 /rag 与 /reset；返回 (是否已处理, 新的 use_rag)。"""
    lowered = user_input.lower()

    if lowered in ("/rag off", "/rag on"):
        use_rag = lowered.endswith("on")
        print("知识库检索：", "已开启" if use_rag else "已关闭")
        return True, use_rag

    if lowered.startswith("/reset"):
        # 删除学习历史属不可逆动作：走 S-08 确认门，拒绝/超时都不会删
        scope = SCOPE_ALL if lowered.endswith("all") else SCOPE_HISTORY
        outcome = perform_reset(state, scope, ask_confirmation)
        print(outcome.message)
        return True, use_rag

    return False, use_rag


def main() -> int:
    # 启动期检查：缺 Key 时立刻给出清晰提示，而不是等第一轮对话中途才崩。
    # （库本身可无 Key 导入，只有真正调用模型才需要 Key。）
    if not get_settings().has_api_key:
        print(f"[错误] 未检测到 {API_KEY_ENV} 环境变量，无法调用模型。")
        print(f'请先设置后重试（PowerShell）：$env:{API_KEY_ENV} = "sk-..."')
        return 1

    state = load_state()

    # 指标采集：库默认**关闭**（避免测试与工具误写真实指标文件），
    # 由 CLI 启动时显式开启。事件写入 data/metrics/events.jsonl（PRD S-07）。
    recorder = metrics.enable()

    # 知识库检索开关：当前**默认关闭**（先不调用 RAG）
    use_rag = False

    print("AI Learning Coach 已启动")
    print("输入 exit 退出程序")
    print("知识库检索默认关闭；输入 /rag on 可临时开启（/rag off 关闭）")
    print("测试用：/reset 清空对话历史（保留画像与进度）；/reset all 完全重置（两者都会先请你确认）")
    print(f"指标采集：已开启 → {recorder.path}")
    print(f"当前状态：阶段={stage_label(state.get('current_stage'))} | {format_profile(state)}")

    while True:
        user_input = input("\n你：").strip()

        if user_input.lower() in ("exit", "quit"):
            print("学习状态已保存。")
            break

        handled, use_rag = _handle_command(state, user_input, use_rag)
        if handled:
            continue

        result = run_turn(state, user_input, use_rag=use_rag)
        render_turn(result, state)

    return 0
