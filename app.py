from agent import chat_with_coach
from profile_extractor import extract_profile
from rag.tool import format_sources
from state import (
    PROFILE_FIELDS,
    load_state,
    maybe_advance_stage,
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


state = load_state()

# 知识库检索开关：当前**默认关闭**（先不调用 RAG）
# 对话中可随时输入 /rag on 临时开启、/rag off 关闭
use_rag = False

print("AI Learning Coach 已启动")
print("输入 exit 退出程序")
print("知识库检索默认关闭；输入 /rag on 可临时开启（/rag off 关闭）")
print(f"当前状态：阶段={state.get('current_stage')} | {format_profile(state)}")


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

    # ① V0.2：抽取画像 -> 合并（空值不覆盖）-> 阶段推进（四项齐全才进 assessment）
    profile = extract_profile(user_input)
    updated_fields = merge_profile(state, profile)
    advanced = maybe_advance_stage(state)

    # ② 让教练带着最新状态对话（已知信息注入，避免重复提问）
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

    # ③ 展示画像收集进度（V0.2 的可见效果）
    if updated_fields:
        labels = "、".join(FIELD_LABELS[f] for f in updated_fields)
        print(f"\n[画像] 本轮新增：{labels}")
    if advanced:
        print("[阶段] goal_clarification → assessment（四项信息已齐全）")
    print("[画像]", format_profile(state))

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
