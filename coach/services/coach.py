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


def describe_known_profile(state, stage: str | None = None) -> str:
    """把 state 里已填写的画像字段整理成可读文本；全空则返回空字符串。

    `stage` 可显式覆盖：调用方应传入**本轮起始阶段**。状态机可能在本轮已经
    推进（如"用户刚提交"→ evaluation），但模型不该抢在代码判定之前
    扮演下一个阶段的角色（真实运行缺陷 A）。
    """
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
    stage = stage if stage is not None else state.get("current_stage")
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
    # 学习/验收阶段：注入今日任务与提交状态
    if stage in (STAGE_LEARNING, STAGE_EVALUATION):
        task_text = describe_today_task(state)
        if task_text:
            lines.append(task_text)
        submission = state.get("pending_submission") or {}
        if submission.get("content"):
            if stage == STAGE_LEARNING:
                # 关键：本轮**不是**验收轮。只告知"已收到"，并明确禁止下结论——
                # 否则模型会照着提交内容自己写出"验收通过"，而代码的判定要下一轮才算
                # （真实运行缺陷 A：曾出现"先告诉用户通过、随后代码判未通过"）。
                lines.append(
                    "- 【已收到提交】系统已收到用户的提交，**验收由系统的验收环节在下一步完成**。"
                    "本轮**只确认收到**（可说明你接下来会核对哪几点），"
                    "**不要**给出完成度 / 掌握度 / 通过与否 / 错误类型 / 下一步动作的任何结论"
                )
            else:
                lines.append(f"- 用户已提交待验收内容：{submission['content'][:400]}")
    # 验收/画像更新阶段：把结构化判定结论交给教练，照实沟通
    if stage in (STAGE_EVALUATION, STAGE_PROFILE_UPDATE):
        result_text = describe_result(state)
        if result_text:
            lines.append(result_text)
    return "\n".join(lines)


def chat_with_coach(user_input, history, use_rag=False, top_k=5, state=None, stage=None):
    """与教练对话。

    use_rag=True 时，若问题与 Python 知识相关就先检索本地向量库，
    把检索结果作为参考资料注入，并要求模型标注来源。
    默认 use_rag=False（暂时不调用 RAG），需要时由调用方显式开启。

    `stage` 应传**本轮起始阶段**（`TurnResult.stage_before`）。由调用方指定而不是
    直接读 state，原因见 `describe_known_profile`：状态机可能已在本轮推进。

    `state` 不为空时会注入"当前权威状态"，让教练不再重复询问已有信息。

    返回 (回答文本, 来源列表)。来源列表为空表示本次没有使用知识库。
    """

    sources = []
    context = ""

    # 1) 判断是否需要查库，需要则检索（惰性导入：RAG 不在范围时不影响主流程）
    if use_rag:
        from rag.tool import build_context, should_retrieve

        if should_retrieve(user_input):
            context, sources = build_context(user_input, top_k=top_k)

    # 2) 组装消息。顺序很关键：
    #    阶段提示词 → (参考资料) → 对话历史 → **当前权威状态** → 本轮用户输入
    #
    #    权威状态必须放在历史**之后**：它是离生成点最近的一条 system 消息，
    #    否则当历史很长时，模型会沿用历史里自己的自述（真实运行缺陷 B）。
    effective_stage = stage if stage is not None else (state or {}).get("current_stage")

    messages = [
        {
            "role": "system",
            "content": stage_prompt(effective_stage)
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

    known = describe_known_profile(state, stage=effective_stage)
    if known:
        messages.append(
            {
                "role": "system",
                "content": KNOWN_INFO_PROMPT + "\n\n【当前权威状态】\n" + known
            }
        )

    messages.append(
        {
            "role": "user",
            "content": user_input
        }
    )

    answer = client.chat(messages)

    return answer, sources
