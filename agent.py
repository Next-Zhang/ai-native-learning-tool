from openai import OpenAI

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL
from rag.tool import build_context, should_retrieve


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


# 注入参考资料时追加的规则（RAG）
RAG_SYSTEM_PROMPT = """
下面提供了【参考资料】，来自 runoob Python3 教程的检索结果。

回答规则：
- 优先依据【参考资料】回答，引用了哪一条就标注编号，例如 [1]；可以引用多条 [1][3]。
- 如果参考资料不足以回答，先明确说“教程资料里没有找到相关说明”，再给出你自己的补充，
  并说明哪部分是通用补充知识。
- 不要编造参考资料中不存在的内容。
"""


def chat_with_coach(user_input, history, use_rag=False, top_k=5):
    """与教练对话。

    use_rag=True 时，若问题与 Python 知识相关就先检索本地向量库，
    把检索结果作为参考资料注入，并要求模型标注来源。
    默认 use_rag=False（暂时不调用 RAG），需要时由调用方显式开启。

    返回 (回答文本, 来源列表)。来源列表为空表示本次没有使用知识库。
    """

    sources = []
    context = ""

    # 1) 判断是否需要查库，需要则检索
    if use_rag and should_retrieve(user_input):
        context, sources = build_context(user_input, top_k=top_k)

    # 2) 组装消息：系统提示 -> (参考资料) -> 历史 -> 本次用户输入
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    if context:
        messages.append(
            {
                "role": "system",
                "content": RAG_SYSTEM_PROMPT + "\n\n【参考资料】\n" + context
            }
        )

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

    return response.choices[0].message.content, sources