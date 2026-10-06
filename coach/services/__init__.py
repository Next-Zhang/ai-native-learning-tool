"""应用层：用例（编排 domain 纯逻辑 + llm + prompts）。

模块一览：
    profile       画像抽取
    assessment    能力测评（出题/判分）
    planning      学习计划（生成/确认）
    daily_task    学习任务（展示/提交识别）
    evaluation    结果验收与画像更新
    coach         教练主对话（消息组装 + LLM 调用）
    maintenance   维护类用例（带确认门的重置：清空历史 / 完全重置）

约束：本层可以调 LLM，但**不做状态机推进**（见 `coach.orchestration`），
也**不直接落盘**（见 `coach.storage`）。

**例外（已知违规，待重划职责）**：`maintenance.perform_reset` 会调用
`coach.storage.reset` 落盘并备份（"删除学习历史"这一不可逆动作本身就必须
与持久化一起原子完成），且 `scope=all` 时会把 `current_stage` 一并重置回
目标澄清。它被 `coach.cli.main` 直接依赖，因此未在本轮改动。

按需从子模块直接导入，例如：
    from coach.services.planning import ensure_plan

`to_bool` 的**规范位置是 `coach.domain.coercion`**（因为 `domain/stages.py` 的守卫
也要用它，而 domain 不能依赖本层）；此处**重导出**，让
`from coach.services import to_bool` 继续可用。
"""

from coach.domain.coercion import to_bool

__all__ = ["to_bool"]
