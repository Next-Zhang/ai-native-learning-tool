"""领域层：纯逻辑，无 IO、无 LLM 调用、无网络。

职责边界：
- 只做确定性计算与状态（dict）读写；
- 不导入 `coach.llm`、不读写文件（`state_schema` 只定义 schema，不落盘）。

模块一览：
    models             数据契约（Pydantic）
    stages             阶段常量 / 守卫 / 转换
    profile_rules      画像合并与完备性
    state_schema       状态 schema 与升级迁移
    assessment_rules   测评判定、聚合与薄弱点
    plan_rules         期限解析、窗口与计划清洗
    cursor             计划游标
    evaluation_rules   完成度、动作一致性与错误类型

按需从子模块直接导入，例如：
    from coach.domain.stages import try_advance
"""
