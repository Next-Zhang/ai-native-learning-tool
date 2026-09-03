from agent import chat_with_coach
from state import load_state, save_state


state = load_state()

print("AI Learning Coach 已启动")
print("输入 exit 退出程序")


while True:

    user_input = input("\n你：").strip()

    if user_input.lower() in ["exit", "quit"]:
        print("学习状态已保存。")
        break

    history = state["conversation_history"]

    answer = chat_with_coach(
        user_input=user_input,
        history=history
    )

    print("\nCoach：", answer)

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