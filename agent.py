from openai import OpenAI

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL


client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL
)


SYSTEM_PROMPT = """
你是 AI Learning Coach，一个持续帮助用户学习技能的智能教练。

你的目标不是单纯回答问题，而是帮助用户最终掌握一个技能。

当前阶段优先完成学习需求澄清。

需要了解：
1. 用户想学习什么
2. 用户当前水平
3. 用户每天可以投入多少时间
4. 用户希望多久达到目标

规则：
- 如果信息不足，一次只询问最关键的1~2个问题。
- 不要过早生成完整学习计划。
- 不要一次输出大量知识。
- 用户说“我会了”并不等于真正掌握，后续需要通过任务验收。
"""


def chat_with_coach(user_input, history):

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    messages.extend(history)

    messages.append(
        {
            "role": "user",
            "content": user_input
        }
    )

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages
    )

    return response.choices[0].message.content