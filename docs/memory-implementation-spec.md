# 记忆管理开发规格

版本：1.0；日期：2026-10-14。状态：设计完成、待开发；统一测试入口已由项目负责人确认。依据：PRD O-09、AC-30～35，ADR-004/006/007。
本文按 to-spec 的开发规格结构编写。描述目标实现，不代表代码已修改或验收通过。技术默认值属于本规格的实现起点，必须在实际使用后调整，不新增学习效果或正常响应硬门槛。

## Problem Statement

学习者需要围绕同一目标跨会话接续，得到可追溯的反馈，同时能够纠正、清除错误或无用记忆。当前系统将对话、证据和派生画像混合保存，已有压缩与归档却缺少任务级回取、统一准入、依赖清理和实际会话身份；会发生摘要引入错误、接续信息丢失、存储裁剪失效等问题。
局部 ReAct 还需要保存行动反馈与暂停点；其临时工具记录不应进入学习能力画像，也不应在清理时连带抹掉评估所需执行事件。

## Solution

以当前学习路径 Way 为作用域，提供统一的记忆协调入口，内部由 Router、存储、上下文组装与注入、生命周期管理协作。业务模块提交带来源的事件，由确定性规则筛选、关联并保存；读取根据当前任务取有效记录和必要原文；清理根据用途、依赖及用户请求执行。
1.0 单用户、单 Way、单进程写入，继续采用单个 JSON。四模块不分成四份独立事实库。自然语言提取和摘要模型只产生候选，不具有直接更新能力证据、确认或进度的权限。

## User Stories

1. As a learner, I want memories to belong to my current learning goal, so that unrelated information does not affect my learning.
2. As a learner, I want my goal to persist across sessions, so that restarting the program does not restart my learning.
3. As a learner, I want explicit preferences to be recorded with their sources, so that I can correct them.
4. As a learner, I want temporary requests separated from lasting preferences, so that today's choice does not silently change future lessons.
5. As a learner, I want inferred preferences identified as candidates, so that guesses do not override my statements.
6. As a learner, I want mixed messages to produce separate relevant records, so that my preferences and questions are both understood.
7. As a learner, I want task judgments tied to my actual submission and rubric, so that feedback concerns the work I submitted.
8. As a learner, I want assistance recorded separately from completion, so that assisted success is not presented as independent ability.
9. As a learner, I want system failures excluded from ability evidence, so that outages do not lower my profile.
10. As a learner, I want disputed results identified, so that uncertain judgments do not silently guide future learning.
11. As a learner, I want corrections reflected in dependent summaries and plans, so that old errors stop influencing the system.
12. As a learner, I want unfinished tasks and pending confirmations preserved, so that interruptions are recoverable.
13. As a learner, I want summaries to retain unresolved questions and constraints, so that compression does not lose my next step.
14. As a learner, I want the coach to retrieve relevant original messages, so that it can verify details instead of guessing.
15. As a learner, I want missing or deleted originals identified, so that the coach does not claim to have verified unavailable material.
16. As a learner, I want oversized submissions handled explicitly, so that partial reading is not presented as complete assessment.
17. As a learner, I want repeated processing to be harmless, so that retries do not duplicate evidence or progress.
18. As a learner, I want older background results prevented from overwriting new decisions, so that my latest valid choices remain effective.
19. As a learner, I want redundant and obsolete memories cleaned up, so that unnecessary history does not accumulate indefinitely.
20. As a learner, I want necessary evidence protected during automatic cleanup, so that current conclusions remain supportable.
21. As a learner, I want deletion requests honored across derived memories, so that deleted content does not return through summaries.
22. As a learner, I want retained learning evidence explained when I clear conversation memory, so that the scope is understandable.
23. As a learner, I want recovery after a failed save, so that unsaved work is not falsely reported as saved.
24. As a learner, I want legacy history migrated without invented timestamps or independence, so that old data remains honestly described.
25. As an agent operator, I want interrupted local runs resumed from explicit action state, so that actions are not blindly repeated.
26. As an agent operator, I want temporary memory cleanup separated from evaluation events, so that tool failures remain measurable.
27. As a developer, I want one behavioral test interface, so that internal refactoring does not require rewriting business tests.
28. As a developer, I want clear rejection and recovery results, so that callers can handle incomplete work without inspecting storage internals.

## Implementation Decisions

### 1. 模块与统一入口

模块名为 MemoryCoordinator、MemoryRouter、MemoryStore、ContextAssembler、MemoryLifecycle。协调入口只编排四模块，不实现第二套分类或评分规则。对业务调用方公开三种操作：

| 操作 | 输入 | 输出与副作用 |
|---|---|---|
| ingest：接收事件 | 可信执行上下文、事件身份/类型、内容与来源引用、预期版本 | 接收/拒绝/待核实/重复/冲突/保存失败；成功时原子提交记忆变化，不能任意修改业务进度 |
| context：按任务读取 | Way、任务用途、必需对象引用、预算与读取快照 | 完整或不完整的 ContextBundle，携带版本、来源、缺失项、截断说明；不修改存储 |
| maintain：生命周期处理 | 可信触发原因、范围、预期版本，用户动作还需对应确认凭据 | CleanupResult：合并/删除/失效/保留数及原因；通过统一提交执行，不增加用户清理入口 |

内部 Router 和 Lifecycle 生成 ChangeSet，Store 校验并提交。协调入口捕获可恢复错误并返回结构化结果；损坏 schema 等不可恢复错误禁止继续覆盖原文件。
保留现有模型调用接口；存储接受可注入的时钟、ID 生成器和持久化适配器，测试使用内存适配器与模拟落盘失败。业务规则和能力注册表仍负责阶段推进及授权。

### 2. 物理结构、唯一事实来源与索引

沿用单文件 JSON。目标 schema 在当前版本 18 基础上升为 19；实际开发时若已有其他迁移占用该号，则使用下一可用版本，不覆盖已有迁移。
顶层增加 revision、单个 way 元数据、memory。way 只保存当前路径身份、创建时间、目标版本；不提前建立多路径字典或切换接口。现有目标/计划/任务字段继续由业务模块拥有。
memory 内包含 records、sessions、runs、views 和 generations。records 为记录 ID 到类型化记录的映射；sessions/runs 为实际会话与局部执行的运行状态；views 是可重建的当前偏好、能力证据引用和摘要引用，不复制原文。generations 保存删除/重置代际；外部评估持久化由独立评估模块负责，不在记忆内复制其数据集。
迁移完成后对话和摘要等旧字段通过兼容读取函数临时投影，不在文件中双写两份正文；各消费方适配完成后才能切换 schema。业务中既有数值画像可以留为明确标记的旧兼容视图，不能继续以它推导新“已掌握”结论。
索引只在内存建立：记录 ID、会话/任务/能力点、类型/状态、反向依赖、事件去重键。加载或成功提交后重建/增量更新；文件中的 records 是唯一正文来源，不持久化第二套搜索正文。

### 3. 通用记录契约

| 字段 | 约束 |
|---|---|
| id / version | 新记录使用随机 UUID；版本从 1 开始，内容或有效性变化时递增；删除后不复用身份 |
| way_id | 从可信执行上下文填入，必须等于当前 Way；模型给出的其他值忽略并作为拒绝原因记录 |
| kind | 固定枚举：message、preference、evidence、summary、open_item、resource、resource_use、work_item；业务目标/授权不作为模型可写 kind |
| validity | pending、valid、disputed、invalid；它描述依据是否可用，不与保留状态混用 |
| lifecycle | active、archived、superseded；删除正文后不保留 deleted 记录副本 |
| origin | 来源类别、实际执行事件/消息/调用身份；执行层提供，模型不能声明自己是有效判定或用户确认 |
| occurred_at / recorded_at | 带时区时间；旧发生时间可为空；处理时间不能替代实际作答或题目呈现时间 |
| session_id / run_id | 实际所属会话/局部运行；旧数据无法判定时为空并保存 legacy_seq，不把旧序号等同真实会话 |
| refs / basis_versions | 相关任务/提交/量规/能力点/消息及生成所依据的记录版本 |
| operation_key | 同一执行事件生成该记录的幂等身份，系统计算；不使用仅由内容散列组成的键 |
| content | kind 专用模型，拒绝额外业务状态字段；没有必要的正文不收集 |
| provenance_status | verified、legacy_unknown 或 inferred；描述来源可追溯状态，不表示模型输出事实必真 |

任务、提交、能力点、计划和量规使用稳定业务 ID；修改内容递增版本，不能以 day-task 或生成名称充当唯一身份。同一综合任务的各能力项引用同一提交与各自量规项，不复制用户提交正文。
同一句话在不同消息出现是两次事件，不因内容相同去掉交互；同一个事件恢复重放则按 operation_key 去重。operation_key 由事件 ID、输出类型、对象和该事件内项目序号组成，覆盖生成后保存前的恢复场景。
通用记录中的来源引用可标为 unavailable；有独立留存用途的结构化偏好/证据可以保留其必要内容，但不得再声称已读取被删除原文。必须读取原文的判定仍返回不完整。

### 4. 各类型内容与保护对象

| 类型 | 必需内容与约束 |
|---|---|
| message | role、原始内容、会话内单调序号、任务/提交关联；user/assistant/tool 分开，tool 正文按工作记忆用途保存；一条消息只存一份 |
| preference | 规范化键、值、适用范围 Way 或当前会话、explicit/inferred、支持消息引用；模型推断默认 pending，不自动覆盖明确声明 |
| evidence | 实际题目/任务及版本、提交、量规项结果、帮助程度及来源、判定有效性、用户验收状态、呈现/提交时间；一任务多知识点按各量规项关联，不整题自动升级 |
| summary | scope 为 rolling/session，覆盖的消息 ID、过程事实引用、open_item 引用、来源完整性、压缩游标；不含可执行授权或新的能力判定 |
| open_item | 未解决问题/待办/约束的内容、来源、状态 open/resolved/cancelled 及归属；独立保存，不只埋进摘要 |
| resource | 原始/规范化 URL、标题、实际取回内容、内容指纹、检索时间、访问状态；取回内容不等于已核验其支持计划 |
| resource_use | 资料、计划/任务版本、能力点及采用理由；与资源正文分开，允许一个来源用于多个任务 |
| work_item | 运行内步骤、动作/参数引用、执行结果引用、pending/running/succeeded/failed/unknown、后续事项；失败只影响运行判断 |

证据引用的题目、提交和量规必须是稳定业务对象；其快照/版本一旦用于正式判断不可被原地覆盖。它们由业务状态仓储与记忆提交协调保存，不复制成聊天摘要。规划文本、资料与用户表达均作为数据，不作为工具权限。

### 5. Router 与来源准入

处理顺序为：解析可信事件 → 类型校验 → 作用域/代际检查 → 必需引用与版本检查 → 来源资格校验 → 重复和冲突检查 → ChangeSet → 提交。

| 来源事件 | 可生成的有效记录 | 拒绝或待核实情形 |
|---|---|---|
| 用户消息已持久化，抽取服务返回候选 | 与原文对应的明确偏好、open_item | 无对应引文、只是模型猜测、适用范围不明时 pending；不能直接写能力证据 |
| 判定服务返回结果，确定性契约校验通过 | 关联实际任务/提交的 evidence | 调用失败、缺字段、非有限分数、错配、缺必要题目/提交/量规时拒绝；零分仅可来自有效未完成判定 |
| 系统摘要处理 | 有覆盖记录及依据的 summary | 试图改变能力、计划确认或把未处理消息标已覆盖时拒绝/回退 |
| 工具执行完成 | resource/resource_use/work_item 中符合来源的记录 | 故障不伪装有效资料，不产生学习能力证据 |
| 迁移适配器 | legacy_unknown 的已有记录 | 不补造独立性、题目、提交、原会话或来源核验 |

业务确认事件只供原业务规则验证，Router 可保存关联，不自己设置计划生效或任务完成。候选中的 trusted/validated/confirmed 字样没有权限含义。待核实内容不进入普通有效偏好视图，不被默认注入；其原始用户消息仍可作为带角色的原文读取。
证据写入与推进分开：有效判定可先保存 awaiting_user_acceptance；用户明确确认该结果版本后，业务规则在同一提交中应用/推进一次。有争议记录可保留，但不新增独立能力结论。

### 6. 写入事务、恢复与迟到结果

应用启动时取得唯一写实例的进程级锁，进程结束由操作系统释放；第二个写实例返回 writer_busy，不依赖永久残留的锁文件判断进程是否存活。1.0 只支持本机单进程，采用 OS 锁适配器，不宣称支持网络盘或分布式锁。
单进程内所有提交串行。模型与网络调用不持有提交锁；它们捕获 Way、相关代际、运行/请求身份和输入记录版本，结果返回时先检查调用仍有效。

一次提交执行：

1. 读取已提交快照，检查预期 revision、Way、代际及所依赖版本。
2. 在副本应用记忆 ChangeSet 和经业务规则批准的相关变更，检查引用、schema、重复应用及清理不变量。
3. 将新 revision 的完整候选状态写入同目录唯一临时文件，flush/fsync 后原子替换。
4. 替换成功才公布新内存快照和索引；失败返回 save_failed，已提交状态保持不变，候选保留供明确恢复，不伪报成功。

revision 冲突时不盲目重放模型结果。若仅无关记录变化，重新核对所有依赖后可由协调入口重新建立 ChangeSet；Way/删除代际变化、被取消/超时/取代的请求或相关输入变化，返回 stale_result 并丢弃输出。重新调用属于新运行，沿用现有网络次数/时间规则。
启动时只加载正式状态文件；遗留临时文件不自动当作成功提交。文件有效但新旧 revision 不明时停止恢复并说明，不自动退回已删内容的备份。文件损坏先隔离，再进入显式恢复/初始化流程；迁移失败禁止覆盖原件。
操作幂等信息与目标记录同时提交。已应用提交由业务对象的 applied 标记/版本长期守护，不依赖可被裁剪的诊断日志；普通消息/摘要使用存活记录及压缩游标去重，完成运行关闭后拒绝旧事件，不无限保存事件 ID 列表。

### 7. 实际会话和运行身份

实际开始学习创建 session_id 和 started_at；显式结束、暂停、进程退出结束当前会话，异常退出则在返回时标记 interrupted 并创建新会话。无交互、跨日、计划游标移动和单次 API 失败均不创建新会话。
学习结束包含用户验收确认后的正常收尾；用户主动暂停/退出也保存未完成项，不强制任务通过。摘要完成状态独立于会话结束状态，退出时未完成的摘要在下次启动补做，不能阻止退出或假装后台仍运行。
局部 ReAct 使用独立 run_id，归属当前 Way/会话；完成、等待用户、受阻或达到限制均保存退出原因。恢复已记录成功的动作不重复调用。崩溃前动作已发出而结果未知时标 unknown，读操作可在新调用下重试；有副作用动作必须检查实际结果/幂等身份，未知时不能盲重放。
16 小时复验按原有效提交到新题目首次呈现时间计算；UTC 计算间隔，显示用户时区；时间不足或未知不算保持。7 天回顾从已确认计划下第一次正式学习会话的 started_at 起算，每 7×24 小时一个边界，UTC 计算。记录 anchor、reviewed_through、review_result 和相关计划版本；长时间离开后一次回顾从上次已处理点到最新已到期边界的全部实际表现，不伪造缺席期间学习、不连续生成多份追赶计划。回顾成功保存后推进 reviewed_through；计划是否经确认激活独立记录，未确认的新计划不覆盖原计划。无学习也可保存“证据不足/保持待办”的回顾结果。返回时检查，不用旧 session_seq 计算真实时间。

### 8. 冲突、修订与依赖图

偏好使用“Way、规范化键、适用会话”作为当前值索引。同范围的明确新声明替代旧值；会话要求优先用于该会话，但不抹掉 Way 长期偏好。模型推断不能覆盖明确值；不一致的推断保留为待核实或拒绝，不自动询问所有非关键偏好。
能力证据不做文本互相覆盖，也不按新旧平均数生成新能力结论。用户自评、两次成功/失败、帮助程度分别展示；有效纠正创建新证据并标记原记录已纠正，引用原版本的派生视图失效。
依赖分三类：basis 为当前结论/未完成流程必需，reference 为可回取补充，coverage 为摘要曾处理哪些消息。只禁止自动删除有效 basis；reference/coverage 的原文正常过期后保留 unavailable 标记，读取不得声称仍可回取。
反向依赖索引在内存维护。新/改依赖必须引用已有同 Way 对象及版本，拒绝自引用/环；循环修订以新记录替代，不构造循环。修订从被改记录沿反向 basis 依赖传播：立即标记过期并退出正常读取，画像按剩余有效证据确定性重建；计划标需要重新检查，实质变更仍等待用户确认。传播与提交失败不产生半有效状态。

### 9. 原文回取与上下文组装

ContextRequest 明确用途：dialogue、plan、judge、resume、review、react。每种用途固定必需对象集合，不能由模型自由删减。ContextBundle 返回 status 为 complete、missing、oversized、stale 或 configuration_required；包含 read_revision、来源条目、缺失引用、预算估算及被省略的辅助条目。
优先级为：系统规则和本次输入 → 实际任务/提交/量规与待确认状态 → 相关有效偏好/证据/未解决项 → 相关摘要 → 原文和资料补充。不同用途改变必需集合；必需内容不因优先级低被截断。
按 ID 精确回取消息，再带同一会话前后各 1 条作为可选相邻上下文；角色和时间顺序保留，预算不足先删相邻消息，不截断目标原文。任务/能力查询先筛选，再按相关对象匹配数、事件新近性和稳定 ID 排序；关键词检索用于原文/资料，1.0 不引入向量检索。
普通历史首选软预算仍为 8000 字符，最近 6 条为偏好而非无条件豁免；最新 3 条有效定稿摘要是候选上限，不保证全部注入。业务必需内容不受此历史软预算直接裁剪，但必须计入整个模型请求预算。
请求预算由调用方提供模型 context_tokens 与 max_output_tokens，留输入容量的 10% 作工程余量；两者都必须为正且预留后可用。使用对应模型可用 tokenizer；无精确计数时使用 UTF-8 字节数加消息/工具序列化包装的保守估算，并标估算，不承诺其为模型硬上界。模型容量未知返回 configuration_required，不臆造供应商上限。服务端超限仍按上下文错误处理，不进入网络自动重试或静默裁必需内容。
必需原文过长时：先按预定义量规拆分可独立核验的项，保存各项完整来源范围与未核验覆盖。全量结构/跨段关系等必需项必须另行核验；无法在预算内完成时返回 oversized 和具体缺口，要求缩小或拆分提交，不产生完整正式判定。聚合只按全部必需项规则，不平均掩盖缺项；分段是同一提交的评估运行，不等于多次作答或新独立证据。
外部原文、摘要、工具结果以数据区块带类型和来源呈现，不能变为系统授权。重复内容按记录身份去重；有争议资料或偏好仅在需要解释争议时带标签读取，不能作为正常确定性事实。

### 10. 压缩与收尾协议

L1 触发继续采用 8000 字符历史软预算、0.7 回压比例、至少 4 条待压缩消息。模型每批输入最多 4000 字符，按消息及段落划分批次，单消息过长拆为带范围的片段；任何片段遗漏都不推进覆盖游标。
用户原文先持久化；提取形成偏好候选/open_item，模型摘要只是候选过程描述。1.0 持久化摘要的权威内容由结构化字段和有精确原文范围的摘录确定性渲染；自由润色不写入长期摘要。模型可提议选择范围，但每条摘录必须在来源中逐字存在；不以短语护栏代替来源校验。这将牺牲部分自然表达，换取摘要不编造过程事实。
压缩 ChangeSet 原子保存新的 rolling 摘要、已完整处理游标、open_item 及原文归档位置。失败时保留旧摘要与未处理原文，下轮可恢复；不把仅“调用返回成功”视作整批覆盖。
L2 收尾读取原会话的结构化证据、rolling 摘要/open_item、尚未覆盖的原文范围及待确认事项。只有覆盖信息完整移交后才将 rolling 标记已收尾；尚未解决 open_item 继续存活，不能因生成摘要清除。摘要按 session_id 唯一更新，不重复追加；session 元数据引用摘要，不再复制 summary 正文。
摘要不能先于本轮消息记录提交；轮内存储顺序由统一协调入口保证，不再依赖旧注册表中的偶然 order。摘要输入覆盖原会话，不误取游标已推进后的下一单元骨架。

### 11. 生命周期与保留配置

以下是开发默认值，不是学习效果阈值；保留旧数量参数的用途，修复原写入路径没有统一执行的问题。protect 表示有活跃 basis 或待处理依赖，自动清理不能直接删除。

| 对象 | 默认策略 |
|---|---|
| 近期原文 | 最近 160 条进入近期读取区；更早转归档，正文只存一份 |
| 归档原文 | 最近 30 个已结束实际会话，另保留当前会话与 protect 项；排序按实际会话开始时间，旧未知序号使用明确 legacy 顺序 |
| 定稿摘要 | 最近 20 个已结束会话，另保留仍服务 open_item/争议的 protect 项；会话只引用，不保存重复正文 |
| 滚动摘要 | 当前会话 1 个有效版本；收尾移交后清理无引用旧版本 |
| 学习证据 | 每能力点默认最近 5 条有效明细，另保护当前达成标准必需的独立证据、每能力点当前展示所依据的一组保持配对、待争议/纠正记录及其必要题目/提交/标准；5 是普通窗口，不强删保护项 |
| 偏好 | 每键/适用范围 1 个当前明确值；旧值无 basis 或未解决争议时下次维护删除；inferred pending 不进入当前值 |
| pending 候选 | 每 Way 最多 100 条；无引用且不影响待确认事项的最旧候选先清理，无法腾出时返回 candidate_capacity，不静默删用户待确认内容 |
| 工作记忆 | active/paused/blocked 运行保留恢复所需内容；终态的结果/来源与未解决事项转存、评估交付进入可靠队列后，下一次维护清理临时正文 |
| 参考资料 | 当前计划/任务采用的版本保护；未采用资料按最长未被当前读取使用排序回收，最后使用时间由实际读取事件更新；暂时访问失败不自动使已存内容无效 |
| 无用历史版本 | 替代关系与必要引用更新后，在成功提交后的下一次维护清理，不另设按自然日清空学习状态 |

不再使用旧的分数锚点替代独立能力依据。对无需保护的早期证据，可生成聚合统计，仅用于历史回顾且明确明细已删；聚合不产生新的独立或保持证据。已迁移的旧数值锚点保留 legacy_unknown，不升级来源。
自动清理顺序：重复/无引用旧版本 → 已交付终态工作记录 → 未采用资料缓存 → 超出窗口且无保护的原文/摘要 → 普通旧证据。删除前构造并校验完整清理计划，按同一 revision 原子提交；其中已变化的计划作废重算。
单文件工程容量保护默认 32 MiB，可配置。提交前先尝试合法清理，仍无法容纳则返回 storage_capacity 并保留上一已提交状态；不为达标删除受保护证据、不伪报保存。不是金额或学习时长限制。大资料在获取时控制候选体积，超限返回 resource_oversized；不先把整段巨大正文塞进状态。1.0 不宣称任意目标/无限内容都可无界保存。所需保护集合超过容量时明确报告依赖和占用，交由用户选择调整目标范围、导出/删除指定内容或提高本机容量配置；系统不替用户牺牲证据。

### 12. 用户删除、代际与派生处理

现有清对话操作删除原文、rolling/session 摘要及其重复副本，并使对话来源 generation 递增。保留事先说明的结构化学习证据/业务进度/偏好；其中对已删聊天的来源链接标 unavailable，不保留隐藏聊天摘录。open_item 如包含仅从聊天取得的个人内容一并清理，恢复所需业务待办从真实任务/提交状态重建。
若清对话请求的范围还包含结构化偏好、提交或证据，必须按具体请求执行更广范围删除，不能用标准 /reset 的窄范围替代。删除偏好时先取消旧值及其派生引用，再更新代际，防止旧抽取结果重新写入。
完全重置在一次提交中创建新 Way 身份、清旧记忆和原有学习状态；代际/运行身份改变，旧请求结果一律拒绝。备份和诊断日志仍按既有说明保留，不宣称彻底删除。
用户明确删除证据时解除其保护，同步撤销/重算依赖它的当前结论；当前任务原文被删除则判定返回 missing。不能以业务依赖为由无限保留，也不能删除依据后继续无条件展示原结论。
无需永久墓碑清单：保留每类删除 generation 与当前有效 Way/运行身份；旧生成任务捕获代际不匹配即拒绝。删除正文和可泄漏内容指纹，必要 unavailable 引用只保存不含正文的 ID/类型。仍有合法依据的运行若需要继续，必须在删除后的新上下文重新开始。

### 13. 旧数据迁移与切换

迁移是单独一次性工作，不调用模型、不改用户学习结论为“已证实”。流程为隔离式读取/备份 → 内存候选 → 校验 → 原子提交。成功后才更改 schema；失败保持原件。迁移备份计入既有备份范围，用户可见其保留语义。

1. 为现有单目标生成一个 Way ID，迁移候选中固定；第一次成功提交后永久使用，崩溃且未提交的候选不对外发布身份。
2. 在该 Way 命名空间内按旧集合位置生成确定性记录 ID；相同迁移重复执行不重复新增。新事件改用随机身份，不能仅按正文去重。
3. 原文按旧顺序导入，保留 role/content。没有真实时间、会话的记录均为空；旧 session_seq 放 legacy_seq，不虚构历史回访。
4. 已有 evidence 作为 legacy_unknown 导入，保留原始来源字符串/score 与可知时间；缺题目/提交/帮助信息则不能满足新独立证据条件。旧 summary 锚点标明聚合，不增加次数。
5. 同一序号的 session_records 与 session_summaries 正文去重；内容不一致时分别保留为待核实旧内容，不自动选一条当事实。rolling 作为 legacy 摘要，不能通过文字恢复新的能力结论。
6. 当前未完成任务/提交/确认状态原样关联，能确定的业务对象建立新 ID；无法可靠关联的旧证据不按主题文本猜配。
7. 旧原文中包含非法 role/类型时保留在迁移问题报告，不能直接注入；报告受用户数据控制和容量规则管理，不打印整段私人内容。
8. 所有读取和写入消费方改用协调入口/兼容投影后，才切换并删除旧重复字段；禁止一边新存储一边继续旧字段直接写入。保留对正常迁移的备份恢复说明，恢复不绕过用户后续删除。

### 14. 评估事件交付边界

本次只确定对外接口及清理约束，不提前设计完整 Agent 评估存储。工具执行产生稳定 invocation_id、逻辑动作/请求尝试身份及结果，供独立评估端接收；不在本规格定义成功率分母、指标字段全集、队列默认数值或评测门槛。
评估交付返回 accepted 或 delivery_incomplete。未确认接收时，工作记录压缩为必要的执行身份/状态元数据，标记 evaluation_pending，并保护这部分元数据免被终态自动清理；无需保留整段工具或聊天正文。独立评估端接入前不能声明事件已经交付或成功率可计算。
接收端应按稳定事件身份去重；允许恢复后重新交付，不宣称跨状态 JSON 和外部日志恰好一次事务。现有 metrics/trace 是否满足此接口需在接入时核对，不能从有日志推定已可靠统计。
采集失败不记作学习失败；若保护的未交付元数据积累到存储容量限制，沿用统一 storage_capacity 的明确失败处理，不暗删事件或伪报完整性。具体缓冲、恢复、汇总与运行调度策略留待后续 Agent 评估规格。
用户明确删除相关个人数据时按请求处理元数据和接收端引用；不能把“评估独立”当成忽略删除要求的理由，第三方范围如实说明。

### 15. 技术失败结果与调用方动作

| 结果 | 调用方动作 |
|---|---|
| rejected / pending | 显示必要原因；不应用为有效事实、不推进业务；非关键偏好不反复打断用户 |
| duplicate | 返回已提交记录引用；不重复记录或应用结果 |
| conflict / stale_result | 保留新状态，按相关依据重新决策；旧输出不直接重放 |
| missing / oversized | 明确缺什么/未读哪部分；禁止正式完整判定，保留原任务和提交 |
| save_failed / storage_capacity / writer_busy | 明确最后可靠保存点；不报告成功，不自动清空状态 |
| configuration_required | 指出模型预算或存储配置缺项，不编造默认供应商能力 |
| delivery_incomplete | 保护必要执行元数据，说明评估覆盖不足；不把采集失败记成学习失败，不伪造成功率 |

## Testing Decisions

主要通过 MemoryCoordinator 的三种公开行为测试，不要求业务测试知道内部四模块如何拆分。存储适配器单独测试真实文件原子提交、进程锁和损坏恢复；只在这些不可由内存适配器表达的行为处使用第二个测试接口。
沿用已有纯 Python 断言 runner、模型桩、内存状态和临时文件隔离模式；缺真实模型时不将跳过记为通过。核心用例无需联网、真实用户状态或评测 holdout 内容。

| 用例组 | 外部输入与断言 | 对应规格 |
|---|---|---|
| 写入准入 | 混合消息拆分；摘要要求写证据被拒；无效判定/错误来源/其他 Way/模型伪造 confirmed 均不改变有效画像或状态 | AC-30、D-02/04/13/18 |
| 来源与冲突 | 同范围新偏好生效、临时要求不覆盖长期值、推断留 pending；自评与失败证据并存；纠正使相关派生内容过期 | AC-33 |
| 幂等与保存 | 同事件恢复仅一条，同正文不同消息保留两条；判定/应用标记一致；模拟保存每个阶段失败，重启只见旧或新完整状态 | AC-11/22/33、D-08/12 |
| 原文与预算 | 精确引用、同会话相邻上下文、未知/已删 ID、必要标准缺失；长提交不能被摘要代替；分段缺一个必需项不整体通过 | AC-31 |
| 压缩与收尾 | 超 4000 字符批次含关键尾部信息；L1 中断不移动未处理范围；L2 接收 rolling/open_item/本轮最后消息；模型编造过程不能入库 | AC-32、D-13～15/18 |
| 生命周期 | 40 个会话归档裁剪到普通窗口加保护项；无重复摘要正文；删除无依赖旧值；有 basis 正常清理暂缓；显式删除撤销派生及旧回调 | AC-34、D-03/16/17 |
| 身份与恢复 | 跨日/计划单元不切会话，退出/中断新会话；已完成动作不重放，未知副作用不盲重试；16 小时边界/未知时间分别处理 | AC-10/12/29 |
| 迁移 | 旧扁平/分段原文、零分、旧聚合锚点、未知时间、重复摘要、损坏记录；重复迁移幂等，旧值不被宣称独立证据 | AC-30/31/33 |
| 评估交付 | 接收端失败、崩溃在接收后确认前、重复交付；工作正文清理后必要元数据可交付且不进入能力画像 | AC-35 |
| 接入契约 | 原有能力读写声明与实际变化一致；所有记忆消费者经过协调入口，不再直接写旧正文；规划/判定使用相应 ContextBundle | AC-23～35 |

测试以可观察内容、版本、状态和返回原因为准，不为每个私有函数复制断言；不把分数保持原样或骨架在前当作来源可信的充分证据。真实模型只补充候选提取和选取来源是否正确的质量验证，不能替代确定性协议测试。

## Out of Scope

多 Way 管理/切换、跨路径自动能力继承、账号/多用户/分布式并发、向量数据库、独立记忆 Agent 或 Review Agent、长期后台调度、模型自行修改清理政策、完整 Plan-and-Execute、视频内容解析、自动代码执行环境、Agent 评估指标/成功率口径和新评测集。
本次不编写业务代码、迁移用户文件、执行新协议或发布应用；开发按后续实现任务进行。普通保留窗口不作为永久无损保存承诺。

## Further Notes

开发顺序：先稳定身份与统一存储/恢复；接 Router 和业务事件；替换任务级上下文与原文回取；修 L1/L2 移交并接生命周期；最后迁移、移除旧正文直接写路径并跑贯穿场景。每步运行有关既有测试和本规格的行为验证，不先整体重写业务状态机。
证据数量显示区分目前可核验的明细数与早期聚合统计；已裁剪记录不再虚构可逐条核验的总数。
技术默认值可配置，改变普通窗口不改变证据资格、用户确认、16 小时复验或 7 天回顾规则。涉及后者的变化仍需产品决策。
当前没有新增产品决策阻塞；本规格中的容量、队列和预算默认值为工程设计选择，待实测校准。供应商数据处理仍需扩大试用前核验，Agent 评估细则保持后续议题。
统一测试接口已由项目负责人确认。按 to-spec 流程需发布到配置的 issue tracker 并应用 ready-for-agent 标签；当前尚未提供 tracker 与分诊配置，本地规格先完成，运行 /setup-matt-pocock-skills 后再按配置发布，不猜测 issue 目的地或假称已发布。
