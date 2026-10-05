"""应用层：用例（编排 domain 纯逻辑 + llm + prompts）。

模块一览：
    profile       画像抽取
    assessment    能力测评（出题/判分）
    planning      学习计划（生成/确认）
    daily_task    每日任务（展示/提交识别）
    evaluation    结果验收与画像更新
    coach         教练主对话（消息组装 + LLM 调用）

约束：本层可以调 LLM，但**不做状态机推进**（见 `coach.orchestration`），
也**不直接落盘**（见 `coach.storage`）。

按需从子模块直接导入，例如：
    from coach.services.planning import ensure_plan
"""
