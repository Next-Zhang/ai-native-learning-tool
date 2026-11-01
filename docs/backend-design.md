# 本地初版后端设计

日期：2026-11-01。状态：开发设计完成、核心能力待实现。本轮目标为用户从 GitHub 下载库、安装依赖并在自己电脑运行的初版软件；无多人线上服务、账号、计费、远程数据库或后台云任务。长期在线方向仅保留接口可替换性。
业务规则见 PRD；职责见系统/Workflow/Agent 运行/领域 Router 设计；工具调用采用注册表，不建设任务树引擎。既有 v0.18 是实现基线，不等于本设计已可用。
技术栈与接口以 [技术选型与模块接口设计](technology-and-module-design.md) 为准：Electron + TypeScript/React 界面，保留 Python 核心，stdio 子进程通信；不进行整体语言迁移。

## 1. 应用入口与模块

主公开接口为 LocalApplication：接收 Event，返回 ApplicationResult；提供 query 读取当前已授权视图和 subscribe 订阅进度。UI 不读写状态文件，Agent 不绕过 Router 调用仓储。CLI 是现有基线适配器，Electron 桌面通过同一服务的 stdio 适配器接入；初版不启动 HTTP 服务。

| 模块 | 所有权与依赖 |
|---|---|
| 应用协调 | 事件接收、幂等、确认、用户交互出口、关联提交；调用 Workflow 与运行控制 |
| Workflow | 阶段/依赖/允许行动、确认点；不生成模型文本、不访问 UI |
| Agent 运行控制 | 决策循环、工具分发、预算/取消、检查点和观察；不直接改业务记录 |
| 学习业务/证据 | 目标、矩阵、计划、任务、提交、判定候选、证据和画像的有效性与生效 |
| 产品数据服务 | 用户/会话、资料、运行与观测各自数据及 Router；存储通过统一提交器 |
| 上下文 | 按用途通过 Router 读取，版本/字段/预算检查，生成模型输入 |
| prompt/模型/工具适配 | 版本化 prompt、模型接口、外部搜索/读取；可测试替换，不向模块外泄漏供应商 SDK 类型 |
| 本地存储 | 已提交快照、版本/原子写、迁移、进程锁；拒绝第二个写实例 |

保持现有模块尽量复用：当前 run_turn/TurnResult 是迁移测试基线，执行器中的选择和业务生效逐步分离；不把全部现有 handler 注册为模型 tool。后端业务代码返回结构化结果，print/input 只留给交互适配器。

## 2. 应用事件契约

Event 包含 event_id、kind、way_id、expected_revision、对象引用/版本及 typed payload；可信 principal 固定为 local-owner，由应用适配器注入。处理同一 event_id 不重复接受/保存；新消息即使正文相同也有新事件身份。模型无法声明 principal 或授权。

| kind | 输入 | 对外行为 |
|---|---|---|
| message | 原文、会话引用 | 保存接收记录，理解意图；可追问/启动运行，不自动将每句话当提交 |
| submit | task_id/version、原始内容、帮助声明 | 保存不可变提交引用，进入判定候选流程 |
| confirm/reject | confirmation_id、目标对象版本、明确选择 | 应用等待事项；过期确认返回 conflict，不复用旧授权 |
| pause/resume/end_session | session_id、可选新容量 | 保存实际会话边界或恢复待办；不按静默时间自动结束 |
| cancel_run | run_id | 立即标记取消并要求执行停止；迟到结果不应用 |
| request_review | 当前目标/周期 | 按真实表现检查复验或周期回顾，受原候选/预算规则约束 |
| clear_conversation/reset | 明确操作范围与确认引用 | 按现有用户操作语义删除/重置，说明备份/日志，不新增三入口 |
| retry | 原 run/任务/提交引用 | 新运行身份，关联旧提交；不重放已成功业务应用 |

ApplicationResult 包含 event_id、revision、status、run_id、messages、pending_confirmation、artifacts、errors、saved_state。status 为 accepted/running/waiting_user/completed/rejected/conflict/failed/cancelled；工具步骤 completed 不等于学习目标达成。saved_state 明确最后可靠 revision，不能凭回复文字宣称保存。
query 包含用途、对象引用与字段要求，经 Router 返回获准投影；运行查询可看进度、退出原因及最后保存点，不返回凭据或原始内部日志。subscribe 只读进度，不改变业务确认或产生一次新运行。

## 3. 领域对象及关联

| 对象 | 核心字段与关系 |
|---|---|
| Way | id、goal/version、capacity、scope、当前有效计划引用；当前只一个，修改同目标不另建路径，完全重置新身份 |
| CapabilityMatrix/Point | 稳定矩阵/能力点 ID、前置、标准、版本、用户确认与未测范围 |
| PlanVersion | roadmap/milestones/window、来源关联、预算、basis_versions、自审核记录、draft/reviewed/awaiting_confirmation/active/superseded |
| TaskVersion | ID/version、计划/能力/量规关联、交付物、允许资料、时间分配；发布后改要求创建新版本 |
| Submission | ID、task/version、原始内容引用、帮助记录、实际提交时间；确认使用原提交而非模型摘录 |
| Judgment | submission/task/rubric/version、逐标准结论/依据、valid/invalid/disputed、模型与 prompt 版本、是否已应用 |
| Evidence | 能力点、有效 Judgment、帮助程度/来源、独立/保持关联、呈现/提交时间；不从分数平均产生独立证据 |
| Confirmation | ID、主体/Way、操作、对象/版本、pending/accepted/rejected/expired，可信用户事件引用 |
| Session | ID、实际开始/结束、中断原因、恢复点；与计划 day/序号分离 |
| Run/Invocation | ID、步骤/工具参数引用、结果状态、输入版本、取消/删除代际、已保存检查点 |
| UserSessionData/Resource | 来源明确的偏好/对话/摘要/open_item；资源正文和采用关系分别归对应服务 |

原题、标准、提交、有效证据与来源必须可追溯。未知帮助不算独立，未知时间不算 16 小时保持；多能力点任务逐项留证，部分完成不整体放行。画像为有效证据投影，业务对象只有一个权威所有者。

## 4. 状态和事务

每次关键生效在同一提交中校验 revision、确认、来源及关联，保存新记录/派生失效/应用标记。当前本地单 JSON 可保证整体候选替换，但必须在提交成功后才公布内存状态和成功回复；网络调用在锁外进行。
确认计划：审核通过且确认匹配版本 → active 计划及确认状态一起提交。
提交判定：有效结果先保存 awaiting_acceptance；用户确认该 Judgment 版本后，证据应用标记、画像/待复验投影、进度变化一起提交。重复确认返回原结果，不重复计次；争议保持原提交并走纠正关联。
无效模型输出、网络故障或保存失败不写能力零分、不消耗有效测评题。原 D-01/02/04/05 与恢复问题为接入前必须修复的核心缺陷，不能仅靠 prompt 约束。
收尾先保存用户最后消息和有效业务结果，再生成摘要候选并可靠移交；摘要失败不回滚已保存的任务结果，也不清掉未处理原文。

## 5. 工具注册表与适用集合

工具登记唯一 name、用途 description、严格 input_schema、handler、task_groups。只把当前允许集合发给模型；执行时查表并重核权限/版本/参数，未知名称或额外参数拒绝，不 eval、不动态导入任意函数。

| 工具名 | 输入/输出概要 | 副作用和前置条件 |
|---|---|---|
| search_resources | query、能力点 → 来源候选/访问错误 | 外部只读，不假称已读正文，需当前资料任务 |
| read_resource | source_id → 有限正文/版本/来源 | 只读允许资料，禁止任意本机路径 |
| get_learning_context | purpose、对象引用 → 获准业务/证据视图 | 领域 Router 分字段读取，无任意全库查询 |
| recall_conversation | 消息/任务/会话引用 → 原文/缺失项 | 当前 Way 和任务用途限制，不能借语义跨域 |
| propose_matrix | 目标/资料引用 → 矩阵草案 | 生成候选，不自动用户确认 |
| prepare_assessment | 已确认矩阵/覆盖范围 → 题目/量规 | 保存待呈现版本；实际呈现时间由系统记录 |
| judge_submission | task/submission/rubric IDs → Judgment 候选 | 仅有效正式提交，完整输入，输出经独立校验 |
| draft_plan | 矩阵/画像/来源/容量引用 → 草案版本 | 不生效，不静默增加预算 |
| review_plan | plan_version → 逐项审核/问题 | 主 Agent 自审核独立步骤，不自行授权激活 |
| present_for_confirmation | kind、对象版本 → 可读内容/confirmation_id | 生成待确认事项，真实确认来自用户事件 |
| build_learning_task | active_plan/窗口、容量 → Task 草案 | 既有范围内生成；实质变更走确认 |
| explain_or_hint | 当前任务/问题/允许资料 → 回复/帮助记录 | 提示影响记录，不暗中给完整答案后算独立 |
| propose_review | 周期/候选证据引用 → 复验/调整建议 | 系统检查会话限额、16 小时及候选排序，不自动激活新计划 |

工具分组用配置映射：资料准备、测评、计划、学习/验收、周期回顾；同工具可复用，不引入任务树引擎。业务应用、记录确认、设置身份、改证据分数、清理任意数据不暴露为通用模型 tools。上述表是目标契约，未实现工具不能先登记为可运行。
工具成功/内容有效/保存成功/业务生效分别返回；失败结果带类别与重试建议，调用方不能把工具错误映射成用户不会。

## 6. 运行调度与冲突

本地 Electron 桌面进程与一个 Python 后端子进程协作；以下调度限制作用于 Python 内部。后端输入线程处理事件和取消，一个工作队列执行当前 Way 的主动 Agent run；同 Way 同时最多一个主动运行，1.0 首版不并行写入工具。模型与网络不阻塞交互事件接收。
新增普通消息先保存并排到下一决策边界；用户取消/重置/目标实质变化优先更新代际，使相关旧操作失效，不等网络请求完成。确认仅适用于已发出的匹配对象/版本，不能把未完成的生成请求误当确认。
工程默认局部循环最多 12 个动作、总计 600 秒、连续 2 次无新信息/产物/业务变化的同输入动作即停止；均可配置、记录在运行快照，属于实现防失控起点，不是正常响应性能目标。调用失败的网络恢复仍含首次最多 5 次、单逻辑调用最多 120 秒，受剩余 run 时间进一步约束，不允许层层叠加重试。
limit_reached/blocked/waiting_user 是有原因的退出，不宣称达成。重试或恢复创建/续接明确身份，不能使同提交重复应用。非幂等副作用状态 unknown 时先核查，不能简单重发。
进程退出后无常驻后台；下次启动标记未结束 run/session 为 interrupted，恢复可靠检查点。已取消/超时/被替代操作迟到结果只记诊断状态，不写业务、证据或记忆。

## 7. 数据访问、存储和上下文

本机可信主体也必须经过领域 Router；身份检查不依赖模型。产品数据管理与访问层按 Learning/Evidence/UserSession/Resource/Runtime/Evaluation/IdentityPolicy 路由，后两类默认不向模型提供敏感原始记录。缓存与预加载不绕过 Router。
沿用本地 JSON 适配器，仓储对外只提供一致快照/版本提交与类型化查询。schema 从实际当前版本向下一个版本迁移，迁移前备份、候选校验、成功后切换；旧帮助/题目/时间未知保留为 legacy_unknown，不猜成独立能力。实际迁移协议按新所有权拆分旧记忆规格，不能直接整体执行旧 MemoryCoordinator。
数据目录可配置为 COACH_DATA_DIR；源码 CLI 默认本地 data，Electron 默认 userData 下的 backend 并显式传入后端。两端都清楚显示状态/备份/日志位置，复用旧目录必须显式选择且不自动覆盖。运行数据、API Key、评测产物不得进入 Git 提交。安装位置和数据位置分别处理。
每次运行初始快照按任务读取，下一步检查相关版本后复用/增量补读；关键事件/工具边界保存，辅助写合并。流式 token 不逐个落盘，不每步生成摘要/执行全量清理。
模型上下文必须有显式模型容量和输出预算；默认辅助历史 8000 字符、3 条摘要及相关原文不是绝对硬上限。必需提交/标准缺失或超限返回明确缺口，可按量规分段但不把未核验部分自动判过。

## 8. Prompt、模型和资料适配

prompt ID/版本/hash 与运行记录关联；各新工具能力的输出模型先定义再登记 prompt，不让模型自由 schema 驱动业务。现有 prompt 标为 legacy_current，保持当前代码兼容，不声称已完成新产品功能。
模型 Key 从本地配置读取，不打印/写入 prompt，不在库内提供共享 Key。缺配置返回 configuration_required；用户自己提供有效凭据后才产生实际模型费用。停止/取消不承诺服务端已撤销计算或计费。
资料搜索首个适配器选 Brave Search API，网页取回选 HTTPX + BeautifulSoup；具体配置、接口与限制见技术选型文档。不将现有 Python 本地 RAG 当成完整联网目标资料库；RAG 为可选依赖，不在核心安装时强制下载模型。来源取回、有效性、引用支持分别记录。

## 9. GitHub 本地体验交付

库提供安装/配置/启动/离线自检/数据范围说明；现有 CLI 保留为第一可验证入口，本地可视界面通过同一服务接入，不把 Web 账号或云服务作为启动前提。
干净环境可安装核心包，prompt manifest 包含在分发中；默认不启用真实评测或抓取，不因启动自动消耗大量模型调用。提供示例配置但不包含凭据、个人数据或真实诊断内容。
目标交付为 Electron 桌面窗口，TypeScript/React 展示，通过主进程管理 Python 子进程；具体视觉稿另行设计。应用结果、等待状态、进度与确认契约使界面可独立开发。GitHub 下载体验不等于所有发布门槛已通过，必须按验收协议标明当前缺口。

## 10. 验证和开发次序

主测试接口已由用户确认：用户 Event → ApplicationResult/确认/可靠保存。模型、工具、时钟、资料、仓储可注入；真实文件适配器单独测原子保存、锁、迁移和恢复。只测外部行为和不变量，不锁死每个私有函数或唯一行动顺序。
开发先后：修正判定绑定/故障/授权 → 应用事件和领域对象的贯穿最小路径 → 注册表/模型选择及资料能力 → 矩阵/计划审核与版本确认 → 学习验收/证据/收尾 → 回取/生命周期/周期回顾 → 干净安装和持续学习观察。
每阶段保留确定性基线以对照自主路径。35 条 AC 场景、候选 judge 评测与真实用户观察分别验收；没有实测不宣称新 run 参数或缓存降低了成本。工程容量/预算可调，不改变用户时间预算、证据资格或确认权。
