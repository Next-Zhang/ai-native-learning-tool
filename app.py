import json

import assessor
import daily
import evaluator
import planner
import reset
from agent import chat_with_coach
from profile_extractor import extract_profile
from rag.tool import format_sources
from stages import stage_label, try_advance
from state import (
    DEFAULT_STATE,
    PROFILE_FIELDS,
    STAGE_ASSESSMENT,
    STAGE_EVALUATION,
    STAGE_LEARNING,
    STAGE_PLANNING,
    load_state,
    merge_profile,
    save_state,
)


FIELD_LABELS = {
    "learning_goal": "学习目标",
    "current_level": "当前水平",
    "daily_minutes": "每天可投入",
    "target_date": "期望期限",
}


def format_profile(state) -> str:
    """把已收集的画像字段格式化成一行，便于肉眼确认 V0.2 效果。"""
    parts = []
    for field in PROFILE_FIELDS:
        value = state.get(field)
        if value in (None, "", []):
            continue
        if field == "daily_minutes":
            value = f"{value} 分钟"
        parts.append(f"{FIELD_LABELS[field]}={value}")
    return " | ".join(parts) if parts else "（尚未收集到任何信息）"


def format_plan_status(state) -> str:
    """计划状态一句话，用于终端展示。"""
    plan = state.get("current_plan") or {}
    if not plan:
        return "未生成"
    status = "已确认" if state.get("plan_confirmed") else "待确认"
    return f"{plan.get('horizon_days', '?')} 天 / {status}"


state = load_state()

# 知识库检索开关：当前**默认关闭**（先不调用 RAG）
# 对话中可随时输入 /rag on 临时开启、/rag off 关闭
use_rag = False

print("AI Learning Coach 已启动")
print("输入 exit 退出程序")
print("知识库检索默认关闭；输入 /rag on 可临时开启（/rag off 关闭）")
print("测试用：/reset 清空对话历史（保留画像与进度）；/reset all 完全重置")
print(f"当前状态：阶段={stage_label(state.get('current_stage'))} | {format_profile(state)}")


while True:

    user_input = input("\n你：").strip()

    if user_input.lower() in ["exit", "quit"]:
        print("学习状态已保存。")
        break

    # 知识库开关指令
    if user_input.lower() in ["/rag off", "/rag on"]:
        use_rag = user_input.lower().endswith("on")
        print("知识库检索：", "已开启" if use_rag else "已关闭")
        continue

    # 记忆清理指令（测试用）
    if user_input.lower().startswith("/reset"):
        if user_input.lower().endswith("all"):
            backup = reset.backup_state()
            state.clear()
            state.update(json.loads(json.dumps(DEFAULT_STATE)))
            save_state(state)
            print("[记忆] 已完全重置（回到目标澄清）"
                  + (f"，旧状态备份于 {backup.name}" if backup else ""))
        else:
            cleared = reset.clear_history(state)
            save_state(state)
            print(f"[记忆] 已清空当前对话历史（{cleared} 条）；画像/计划/阶段保留")
        continue

    # ① V0.2：抽取画像 -> 合并（空值不覆盖）
    profile = extract_profile(user_input)
    updated_fields = merge_profile(state, profile)

    # ② V0.3c：计划阶段 —— 先判定用户是否确认（B2），再确保计划已生成
    confirmation = None
    plan_created = False
    if state.get("current_stage") == STAGE_PLANNING:
        if state.get("current_plan") and not planner.is_confirmed(state):
            confirmation = planner.confirm_plan(state, user_input)
        plan_created = planner.ensure_plan(state)

    # ②' V0.3d：每日任务阶段 —— 先判定是否提交结果，再准备“今日任务”
    submission = None
    task_created = None
    in_learning = state.get("current_stage") == STAGE_LEARNING
    if in_learning:
        if state.get("today_task") and not state.get("pending_submission"):
            submission = daily.detect_submission(state, user_input)
        if not state.get("today_task"):
            task_created = daily.build_today_task(state)

    # ②'' V0.3e：验收阶段 —— 有提交且尚未判定时，先做结构化判定
    evaluation = None
    if state.get("current_stage") == STAGE_EVALUATION and state.get("pending_submission"):
        evaluation = evaluator.evaluate(state)

    # ③ V0.3 状态机：条件满足才推进一步（守卫在 stages.py）
    transitions = []
    previous_stage = state.get("current_stage")
    if try_advance(state):
        transitions.append((previous_stage, state.get("current_stage")))

    # ④ V0.3b：测评阶段 —— 首次进入先生成测评大纲
    in_assessment = state.get("current_stage") == STAGE_ASSESSMENT
    assessment_plan_created = assessor.ensure_plan(state) if in_assessment else False

    # ⑤ 让教练带着最新状态对话（阶段提示词 + 已知信息 + 进度注入）
    history = state["conversation_history"]

    answer, sources = chat_with_coach(
        user_input=user_input,
        history=history,
        use_rag=use_rag,
        state=state,
    )

    print("\nCoach：", answer)

    # 本次使用了知识库时，打印来源章节（便于核对回答依据）
    if sources:
        print("\n[参考资料]", format_sources(sources))

    # ⑥ V0.3b：测评记账 —— 只有“题目在上一步已经提出”时才记录本轮作答
    record = None
    summary = None
    if in_assessment and not assessment_plan_created:
        record = assessor.record_answer(state, user_input, answer)
        if assessor.is_finished(state):
            summary = assessor.finalize(state)
            previous_stage = state.get("current_stage")
            if try_advance(state):
                transitions.append((previous_stage, state.get("current_stage")))

    # ⑥' V0.3e：判定成功后应用画像更新，并按 pass / retry 决定推进还是重做
    update_summary = None
    if evaluation is not None:
        previous_stage = state.get("current_stage")
        if try_advance(state):                       # 结果验收 -> 画像更新
            transitions.append((previous_stage, state.get("current_stage")))
        update_summary = evaluator.apply_update(state)
        previous_stage = state.get("current_stage")
        if try_advance(state):                       # 画像更新 -> 每日任务
            transitions.append((previous_stage, state.get("current_stage")))

    # ⑦ 展示状态变化（肉眼可验证）
    if updated_fields:
        labels = "、".join(FIELD_LABELS[f] for f in updated_fields)
        print(f"\n[画像] 本轮新增：{labels}")

    if assessment_plan_created:
        plan = (state.get("assessment_progress") or {}).get("plan") or []
        topics = "、".join(q.get("topic", "") for q in plan)
        print(f"[测评] 已生成测评大纲：{len(plan)} 题（{topics}）")

    if record:
        print(f"[测评] 第 {record.index} 题「{record.topic}」判定："
              f"{record.verdict}（{record.note}）")

    if summary:
        print(f"[测评] 测评完成：知识点得分 {summary['skill_profile']}")
        print(f"[测评] 薄弱点：{'、'.join(summary['weak_points']) or '（无）'}")

    if plan_created:
        plan = state.get("current_plan") or {}
        themes = "、".join(day.get("theme", "") for day in plan.get("days", []))
        print(f"[计划] 已生成 {plan.get('horizon_days')} 天计划"
              f"（起始 {plan.get('start_date')}）：{themes}")

    if confirmation is not None:
        if confirmation.confirmed:
            print(f"[计划] 用户已确认计划（{confirmation.reason}）")
        else:
            print(f"[计划] 尚未确认：{confirmation.reason}")

    if task_created:
        print(f"[任务] 今日任务（第 {task_created['day']} 天 · 第 {task_created['task']} 个）："
              f"{task_created['goal']}（预计 {task_created.get('minutes', 0)} 分钟）")

    if submission is not None and submission.is_submission:
        print(f"[任务] 收到提交（{submission.reason}）：{submission.content[:80]}")

    if evaluation is not None:
        print(f"[验收] 判定：完成度={evaluation.completion} | 掌握度={evaluation.mastery} "
              f"| 下一步={evaluation.next_action}")
        print(f"[验收] 错误类型：{'、'.join(evaluation.error_types) or '（无）'}")
        if evaluation.feedback:
            print(f"[验收] 反馈：{evaluation.feedback}")

    if update_summary is not None:
        action_text = "已通过，推进到下一个任务" if update_summary["action"] == "pass" \
            else "未通过，重做当前任务"
        print(f"[画像] 已更新「{update_summary['topic']}」= {update_summary['score']}"
              f" → 画像：{update_summary['skill_profile']}")
        print(f"[画像] 薄弱点：{'、'.join(update_summary['weak_points']) or '（无）'}")
        print(f"[任务] {action_text}")

    if in_learning and plan_created is False and task_created is None \
            and daily.is_plan_finished(state):
        print("[计划] 本窗口计划已全部完成（滚动重排将在后续版本实现）")

    for from_stage, to_stage in transitions:
        print(f"[阶段] {stage_label(from_stage)} → {stage_label(to_stage)}")

    print(f"[状态] 阶段={stage_label(state.get('current_stage'))} | {format_profile(state)}")
    if state.get("skill_profile"):
        print(f"[状态] 能力画像={state['skill_profile']} | 薄弱点={state.get('weak_points') or []}")
    print(f"[状态] 学习计划={format_plan_status(state)}")
    if state.get("current_plan"):
        print(f"[状态] 计划进度={daily.describe_progress(state)}")

    state["conversation_history"].append(
        {
            "role": "user",
            "content": user_input
        }
    )

    state["conversation_history"].append(
        {
            "role": "assistant",
            "content": answer
        }
    )

    save_state(state)
