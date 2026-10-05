"""教练主对话用例（原 `agent.py`）。

职责：把「阶段提示词 + 已知画像 + 参考资料 + 历史 + 本轮输入」组装成消息并调用模型。
**不再自己持有 LLM 客户端**（改由 `coach.llm` 统一提供），也不再硬编码模型名。

RAG 采用**惰性导入**：RAG 本期不在范围，缺失时不应影响主流程。
"""

from coach.domain.stages import (
    STAGE_ASSESSMENT,
    STAGE_EVALUATION,
    STAGE_LEARNING,
    STAGE_PLANNING,
    STAGE_PROFILE_UPDATE,
    stage_label,
)
from coach.llm import client
from coach.prompts.stages import stage_prompt
from coach.prompts.tasks import KNOWN_INFO_PROMPT, RAG_SYSTEM_PROMPT
from coach.services.assessment import describe_progress
from coach.services.daily_task import describe_today_task
from coach.services.evaluation import describe_result
from coach.services.planning import describe_plan

__all__ = ["chat_with_coach", "describe_known_profile"]

# 字段 -> 中文标签，用于拼"已知信息"
_PROFILE_LABELS = {
    "learning_goal": "学习目标",
    "current_level": "当前水平",
    "daily_minutes": "每天可投入",
    "target_date": "期望期限",
}


def describe_known_profile(state) -> str:
    """把 state 里已填写的画像字段整理成可读文本；全空则返回空字符串。"""
    if not state:
        return ""
    lines = []
    for field, label in _PROFILE_LABELS.items():
        value = state.get(field)
        if value in (None, "", []):
            continue
        if field == "daily_minutes":
            value = f"{value} 分钟"
        lines.append(f"- {label}：{value}")
    if not lines:
        return ""
    # 明确告知还缺什么，让“状态”真正驱动下一步提问
    missing = [
        label for field, label in _PROFILE_LABELS.items()
        if state.get(field) in (None, "", [])
    ]
    if missing:
        lines.append(f"- 仍缺失（需要询问）：{'、'.join(missing)}")
    stage = state.get("current_stage")
    if stage:
        lines.append(f"- 当前阶段：{stage_label(stage)}")
    # 测评阶段：把测评进度交给教练，确保一次只问当前这道题、不跳题
    if stage == STAGE_ASSESSMENT:
        progress_text = describe_progress(state)
        if progress_text:
            lines.append(progress_text)
    # 计划阶段：把已生成的计划交给教练，照实呈现而不是另编一份
    if stage == STAGE_PLANNING:
        plan_text = describe_plan(state)
        if plan_text:
            lines.append(plan_text)
    # 学习/验收阶段：注入今日任务与待验收的提交内容
    if stage in (STAGE_LEARNING, STAGE_EVALUATION):
        task_text = describe_today_task(state)
        if task_text:
            lines.append(task_text)
        submission = state.get("pending_submission") or {}
        if submission.get("content"):
            lines.append(f"- 用户已提交待验收内容：{submission['content'][:400]}")
    # 验收/画像更新阶段：把结构化判定结论交给教练，照实沟通
    if stage in (STAGE_EVALUATION, STAGE_PROFILE_UPDATE):
        result_text = describe_result(state)
        if result_text:
            lines.append(result_text)
    return "\n".join(lines)


def chat_with_coach(user_input, history, use_rag=False, top_k=5, state=None):
    """与教练对话。

    use_rag=True 时，若问题与 Python 知识相关就先检索本地向量库，
    把检索结果作为参考资料注入，并要求模型标注来源。
    默认 use_rag=False（暂时不调用 RAG），需要时由调用方显式开启。

    state 不为空时会注入“已知用户信息”，让教练不再重复询问已有信息（V0.2 画像回灌）。

    返回 (回答文本, 来源列表)。来源列表为空表示本次没有使用知识库。
    """

    sources = []
    context = ""

    # 1) 判断是否需要查库，需要则检索（惰性导入：RAG 不在范围时不影响主流程）
    if use_rag:
        from rag.tool import build_context, should_retrieve

        if should_retrieve(user_input):
            context, sources = build_context(user_input, top_k=top_k)

    # 2) 组装消息：阶段提示词 -> (已知信息) -> (参考资料) -> 历史 -> 本次用户输入
    #    阶段提示词由状态机提供：处于哪个阶段，教练就按那个阶段的行为准则工作
    current_stage = (state or {}).get("current_stage")
    messages = [
        {
            "role": "system",
            "content": stage_prompt(current_stage)
        }
    ]

    known = describe_known_profile(state)
    if known:
        messages.append(
            {
                "role": "system",
                "content": KNOWN_INFO_PROMPT + "\n\n【已知用户信息】\n" + known
            }
        )

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

    answer = client.chat(messages)

    return answer, sources
