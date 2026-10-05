"""AI Native Learning Tool —— 学习教练 Agent 主包。

分层（依赖方向自上而下，下层不依赖上层）：

    cli/            终端接口层
    orchestration/  单轮流程编排（状态机驱动）
    services/       应用层：用例（编排 domain + llm + prompts）
    storage/        持久化（本机 JSON）
    prompts/        提示词集中管理（纯数据）
    llm/            模型访问唯一入口
    domain/         领域纯逻辑（无 IO、无 LLM、可单测）

对外只暴露版本号；具体能力从各自子模块导入，避免隐式耦合。
"""

__version__ = "0.8.0"
