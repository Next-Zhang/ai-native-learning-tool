# 当前 Agent 架构

核对日期：2026-10-13。对象：App_landing 当前工作区（软件 v0.18）。
本文描述已存在的代码；产品目标见 [PRD](PRD.md)，取舍见 [架构决策](decisions.md)，缺口见 [交付清单](delivery.md)。
产品对象以 [术语表](terminology.md) 区分；下文代码符号与实际语义保留。PRD 1.0 已补齐十步目标闭环，其目标规范不改变本文的代码现状。目标级检索、能力矩阵确认、计划自审核、用户验收确认与 7 天回顾的产品要求见 PRD 第 3.3～3.4 节；本文仍记录现有单教练工作流，不把新增环节描述为已实现。

2026-11-01：目标设计已拆分为 [系统](system-design.md)、[Workflow](workflow-design.md) 和 [Agent 运行](agent-runtime-design.md)，并明确长期多人在线方向；下文仍仅描述现有 v0.18，不表示已经完成重构。

## 1. 执行范式

当前为代码编排的单教练 Workflow。模型负责内容生成、抽取及结构化判断；状态机守卫决定阶段推进。
只有 MatrixSelector 实现。HybridSelector、模型步骤提议与多 Agent 均未实现。

目标演进已于 2026-10-14 确定为外层工作流约束与局部 ReAct，见 [ADR-006](adr/0006-local-react.md)。首期在资料检索与计划生成/自审核中引入模型选择和结果反馈循环；沿用统一合法性、状态和授权检查。现有选择器注入点提供复用基础，但局部循环、退出恢复与限额尚未实现，不能将当前矩阵执行描述成 ReAct。

## 2. 目录与职责

| 目录/模块 | 当前职责 |
|---|---|
| app.py / coach/__main__.py | CLI 入口 |
| coach/cli/main.py | 读输入、处理 /rag 与 /reset、显示 TurnResult；也读取状态生成展示 |
| coach/orchestration/turn.py | 建 TurnContext、开启 trace、执行槽位、记录轮结束 |
| coach/orchestration/executor.py | 选择能力、检查前置条件、执行 handler、推进、护栏、摘要、历史及落盘 |
| coach/domain/stages.py | 阶段、守卫、转换函数 |
| coach/domain/capabilities.py | 能力声明、槽位、阶段适用性、读写键、自主权、顺序 |
| coach/domain/models.py / perception.py | 局部 Pydantic 数据模型与 PerceptionResult |
| coach/domain/*_rules.py / cursor.py | 画像、计划、评分和任务游标的确定性规则 |
| coach/domain/memory.py / zones.py | 证据、派生画像、历史选择、保留策略和逻辑分区 |
| coach/services/ | 模型用例及状态更新；maintenance 还执行备份与保存 |
| coach/prompts/ / coach/llm/ | 提示词与统一模型调用 |
| coach/storage/ | 状态读取、迁移触发、保存、重置及备份 |
| coach/metrics/ / observability/ | 指标事件和单轮执行 trace |
| rag/ | 可选的 Python 教程本地检索管道 |
| tests/ / evals/ | 确定性回归、live 用例、判定评测集 |

依赖方向以接口 → 编排/用例 → 领域规则与适配器为主。当前并非严格无例外：
maintenance 会落盘并重置阶段；CLI 直接读取领域与用例展示函数；执行器包含部分业务实现。

## 3. 状态机与单轮顺序

主链：goal_clarification → assessment → planning → learning → evaluation → learning。

| 转换 | 当前守卫 |
|---|---|
| 澄清 → 测评 | learning_goal、current_level、session_minutes、target_date 四项齐全 |
| 测评 → 计划 | skill_profile 非空 |
| 计划 → 学习 | current_window 存在，plan_confirmed 为真 |
| 学习 → 验收 | today_task 与 pending_submission 存在 |
| 验收 → 学习 | latest_result_applied 为真 |

completed 常量与提示词存在，但没有进出转换；目标结束目前由计划标志表达，未形成完整收尾流程。
一次 try_advance 只推进一步；一轮可以在多个推进点调用它，不等于一轮最多只转换一次。

骨架顺序：

1. intake：未补齐画像时抽取信息。
2. stage_pre：按当前阶段确认/生成计划、识别提交/构建任务，或进行验收。
3. 在 stage_pre 结束后尝试推进。
4. stage_post：进入测评后确保大纲存在。
5. dialogue：用本轮起始阶段组装上下文并生成回复，再经过内容护栏。
6. after_dialogue：测评判卷和收尾，必要时推进到计划。
7. evaluation_apply：应用本轮验收结论，推进回学习。
8. closing：摘要、完成检查、窗口滚动、历史裁剪及保存；具体顺序按注册表 order。

选择能力支持 live 与 turn_start 两种阶段快照。必须结合槽位和前置条件理解，不能只读阶段名。
当前测评将本轮回复传给判卷；该时序缺陷记录为 D-01，不能按理想题目绑定描述。

## 4. 能力执行与权限边界

能力定义在 REGISTRY；前置条件与 handler 分别在 executor 的两张表中，依靠能力名关联。
新增能力需要同时更新三处和对应测试，turn.py 通常无需改动。

reads 是说明与键名检查；writes 由测试 fixture 执行后的顶层差异验证。它们不是运行时权限隔离，也不证明所有分支都已覆盖。

自主权分 read / write / danger。执行器检查 danger 的 action_id 是否登记，但不统一取得人工确认。
已接线的删除流程由 maintenance 调确认门；登记动作与真实确认不是同一件事。
授权加固与能力定义收敛见 D-05、R-01。

## 5. 学习数据关系

| 对象 | 当前形式与限制 |
|---|---|
| 目标/容量 | 顶层字段；目标主要是一个 learning_goal 字符串；偏好缺少采集写入链路 |
| 测评 | assessment_progress.plan / records / finished |
| 路线图 | roadmap，包含 milestones 与 current_milestone |
| 执行窗口 | current_window，包含 unit / length / milestone_id / days[].tasks[] |
| 当前任务 | today_task，按 plan_progress 的 day/task 位置取出 |
| 提交与判定 | pending_submission、latest_result、latest_result_applied |
| 长期证据 | evidence，按知识点文本组织，带来源、时间、序号、任务位置 |
| 派生视图 | skill_profile、weak_points、待复验项 |
| 对话与摘要 | conversation_history、conversation_archive、rolling_summary、session_summaries |

路线图与窗口生成使用画像渲染文本。现有重估信号是验收尝试次数 / 任务总数，用于缩放后续 sessions_est。
窗口走完会进入下一里程碑并生成新窗口；代码沿用原确认标志，不再次询问。是否属于实质计划变更需按 PRD 审查。
每个任务时长被钳制，但执行单元的总时长尚无统一约束。

知识点以生成文本作为身份，测评 topic 与验收 theme/goal 可能不一致；任务 ID 只有 day-task，跨窗口重复。
这些是当前数据模型限制，不能将证据链描述为已具备稳定全局关联。

## 6. 模型与对话上下文

Settings 集中配置模型、API 地址、温度和凭据；client.json_call 与 client.chat 是统一调用入口。
JSON 模式后由各服务清洗或局部校验。PerceptionResult 携带 kind / payload / ok / needs_confirm / raw / error。
空对象或字段默认值仍可能被接受；调用成功不能直接解释为有效判定。

对话输入顺序：阶段提示词 → 可选检索资料 → 滚动/历史摘要 → 选取的原文历史 → 当前权威状态 → 用户输入。
权威状态在历史之后；对话角色使用 stage_before。判定结论应来自结构化结果，不能由自由对话替代。
护栏按短语清单删句、舍弃摘要补充或追加提醒；它不提供任意语义注入的全面防御。

对话、生成与判定服务各有失败兜底。测评故障仍会写 missing 并被聚合；验收故障通常返回失败、不更新结论。
不能宣称所有故障都会保持原阶段且不污染画像。

## 7. 存储、记忆和观测

目标设计已确定为 Way 作用域下的四模块，见 [目标记忆架构](memory-architecture.md) 及 [ADR-007](adr/0007-memory-management.md)。尚未实现；下文继续记录当前代码，现有回取函数不等同完整上下文查询或 Router。

物理状态是 data/user_state.json 单文件；zones.py 是逻辑归区，并未重构为嵌套四区。
schema_version 与迁移登记表存在；迁移每次运行并依靠幂等性，不是按版本统一跳过。
常规 save_state 使用临时文件 + fsync + os.replace；reset 的 save_to 仍直接写文本，两条路径行为不同。

记忆参数与处理见 [记忆设计](memory-design.md)。有界保留会裁剪原文和降采样证据，不能承诺全部明细永久无损。
/reset 清原文与归档，尚未清摘要；/reset all 重置状态但保留备份及独立诊断日志，不能宣传为彻底擦除个人数据。

CLI 显式开启 metrics 和 trace。事件汇总的 P95 当前来自单次 LLM 调用，尚非整轮端到端延迟。
trace 记录输入和回答；涉及个人内容。异常中断时完成事件与收尾不一定执行，尚无整轮事务与统一恢复机制。
