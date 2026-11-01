# 产品验收覆盖映射

2026-11-01：Workflow/Agent 与产品数据所有权已拆分，见 [产品系统设计](system-design.md)。现有 AC 行为要求不变，AC-30～35 改由各数据所有者与上下文服务联合满足；旧综合记忆总入口不再作为验收前提。本轮仅改设计，未增加实现或测试通过证据。


核对日期：2026-10-13。对象：当前 App_landing 工作区，含既有未提交修改。
规格同步：2026-10-14。后续决策只更新 AC 要求及缺口，既有测试/样本静态核对日期仍为 2026-10-13，未因此增加执行证据。
规格来源：[PRD 第 7 节](PRD.md#7-产品功能验收案例)。实现状态见 [交付清单](delivery.md)，实际执行结果见 [验证报告](validation.md)。

本次静态阅读测试函数的输入、断言、桩替换及评测 dev 样本内容；未执行测试、未调用真实模型、未修改测试或评测数据。
测试引用用文件和函数名定位，不依赖测试名称推定行为。评测样本存在不代表已跑或人工标签已复核。

## 1. 读表规则

| 状态 | 含义 |
|---|---|
| 直接覆盖 | 现有证据覆盖该 AC 的全部必需行为，且没有已知规范冲突；仍需执行才有通过结论 |
| 部分覆盖 | 只覆盖该 AC 的部分条件、分支或组件，不能验收整条 |
| 缺口 | 未找到针对该 AC 核心行为的直接断言/样本；可能只有邻接组件证据 |
| 冲突 | 现有断言明确保护与新 PRD 相反的行为，需要先协调需求与实现再改测试 |

“失败/通过/未执行”是运行结果；“部分/缺口/冲突”是规格覆盖状态，两者不混用。
邻接证据仅解释已有基础，不计为该 AC 已覆盖。一个 AC 可需要代码测试、AI 评测与真实使用三类证据。
本表中的 U/E 是本映射的证据索引，不新增业务需求编号；后续不据静态匹配计算发布通过率。

## 2. 逐条覆盖映射

| AC | 需要验证的核心行为 | 现有代码测试证据 | 现有 AI 评测证据 | 覆盖状态 | 主要缺口/关联待办 |
|---|---|---|---|---|---|
| AC-01 | 自评/期限为空仍可明确目标并继续 | U-01 断言缺期限阻塞；每周次数可空只属邻接 | E-01 仅画像抽取，不运行目标放行 | 冲突 | 旧四项必填与 BR-01 相反；补目标达成标准/自评可空；C-01 |
| AC-02 | 模糊目标每轮最多两问，不直接生成泛化课程 | U-02 只断言若干提示词，不检查提问数或模糊输入整轮 | E-01 的 DEV-PE-02 只检查未知字段，不检查回复 | 缺口 | 加整轮分支断言与澄清对话质量样本；C-01/C-09 |
| AC-03 | 未确认不执行，同时完整解释安排 | U-03 直接断言未确认守卫与字符串 false；U-04 只检查执行顺序 | E-02 对初始计划确认分类有样本 | 部分覆盖 | 缺目标关系、标准、时间展示与完整整轮“不下发任务”核验 |
| AC-04 | 讲解/练习/反馈总量不超预算、不虚改或抬高时长，预计超时可选择继续/暂停 | U-05 只钳单任务；U-06 明确要求 5 分钟抬到 15 分钟 | — | 冲突 | 三类活动总量、实际拆分、保留原预算及超时选择未覆盖；D-06/07 |
| AC-05 | 判定绑定实际 Q1，不受本轮新文字影响 | U-07 只核对对话阶段，不核对测评题目传参 | E-03 直接传入固定题目，绕过 executor 时序 | 缺口 | 新增 Q1/Q_NEW 错配回归及题目版本关联；D-01/11 |
| AC-06 | 提问/提示不算提交，不消耗测评题 | U-08 在学习任务识别与守卫上部分覆盖；live 用例本次未执行 | E-04 的 DEV-SD-02/03/05 检查提问/提示为非提交 | 部分覆盖 | 没有测评阶段追问不记 records 的验证；缺多轮歧义 |
| AC-07 | 测评 API 失败保留原作答、不记零分、不消耗题 | U-09 是提交识别/任务验收异常，不能代替测评异常 | —；E-03 只比判定标签，不验证失败后状态 | 缺口 | 已有内存复现表明违反要求；补连续故障及重试不丢作答；D-02 |
| AC-08 | 空/残缺/错配判定不写证据、不推进，可重试 | U-09 覆盖 RuntimeError/无 Key 后不写验收结果 | —；E-05 不含模型空输出或错配场景 | 部分覆盖 | 缺空对象、缺字段、题目/版本不一致与同提交重试；D-04/11 |
| AC-09 | 有答案辅助完成不能成为独立应用/掌握 | U-10 明确把 completed 映射到 mastery=1.0，未输入帮助程度 | —；E-05 未带帮助字段 | 冲突 | 需帮助程度记录与分层证据；不能沿用完成度→掌握度断言；C-05 |
| AC-10 | 无交互不结束；退出/实际中断后返回新会话接续原任务/提交；跨日、游标与单次 API 失败不自动切分 | U-11 核对状态注入/原待提交分支；U-12 仅存储组件 | — | 部分覆盖 | 缺无交互/跨日/API 失败不切分、真实边界及保存→重载→返回整链；C-02/D-11 |
| AC-11 | 同一提交重复处理不重复证据/推进/尝试计数 | U-13 仅正常推进一次；摘要记录幂等是另一对象 | — | 缺口 | 缺提交/判定唯一身份和重复应用故障注入；D-11/12 |
| AC-12 | 已定优先级与时间排序，每会话自动至多一个任务，可覆盖多个相关知识点；告知、计预算、不覆盖原待办；逐点判定与检查 16 小时，跳过不补发 | U-14 只验证序号阈值和提示词；U-15 以计划 day 推会话序号 | — | 部分覆盖 | 缺候选排序/多知识点部分完成与逐点证据、会话限额/告知/跳过/预算及原待办、16 小时/时间未知边界；C-02/04 |
| AC-13 | 争议、纠正与原证据关联且不新增错误掌握结论 | — | — | 缺口 | 缺争议状态、补充证据、纠正链与人工复核；C-07/D-11 |
| AC-14 | 改目标/实质重建拒绝不执行，授权绑定版本 | U-16 确认门通用拒绝/取消及删除路径保持状态 | E-02 的拒绝初始计划仅邻接，不是变更授权 | 部分覆盖 | 目标/计划变更业务路径未接线；缺版本及过期授权；C-03 |
| AC-15 | 缩短预算或暂停后返回，保留进度且新量符合预算 | —；U-05 仅单任务上限，非调整会话 | — | 缺口 | 缺暂停/继续、容量修改、原提交保留；C-03/D-06/07 |
| AC-16 | 综合任务逐项覆盖必需标准，缺项补验，全部有独立证据可达成、不等复验；关键复验失败补强 | U-17 现有窗口滚动断言直接标记里程碑 done | — | 冲突 | 缺综合任务逐项证据/缺项补验、未复验不阻塞、失败补强及主动停止；C-06 |
| AC-17 | 合法已登记动作无授权仍被统一执行入口拒绝 | U-18 只验证登记/级别，danger 循环当前空转 | — | 缺口 | 不能以动作登记测试替代授权测试；补注册合法但无/过期确认；D-05 |
| AC-18 | 清对话时原文/归档/摘要均不再注入，并说明保留证据 | U-19 验证消息清空、画像保留和写回，未置入摘要 | — | 部分覆盖 | 摘要清除与“清除后再构建上下文”断言缺失；已确认 D-03 |
| AC-19 | 用户理解备份/trace/API 去向与彻底删除边界 | U-20 只证明备份存在及保留数，不检查对用户说明 | — | 缺口 | 缺删除说明、范围理解任务与手动删除文档核验；O-06 |
| AC-20 | 资料不足说明边界，外部注入不改状态，不编引用 | U-21 只处理回复/摘要短语，非外部资料指令 | E-05 的 DEV-EV-05 覆盖用户提交中诱导满分这一子情形 | 部分覆盖 | 缺网页/检索注入、伪造来源、资料不足与状态不变；C-09 |
| AC-21 | 一条合格独立表现即可展示并注明来源与数量；结果与证据分开，待复验不降级，无总体掌握分数 | U-22 核对证据元数据与画像渲染，非完整回顾 | — | 部分覆盖 | 缺单条成立条件/显示阈值、帮助/争议输入、待复验不降级与实际回顾输出；C-05/06/07 |
| AC-22 | 每逻辑调用含首次最多 5 次请求、总等待最多 120 秒，可取消；终止/被替代请求迟到结果不应用，保留已保存结果及任务/提交 | U-12 仅成功保存/坏文件处理；U-23 仅模型错误 trace 与采集失败 | — | 部分覆盖 | 缺次数/跨层/120 秒边界/错误分类/取消与迟到竞态、新旧调用隔离、保存中断及恢复幂等；D-08/12 |
| AC-23 | 目标资料库、真实来源与计划支持关系、失败/未读说明 | —；现有本地检索只是邻接能力 | — | 缺口 | 未建立新流程验收证据；C-13 |
| AC-24 | 矩阵范围确认、能力标准/前置与测评覆盖、初始画像 | —；既有大纲和判卷不覆盖完整确认流程 | — | 缺口 | 未建立新流程验收证据；C-14 |
| AC-25 | 计划自审核、退回修订、版本化展示与用户确认 | —；既有计划确认不能替代自审核 | — | 缺口 | 未建立新流程验收证据；C-15 |
| AC-26 | 待确认验收/争议不推进，确认只应用一次且不升级独立性 | —；既有结果应用幂等不能替代用户验收确认门 | — | 缺口 | 未建立新流程验收证据；C-16 |
| AC-27 | 学习后摘要/能力/偏好分开更新，失败可见并恢复 | —；既有记忆测试不覆盖完整收尾更新协议 | — | 缺口 | 未建立新流程验收证据；C-17 |
| AC-28 | 7 天周期按证据回顾、避免重复，新/改计划重审并确认 | —；计划窗口推进不是按经过时间回顾 | — | 缺口 | 未建立新流程验收证据；C-18 |
| AC-29 | 局部循环合法行动、反馈决策、有限执行、暂停恢复与权限 | —；现有矩阵与能力检查不覆盖动态循环 | — | 缺口 | 新规格尚未建立执行证据；C-19 |
| AC-30 | Router 类型/来源/Way 准入，不升级摘要与故障 | — | — | 缺口 | 尚无 Router；C-20 |
| AC-31 | 按目标/任务/消息读取原文，缺失与超限处理 | —；现有 select_history 只选最近消息 | — | 缺口 | 无稳定消息引用和任务级回取；C-21/22 |
| AC-32 | L1→L2 移交关键接续信息，未处理原文不丢出上下文 | —；现有局部摘要测试未保护此链路 | — | 缺口 | D-14/15；C-22/23 |
| AC-33 | 按类型处理冲突/争议、版本一致性与派生失效 | — | — | 缺口 | C-21；旧单槽更新非完整协议 |
| AC-34 | 依赖清理、索引/派生同步、删除不复活 | —；现有 reset 测试不能覆盖生命周期 | — | 缺口 | D-03/16/17；C-23 |
| AC-35 | 工作记忆回收与评估记录分开，失败不污染能力 | —；已有 metrics/trace 不覆盖该协议 | — | 缺口 | C-23；详细 Agent 评估协议另定 |

覆盖登记：原 AC-01～22 的静态统计为直接覆盖 0、部分覆盖 10、缺口 8、冲突 4；本轮新增 AC-23～28 均登记为缺口，尚未逐项重新审计或执行。局部 ReAct 决策另新增 AC-29，登记为缺口。四模块记忆顶层设计新增 AC-30～35，暂登记为缺口，未新增执行证据。现共 35 条：直接覆盖 0、部分覆盖 10、缺口 21、冲突 4。
这表示尚不能用现有证据完整验收任一整条 AC，不表示已有测试没有价值，也不是当前测试通过率。

## 3. 代码测试证据索引

定位形式为文件链接 + 精确函数名，后续改动应按实际函数和断言重新核对。
下述都是静态已读的断言范围，本次运行结果统一为“未执行”。

| 索引 | 文件与函数 | 断言的实际边界 |
|---|---|---|
| U-01 | [test_profile.py](../tests/test_profile.py)：`test_stage_guard_blocks_incomplete`、`test_sessions_per_week_does_not_block_completeness` | 缺期限阻塞；每周次数可空，但自评/期限仍存在 |
| U-02 | [test_stages.py](../tests/test_stages.py)：`test_stage_prompts_encode_key_rules` | 只断言测评/计划等提示词词句，不执行模糊目标澄清 |
| U-03 | [test_plan.py](../tests/test_plan.py)：`test_guard_requires_confirmation`、`test_confirm_plan_rejects_string_false` | plan_confirmed 放行与 false 归一；不证明计划展示完整 |
| U-04 | [test_dialogue.py](../tests/test_dialogue.py)：`test_step_order_planning_unconfirmed` | 桩调用记录顺序，不能替代完整未确认流程效果 |
| U-05 | [test_plan.py](../tests/test_plan.py)：`test_normalize_plan_data_clamps_overlong_tasks`、`test_normalize_plan_drops_tasks_without_done_criteria` | 逐任务改 minutes、丢缺标准任务；同单元总量及实际工作量未测 |
| U-06 | [test_memory.py](../tests/test_memory.py)：`test_clamp_session_minutes_bounds` | 明确将 5 抬到下限 15，属于与新需求冲突的断言 |
| U-07 | [test_dialogue.py](../tests/test_dialogue.py)：`test_coach_uses_turn_start_stage_not_advanced_stage` | 学习阶段回复提示词选择，非测评判定输入关联 |
| U-08 | [test_daily.py](../tests/test_daily.py)：`test_live_submission_detection`、`test_guard_requires_submission`、`test_detect_submission_without_llm_keeps_state` | 学习任务中的提问/代码识别、提交守卫、无 Key；不覆盖测评追问 |
| U-09 | [test_perception.py](../tests/test_perception.py)：`test_failed_judgement_keeps_stage_and_writes_nothing`、`test_evaluation_failure_does_not_write_latest_result`；[test_evaluation.py](../tests/test_evaluation.py)：`test_evaluate_without_llm_keeps_state` | 前两者分别是提交识别与任务验收异常；第三者无 Key；不是所有无效输出 |
| U-10 | [test_evaluation.py](../tests/test_evaluation.py)：`test_mastery_is_derived_from_completion` | completed 被断言为 mastery=1.0，无帮助程度区分 |
| U-11 | [test_dialogue.py](../tests/test_dialogue.py)：`test_authoritative_state_message_follows_history`、`test_step_order_learning_with_pending_submission` | 状态注入位置、已有提交的单轮分支；没有跨进程保存/重载 |
| U-12 | [test_reset.py](../tests/test_reset.py)：`test_save_state_is_atomic`、`test_load_state_keeps_a_copy_of_broken_file`、`test_load_state_upgrades_nested_plan_progress_attempts` | 保存成功后的文件与临时文件检查、损坏留底、迁移；不模拟写入中断，不证明恢复原任务 |
| U-13 | [test_daily.py](../tests/test_daily.py)：`test_mark_task_done_advances_and_clears`；[test_evaluation.py](../tests/test_evaluation.py)：`test_apply_update_pass_advances_cursor` | 正常推进；未对同提交重复应用。摘要幂等见第 5 节 |
| U-14 | [test_memory.py](../tests/test_memory.py)：`test_topic_becomes_due_after_n_uncovered_sessions`、`test_review_hint_lists_due_topics_only` | 序号阈值与提示词列表，不是复验任务及实际回访 |
| U-15 | [test_memory.py](../tests/test_memory.py)：`test_day_boundary_opens_exactly_one_new_session` | 计划 day 推动 session_seq；真实学习会话尚未建模 |
| U-16 | [test_confirmation.py](../tests/test_confirmation.py)：`test_denied_blocks`、`test_timeout_blocks`、`test_confirm_fn_exception_is_fail_closed`、`test_reset_history_denied_leaves_state_untouched`、`test_reset_all_denied_keeps_profile_and_plan` | 通用确认函数与删除用例；不是改目标/重建计划和版本授权 |
| U-17 | [test_plan.py](../tests/test_plan.py)：`test_roll_window_moves_on_and_recalibrates` | 完成位置后推进，断言首里程碑 done 和延续确认标志；不核对阶段能力标准 |
| U-18 | [test_capabilities.py](../tests/test_capabilities.py)：`test_enabled_danger_capabilities_have_registered_action`、`test_ensure_allowed_combines_level_and_registration` | 前者当前无启用 danger 能力，循环空转；后者仅登记和级别 |
| U-19 | [test_reset.py](../tests/test_reset.py)：`test_clear_history_counts_and_clears`、`test_reset_history_keeps_profile_plan_and_stage`；[test_confirmation.py](../tests/test_confirmation.py)：`test_reset_history_approved_clears_and_saves` | 消息清空、状态保留、持久化；fixture 不含需清掉的叙事摘要 |
| U-20 | [test_reset.py](../tests/test_reset.py)：`test_reset_all_restores_defaults_and_backs_up`、`test_backup_prunes_to_keep_limit` | 备份存在/内容/保留数量，不证明用户知道保留范围 |
| U-21 | [test_guardrails.py](../tests/test_guardrails.py)：`test_turn_strips_the_models_verdict_announcement`、`test_summary_supplement_with_judgement_words_is_dropped` | 少数短语输出处理；非外部指令隔离或来源正确性 |
| U-22 | [test_memory.py](../tests/test_memory.py)：`test_evidence_carries_source_time_and_session`；[test_dialogue.py](../tests/test_dialogue.py)：`test_render_profile_covers_all_dimensions` | 证据字段/部分画像文本；未验证帮助、争议、证据时间的回顾展示 |
| U-23 | [test_trace.py](../tests/test_trace.py)：`test_llm_failures_are_recorded_with_their_error`、`test_write_failure_is_swallowed` | LLM 异常上报、trace 写失败；trace 存储不是用户 state 保存 |

U-08 含 live 用例，缺 Key 时跳过；其他 live 测试尚有 D-09 接口漂移，不能拿历史跳过读数证明有效。
本索引不穷举全部测试，只收与本次 AC 直接或邻接相关的可解释证据。

## 4. AI 评测样本索引

### 4.1 开发集

来源：[dev.jsonl](../evals/dataset/dev.jsonl)。本次只做样本内容与 compare 字段核对，未跑模型、未修改标签。

| 索引 | 样本 ID | 实际评价范围 | 可关联与不能证明的内容 |
|---|---|---|---|
| E-01 | DEV-PE-01～04 | profile_extract：目标/水平关键词、分钟数、期限 | AC-01/02 邻接；不能证明可选字段放行、提问数量或目标达成标准 |
| E-02 | DEV-PC-01～05 | plan_confirm：初始计划同意、要求修改、含糊、询问依据 | AC-03 部分；AC-14 仅邻接，不验证变更版本或动作执行授权 |
| E-03 | DEV-AV-01～08 | assessment_verdict：固定题目和答案的 mastered/partial/missing 标签 | AC-05 仅邻接；绕过单轮题目传参，不覆盖 API 故障和状态推进 |
| E-04 | DEV-SD-01～05 | submission_detect：代码/文字作答、问题、含糊状态、提示请求 | AC-06 的学习任务识别部分；DEV-SD-02/03/05 为非提交，没有测评追问流程 |
| E-05 | DEV-EV-01～08 | evaluation_completion：完成度与 next_action | DEV-EV-05 对 AC-20 的用户提交诱导判满分部分直接相关；不检外部资料、帮助程度、错配或持久化 |

本轮静态核对 dev 共 30 条，5 个 judge。现有 runner 主要比较标签/布尔值/抽取字段，
不会据此检查用户看到的回复、跨次进度、证据写入、来源准确性或整个 AC 的行为。
旧标签/mastery 概念与新 PRD 证据分层需在后续数据修订中审查；本次不改数据集。

### 4.2 独立验收集

来源：[holdout.jsonl](../evals/dataset/holdout.jsonl)。本映射仅按元数据登记候选，不根据答案内容作覆盖结论，也不据其调整提示词或标签。

| judge | 样本 ID | 可登记范围 |
|---|---|---|
| assessment_verdict | HO-AV-01/02 | 同 E-03 的服务判定类别，不能证明题目时序和故障恢复 |
| evaluation_completion | HO-EV-01/02 | 同 E-05 的完成度类别，不能证明帮助分层 |
| submission_detect | HO-SD-01/02 | 同 E-04 类别；具体 AC 覆盖在正式独立验收时审查 |
| plan_confirm | HO-PC-01 | 初始确认类别，不计目标变更授权覆盖 |
| profile_extract | HO-PE-01 | 画像字段类别，不计澄清流程覆盖 |

本轮登记 8 个 ID，未执行正式验收，未批准结果。“有 holdout 样本”不等于所有 AC 有独立验收。
正式使用仍按 evals 的 --allow-holdout 规则与防调参泄漏约定执行。

## 5. 四类容易误判的覆盖

1. 提示词出现规则，不等于模型执行规则。U-02 不证明每轮只问两问；U-21 不证明任意注入能阻断。
2. API 异常返回失败，不等于所有模型输出有效性已检查。U-09 不涵盖空 JSON、错误对象身份与缺字段。
3. 某个对象幂等，不等于所有业务幂等。`test_session_record_upsert_is_idempotent` 只对摘要/会话记录去重，不是 AC-11 的提交/判定去重。
4. 测试名字描述保障，不等于断言达到该保障。U-12 的 atomic 测试只走成功写入路径，没有模拟写到一半失败；U-18 的 danger 声明测试循环当前为空。

冲突断言不能为提高通过数直接删掉：先批准新规则，新增失败复现，再改实现并更新旧断言，保留原风险的必要保护。
目前没有完整运行结果，不能用本表的静态状态计算 M-02 通过率。

## 6. 人工与真实使用证据缺口

以下均“未执行”。人工记录需关联 AC、目标/会话/任务身份、模型配置和观察边界。

| 场景 | 对应 AC | 应补的观察证据 |
|---|---|---|
| 首次设置与计划理解 | AC-01/02/03 | 用户能复述目标、任务标准及时间；不必自评或设置期限 |
| 中断后实际返回 | AC-10/15/22 | 用户无需重述目标，原提交被正确处理；异常恢复点如实说明 |
| 提示辅助与新任务 | AC-09/21 | 用户知道辅助记录与能力结论的边界；未见同类任务表现分层 |
| 主动复验与跳过 | AC-12 | 真实后续会话、预算占用、知识点关联和跳过后状态 |
| 质疑、目标改变和停止 | AC-13/14/16/17 | 能拒绝/取消，纠错不丢旧证据，旧授权不能复用 |
| 删除理解与来源信任 | AC-18/19/20 | 用户理解保留项/API 去向，引用支持内容，资料不足不伪装有依据 |

学习收益还需按 PRD 1.0 第 8.3 节观察：项目作者同一目标至少 5 次实际会话、至少 7 天，含中断返回及至少间隔 16 小时的独立复验，记录起点和未见可比任务表现；先测基线，不设提升硬门槛。协议未执行，不能由一次可用性检查或单人观察推出普遍收益与因果增量。

## 7. 补证据顺序与维护

1. 优先 D-01～05：AC-05/07/08/17/18 的故障、错配、授权、清理回归；先将既有内存复现变成可维护测试。
2. 协调冲突：AC-01/04/09/16 对应 U-01/06/10/17；按 PRD 的 BR-01/02/04/10 调整契约和实现，再更新旧断言。
3. 补状态关联与恢复：AC-10/11/22，验证真实保存/重载及同结果重复处理。
4. 补持续学习流程：AC-12/13/15/16/21；按已确定 O-02/O-05 验证证据分层、16 小时间隔、综合任务覆盖与不等待复验，以及自动排序/每会话单任务/多知识点逐点留证。
5. 扩展 dev：澄清提问数与目标理解、测评追问、辅助分层、资料不足与检索注入；不要把纯代码失败全部交给真实模型评测。
6. 执行确定性回归、真实模型分层评测和人工任务，分别在验证报告记录，不把三种结果混算。

维护责任：改 AC 时复核本表；改测试时核对实际断言；改数据时更新 ID 和比对范围。
每次正式验收绑定代码状态与规格版本；已失效引用改为撤销或替代，不把“相关”自动升级为“直接覆盖”。

## 本轮验收资料补充

新增 workflow-scenarios 与 35 条 AC 一一对应，字段为 given/when/expected/execution；这是可供后续自动化与人工执行的场景规格，不是测试断言或通过证据，原覆盖分类不因此升级。acceptance-candidate 含五 judge 各 6 条、共 30 条未复核样本，不能当作已合格的独立验收集。
Prompt catalog 的 AC 关联是用途映射，不证明对应 AC 已实现。真实新增的离线设施测试与旧回归运行结果单独登记在验证报告。计划来源、自审核、工具选择、上下文与周期回顾还需应用级验收，不由五 judge 分数替代。
