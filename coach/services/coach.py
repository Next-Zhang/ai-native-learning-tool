"""教练主对话用例（原 `agent.py`）。

职责：把「阶段提示词 + 已知画像 + 参考资料 + 历史 + 本轮输入」组装成消息并调用模型。
**不再自己持有 LLM 客户端**（改由 `coach.llm` 统一提供），也不再硬编码模型名。

RAG 采用**惰性导入**：RAG 本期不在范围，缺失时不应影响主流程
（导入与检索都包在 try/except 里，失败只 `print` 一行提示并按"无参考资料"继续）。

兜底：`client.chat` 失败时返回 `FALLBACK_REPLY`，**绝不向上抛** ——
`cli.main` 与 `orchestration.turn` 都没有 try/except，抛出去就是整个会话崩掉。
"""

from coach.domain.memory import (
    INJECT_CHAR_BUDGET,
    INJECT_SESSION_SUMMARIES,
    select_history,
    session_summaries,
)
from coach.domain.profile import render_profile
from coach.domain.profile_rules import PROFILE_FIELDS
from coach.domain.stages import (
    STAGE_ASSESSMENT,
    STAGE_EVALUATION,
    STAGE_LEARNING,
    STAGE_PLANNING,
    stage_label,
)
from coach.llm import client
from coach.prompts.stages import stage_prompt
from coach.prompts.tasks import (
    KNOWN_INFO_PROMPT,
    PROGRESS_MEMORY_PROMPT,
    RAG_SYSTEM_PROMPT,
    SESSION_HISTORY_PROMPT,
)
from coach.services.assessment import describe_progress
from coach.services.daily_task import describe_today_task
from coach.services.evaluation import describe_result
from coach.services.planning import describe_plan

__all__ = ["chat_with_coach", "describe_known_profile"]

#: 模型调用失败时的**确定性兜底回复**。必须不涉及任何阶段判定
#: （不提"通过/未通过/下一步"），否则会在代码判定之前误导用户（缺陷 A）。
FALLBACK_REPLY = (
    "（本轮没能取到模型的回复：可能是网络波动或 API Key 失效。"
    "你的学习进度已保存，请稍后重试。）"
)

# 字段 -> 中文标签，用于拼"已知信息"
_PROFILE_LABELS = {
    "learning_goal": "学习目标",
    "current_level": "当前水平",
    "session_minutes": "单次可投入",
    "target_date": "期望期限",
    "sessions_per_week": "每周大约",       # 可选项：知道就展示，但不追问
}


def describe_known_profile(state, stage: str | None = None) -> str:
    """把**用户画像**与阶段上下文整理成可注入对话的权威状态文本。

    画像部分由 `domain.profile.render_profile()` 提供（**唯一渲染出口**）；
    本函数只在其上叠加"还缺什么"与**阶段相关**的注入。

    `stage` 可显式覆盖：调用方应传入**本轮起始阶段**。状态机可能在本轮已经
    推进（如"用户刚提交"→ evaluation），但模型不该抢在代码判定之前
    扮演下一个阶段的角色（真实运行缺陷 A）。
    """
    if not state:
        return ""
    lines: list[str] = []
    # 画像部分走 **domain.profile 的唯一渲染出口**。
    # 这修掉了 X-18：以前这里手工挑字段，**漏掉了 skill_profile / weak_points**，
    # 于是"方案生成知道你的薄弱点，但跟你对话的教练不知道"。
    rendered = render_profile(state)
    if rendered:
        lines.append(rendered)
    # 明确告知还缺什么，让“状态”真正驱动下一步提问。
    # **只列必填项** —— 可选项（每周几次）不该把用户卡在澄清阶段。
    missing = [
        _PROFILE_LABELS[field] for field in PROFILE_FIELDS
        if field in _PROFILE_LABELS and state.get(field) in (None, "", [])
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
    # 验收阶段：把结构化判定结论交给教练，照实沟通
    # （v0.16 删除了 profile_update 阶段，其分支已不可达）
    if stage == STAGE_EVALUATION:
        result_text = describe_result(state)
        if result_text:
            lines.append(result_text)
    return "\n".join(lines)


def chat_with_coach(
    user_input: str,
    history: list[dict],
    use_rag: bool = False,
    top_k: int = 5,
    state: dict | None = None,
    stage: str | None = None,
) -> tuple[str, list[dict]]:
    """与教练对话。

    use_rag=True 时，若问题与 Python 知识相关就先检索本地向量库，
    把检索结果作为参考资料注入，并要求模型标注来源。
    默认 use_rag=False（暂时不调用 RAG），需要时由调用方显式开启。

    `stage` 应传**本轮起始阶段**（`TurnResult.stage_before`）。由调用方指定而不是
    直接读 state，原因见 `describe_known_profile`：状态机可能已在本轮推进。

    `state` 不为空时会注入"当前权威状态"，让教练不再重复询问已有信息。

    返回 (回答文本, 来源列表)。来源列表为空表示本次没有使用知识库。

    兜底（审计修复）：模型调用失败时**不抛出**，而是 `print` 失败提示并返回
    `FALLBACK_REPLY` —— 否则一次网络抖动会直接掀掉整个 CLI 会话
    （`cli.main` / `run_turn` 都没有 try/except）。
    """

    sources: list[dict] = []
    context = ""

    # 1) 判断是否需要查库，需要则检索（惰性导入 + 兜底：RAG 不可用时不影响主流程，
    #    与 `cli.main._format_sources` 的处理保持一致；首次检索会下载/加载本地模型，
    #    失败是常见情况，绝不能让它中断对话）
    if use_rag:
        try:
            from rag.tool import build_context, should_retrieve

            if should_retrieve(user_input):
                context, sources = build_context(user_input, top_k=top_k)
        except Exception as exc:            # noqa: BLE001 —— 检索失败按"无参考资料"继续
            print(f"[知识库检索失败，本轮按无参考资料继续] {type(exc).__name__}: {exc}")
            context, sources = "", []

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

    # 3) 先算出「权威状态」文本 —— 它**参与**下面的注入预算计算
    known = describe_known_profile(state, stage=effective_stage)

    # 3b) 记忆的**叙事层**（docs/memory-design.md §6.1 的 ② 与 ④）：
    #     本次学习的进行中摘要 + 此前各次学习的定稿摘要。
    #     它们必须排在对话原文之前，但**权威状态仍在最后**（I-3 不变）。
    rolling = (state or {}).get("rolling_summary")
    if rolling:
        messages.append({
            "role": "system",
            "content": PROGRESS_MEMORY_PROMPT + "\n\n【本次学习进展】\n" + str(rolling),
        })

    recent = session_summaries(state)[-INJECT_SESSION_SUMMARIES:] if state else []
    if recent:
        block = "\n".join(
            f"- 第 {item.get('seq')} 次学习：{item.get('text', '')}" for item in recent
        )
        messages.append({
            "role": "system",
            "content": SESSION_HISTORY_PROMPT + "\n\n【此前学习摘要】\n" + block,
        })

    # 4) 历史按**字符预算**截取，而不是固定条数（docs/memory-design.md §6.1）。
    #    固定条数无法适配不同长度的对话：一次 2 小时的学习里，8 条只覆盖最近十几分钟；
    #    固定放大又会在短对话里白白拉长提示词。
    fixed = sum(len(str(m.get("content") or "")) for m in messages)
    fixed += len(user_input) + len(known or "")
    messages.extend(select_history(history, budget=max(0, INJECT_CHAR_BUDGET - fixed)))

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

    try:
        answer = client.chat(messages)
    except Exception as exc:                # noqa: BLE001 —— 一次对话失败不得中断整个会话
        print(f"[对话调用失败，已使用兜底回复] {type(exc).__name__}: {exc}")
        answer = FALLBACK_REPLY

    return answer, sources
