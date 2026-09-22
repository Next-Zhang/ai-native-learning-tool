from agent import chat_with_coach
from rag.tool import format_sources
from state import load_state, save_state


state = load_state()

# 知识库检索开关：当前**默认关闭**（先不调用 RAG）
# 对话中可随时输入 /rag on 临时开启、/rag off 关闭
use_rag = False

print("AI Learning Coach 已启动")
print("输入 exit 退出程序")
print("知识库检索默认关闭；输入 /rag on 可临时开启（/rag off 关闭）")


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

    history = state["conversation_history"]

    answer, sources = chat_with_coach(
        user_input=user_input,
        history=history,
        use_rag=use_rag
    )

    print("\nCoach：", answer)

    # 本次使用了知识库时，打印来源章节（便于核对回答依据）
    if sources:
        print("\n[参考资料]", format_sources(sources))

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
