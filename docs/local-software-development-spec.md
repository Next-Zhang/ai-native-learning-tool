# 本地初版学习软件开发规格

版本：1.0；日期：2026-11-01。状态：参考汇总，不作为独立需求来源；产品要求以 PRD 为准，开发以专项设计为准，尤其是 [技术选型与模块接口设计](technology-and-module-design.md)。本规格不表示目标功能已实现。按项目负责人指定的 to-spec 模板，由 subagent 基于当前讨论、代码和设计文档综合撰写。依据 PRD、ADR-004/006/008/009 及本地后端设计；测试入口已经项目负责人确认，无需重新访谈。

## Problem Statement

学习者需要在自己电脑上围绕一个能力目标持续学习，能够看见目标与计划的依据、提交实际产出、获得可追溯反馈，并在中断后继续。当前原型具有 CLI、阶段工作流、模型判定及记忆压缩，但尚不能可靠完成新的十步产品闭环；题目绑定、故障记分、授权、预算、摘要信息流转和恢复仍有已知缺陷。
此前设计将业务状态、证据、资料、运行检查点与个人记忆混为较大的记忆体系，增加了数据所有权和开发边界的不确定性。直接增加自主工具选择会放大已有状态与判定问题。
首批体验者将通过 GitHub 下载库并本地运行。当前不需要多人在线账号或云端部署，但需要明确安装、配置、启动、数据范围、错误及费用行为，避免把开发环境能运行误认为可供用户可靠体验。

## Solution

交付单用户、单学习路径 Way 的本地初版，保留 Python 核心和现有 CLI 验证入口，以应用服务统一接收用户事件并输出结构化结果、确认请求和可靠保存状态。本地界面采用 Electron + TypeScript/React，经主进程和 stdio 协议连接 Python 后端；不启动 HTTP 服务，核心不依赖桌面框架。
Workflow 管理必要依赖、业务状态和确认点；主 Agent 在合法范围内通过行动反馈选择下一步，首期仅在检索、计划生成和自审核修订开放局部 ReAct。工具采用集中注册表与分发执行器，产品数据由不同领域服务拥有，所有 Agent 数据存取和上下文预加载都通过相应 Router。
保留目标澄清、资料准备、能力矩阵与测评、画像驱动计划、自审核、展示确认、学习验收、收尾更新、复习复验及七天回顾十个环节，按最小能力实现。prompt 采用明确 ID/版本/内容散列和输出契约；确定性验收、真实模型判定评测和真实学习观察分开执行。

## User Stories

1. As a learner, I want to download and run the software locally, so that I can try it without an online account.
2. As a learner, I want clear dependency and configuration instructions, so that I can start from a clean environment.
3. As a learner, I want missing model credentials reported clearly, so that configuration failures are not mistaken for learning failures.
4. As a learner, I want my local data and backup locations explained, so that I understand what is stored on my computer.
5. As a learner, I want my goal clarified through a few relevant questions, so that the software understands what I want to achieve.
6. As a learner, I want optional self-assessment and deadlines to remain optional, so that I can begin without inventing them.
7. As a learner, I want my actual available time respected, so that a short session is not silently enlarged.
8. As a learner, I want teaching, practice and feedback included in my time budget, so that plans reflect my real capacity.
9. As a learner, I want explicit preferences recorded with their sources, so that later teaching reflects my choices.
10. As a learner, I want access to real reference materials, so that learning arrangements have verifiable support.
11. As a learner, I want unavailable or insufficient sources identified, so that fabricated references do not guide my learning.
12. As a learner, I want the goal's capability matrix explained and confirmed, so that assessment covers an agreed scope.
13. As a learner, I want assessment tied to the actual question and answer, so that my profile reflects my own work.
14. As a learner, I want untested and unjudgeable areas shown separately, so that uncertainty is not presented as inability.
15. As a learner, I want plans based on my evidence and capacity, so that tasks address relevant gaps.
16. As a learner, I want each plan's sources and reasoning visible, so that I can assess whether it fits my goal.
17. As a learner, I want a plan checked before presentation, so that unsupported or impractical arrangements are revised.
18. As a learner, I want to confirm the exact plan version before it becomes active, so that suggestions do not silently replace my choices.
19. As a learner, I want requests to modify a plan treated separately from agreement, so that questions do not grant authorization.
20. As a learner, I want one current learning task with a clear deliverable and rubric, so that I know what to produce.
21. As a learner, I want questions and hint requests distinguished from submissions, so that asking for help does not consume an attempt.
22. As a learner, I want my complete original submission judged, so that compressed excerpts do not distort the result.
23. As a learner, I want invalid model results rejected, so that malformed outputs do not update my progress or ability.
24. As a learner, I want to accept or dispute a task judgment, so that an automated result does not force an incorrect progression.
25. As a learner, I want assistance recorded separately from task completion, so that aided success is not called independent ability.
26. As a learner, I want independent evidence and later retention evidence displayed separately, so that one success is not overstated.
27. As a learner, I want comprehensive milestone tasks linked to required standards, so that missing requirements are not hidden by averages.
28. As a learner, I want learning summaries to preserve unresolved questions and constraints, so that the next session can continue accurately.
29. As a learner, I want relevant original messages retrievable, so that the coach can verify remembered details.
30. As a learner, I want deleted or unavailable originals acknowledged, so that the system does not claim to have checked them.
31. As a learner, I want review scheduling explained and included in my budget, so that review does not unexpectedly replace my pending task.
32. As a learner, I want to skip an automatic review without being marked wrong, so that I retain control of my session.
33. As a learner, I want periodic plan review based on actual activity, so that time passing alone does not imply progress or forgetting.
34. As a learner, I want to pause, exit and return without rebuilding my goal, so that interruptions do not erase useful work.
35. As a learner, I want cancellation and retry to preserve reliable results, so that late responses do not overwrite newer decisions.
36. As a learner, I want repeated events handled only once, so that retries do not duplicate evidence or progress.
37. As a learner, I want save failures distinguished from successful persistence, so that I know the last recoverable state.
38. As a learner, I want incorrect, redundant and obsolete information managed consistently, so that memory remains useful and controllable.
39. As a learner, I want clearing conversation data to include derived conversation summaries, so that removed content does not reappear.
40. As a learner, I want reset and backup semantics explained, so that resetting progress is not confused with complete data deletion.
41. As an operator, I want model and tool actions restricted to permitted capabilities, so that generated requests cannot bypass business rules.
42. As an operator, I want product data access filtered by domain, purpose and scope, so that the Agent only receives authorized information.
43. As an operator, I want failed tool calls retained for evaluation without becoming ability evidence, so that failures are measurable and fairly interpreted.
44. As a developer, I want prompts identified by stable versions and content hashes, so that changes and evaluation configurations are reproducible.
45. As a developer, I want incomplete reviews and failed evaluation calls reported explicitly, so that a high average cannot conceal missing coverage.
46. As a developer, I want behavior tested through the application event interface, so that internal refactoring does not invalidate useful tests.
47. As a developer, I want deterministic baseline and autonomous paths compared under the same constraints, so that additional autonomy is justified by evidence.
48. As an evaluator, I want human-reviewed frozen samples separated from development material, so that independent acceptance is not contaminated by tuning.

## Implementation Decisions

### 1. Scope and ownership

- Current delivery is a local software experience downloaded from GitHub, with one local user and one Way. No online authentication, shared service or cloud background job is required.
- Keep Python and replaceable adapters. Use Electron with TypeScript/React for the desktop, connected through a versioned stdio adapter. Preserve the CLI as a verification interface. Neither desktop code nor CLI may bypass the application service to mutate state.
- Product data is not all Agent memory. Learning business owns goals, plans, tasks, submissions and confirmations; evidence services own judgments, assistance and ability projections; user/session data owns preferences, dialogue and summaries; resources own source content and adoption; runtime owns execution checkpoints; evaluation owns operational records.
- Context assembly reads authorized projections across these owners. The previous comprehensive memory coordinator must not be implemented as the product-wide business and data authority. Its provenance, version, original-reference, compression and recovery mechanisms may be reused under the revised ownership.

### 2. Application interface

- LocalApplication accepts a typed Event and returns ApplicationResult, with query and progress subscription operations. The core returns messages, waiting states and errors rather than directly blocking on terminal input.
- An Event carries a unique event ID, type, Way, expected revision, object references and versions, plus type-specific content. The trusted adapter supplies the local principal; model-generated identity or authorization fields are never accepted as authority.
- Supported event types cover message, explicit submission, confirmation/rejection, pause/resume/end session, cancellation, review request, conversation clearing/reset and retry.
- A result identifies the event, run and committed revision, its status, output messages, artifacts, pending confirmation, errors and last reliable saved state. Accepted input, a completed tool, a saved result and an achieved learning goal remain distinct.
- Replaying one event is idempotent. Separate messages with identical text remain separate events. Confirmation references a specific pending action and object version.

### 3. Workflow and learning closure

- Initialization must establish the goal, obtain real source material, confirm matrix scope, perform valid assessment, draft an evidence-based rolling plan, perform self-review, present the version and obtain user confirmation.
- Dependencies are mandatory; exploratory actions can move backwards to collect information or revise. Source failure cannot be disguised as completed retrieval, and review failure cannot activate a plan.
- Missing self-assessment or deadline does not block learning. Do not impose a uniform minimum session duration; teaching, practice and feedback all consume the stated budget. Reduce or split actual work rather than only reducing its time label.
- Each task identifies the expected output, rubric and permitted tools or materials before submission. Formal judgment binds the presented task, unchanged rubric and original submission; questions and hint requests are not submissions.
- Valid judgments may be saved awaiting user acceptance. Acceptance applies evidence and progress once in a consistent business transaction; disputed or invalid judgments do not create new independent conclusions.
- One qualifying new-task independent performance can be displayed with source, time, count and assistance information. Unknown assistance is not independent. Task completion, independent application, due-review flag and cross-session retention are distinct; no overall mastery percentage summarizes them.
- Retention requires a new related task in a later actual session, independent success and at least sixteen hours from the original valid submission to first presentation of the retest. Missing timestamps do not satisfy the interval. Milestone progression need not wait for retention.
- Comprehensive milestone and final tasks cover every confirmed necessary standard, with targeted supplementary checks for gaps. High scores elsewhere cannot compensate for a missing necessary requirement.
- Automatically arrange at most one review task per actual session; it may cover related knowledge points. Explain reasons and budget use, preserve pending work, and apply per-point results. Skipping is not failure and does not automatically trigger a replacement task.
- Seven-day review uses actual elapsed time and observed activity, can occur on return, and may retain the current plan. New or materially changed plans return through self-review and version-specific confirmation.

### 4. Domain models and validity

- Assign stable IDs and versions to Way, capability matrix/points, plans, tasks, submissions, judgments, evidence, confirmations, sessions and runs. Do not use generated topic text or a repeated day/task position as global identity.
- Presented task/rubric versions and original submissions remain immutable while referenced by a judgment; modifications create new versions and invalidate affected derived content.
- Evidence links the actual task, submission, standards, assistance and timestamps. Invalid output, an API failure, user self-description or a narrative summary cannot stand in for valid performance.
- Derived ability views follow valid evidence and confirmed standards rather than legacy numeric averaging. Corrected/disputed evidence propagates invalidity or a required recheck to affected views, summaries and plans.
- Legacy records retain known source and score information but missing questions, assistance, timestamps or actual sessions remain unknown. Migration cannot manufacture independent application or retention.

### 5. Agent loop and tools

- Workflow determines legitimate state transitions and allowed actions; the Agent chooses actions within those constraints. Start dynamic selection in resource retrieval, plan generation and explicit self-review revision; retain deterministic baseline behavior elsewhere until validated.
- Use a tool registry and dispatcher with stable unique names, descriptions, strict input schemas, internal handlers and task groups. Only permitted tools are shown to the model, and execution independently rechecks availability and parameters.
- Model-visible tools cover resource search/read, authorized context lookup, conversation recall, matrix/assessment preparation, judgment candidates, plan drafting/review/presentation, task generation, teaching/hints and review proposals.
- A generated tool call is a request, not execution authority. No arbitrary code, dynamic handler import, unrestricted state setter, credential lookup or generic evidence/confirmation mutation tool is provided.
- Tool results expose separate invocation identity, execution status, content validity, object/version, provenance, actual save state and error/retry category. System checks rather than model prose establish business effect.
- No task-tree engine, additional model router or separate Planner/Executor is introduced. Tool group selection is configuration; tools can be reused across groups.
- Plan self-review is an explicit, recorded capability with source-support, profile-fit and feasibility checks; it is not a sentence appended to generation instructions. A future Review Agent may replace the reviewer role without replacing confirmation semantics.

### 6. Scheduling, failure and recovery

- One local process owns writes. The interactive event handler remains responsive while one worker queue performs the current Way's active Agent run; the first release does not execute concurrent writing tools within one Way.
- Persist ordinary incoming messages and incorporate them at the next decision boundary. Cancellation, reset or material target change updates cancellation/validity generation promptly, so a blocked network call cannot later overwrite new choices.
- Engineering defaults for a local autonomous run are twelve actions, six hundred seconds total and termination after two repeated same-input actions with no new information, artifact or business change. These defaults are configurable guardrails, not proven performance targets.
- Each logical model operation permits at most five requests including the first and at most one hundred twenty seconds total, including waits; the remaining run budget may end it earlier. SDK and business retry layers share limits rather than multiplying retries.
- Configuration errors and invalid returned content are distinguished from transient request failures. No monetary automatic stop is added. Record known usage and cost, marking unknown values rather than zero.
- Completed, waiting-user, blocked, cancelled, failed and limit-reached are separate outcomes. Asking the user pauses execution instead of inventing a reply.
- A successful action is not blindly replayed after recovery. Unknown side-effect outcomes require reconciliation. Cancelled, timed-out, superseded or dependency-stale responses cannot update business, evidence or user/session data.
- Actual sessions are independent of plan units, dates and API failures. Silence does not automatically terminate a session. Returning after exit/interruption creates a new actual session and restores the unfinished task or pending confirmation.
- Local process exit does not promise continued background execution. Restart marks unfinished sessions/runs interrupted and resumes from the last reliable checkpoint.

### 7. Domain Routers and context

- Learning, evidence, user/session, resource, runtime, evaluation and identity/policy domains each enforce their own Router rules. A common entry point only dispatches requests and cannot grant cross-domain authority.
- All Agent reads, writes, context preloads, cached views and stored-data tool results are filtered by trusted subject, Way, actual purpose, object relation, permitted fields and current versions. Unknown operations/fields default to denied.
- Credentials, full management policy, private runtime debugging records and independent evaluation labels are not model-readable. Execution services' ability to record checkpoints or evaluation events is not delegated to the Agent.
- Context requests identify their purpose and mandatory task/submission/rubric/assistance inputs. Return completeness, source references, read versions, missing items and budget information.
- Exact original-message/task/session lookup precedes optional keyword retrieval. Unknown or deleted references are explicit failures, not invitations to fabricate prior content.
- Reuse a still-authorized initial snapshot and incrementally read relevant changes. Router checks need not cause a full physical file read. Invalidate affected caches on policy changes, corrections, deletion or dependency updates.
- Keep relevant auxiliary history within the existing eight-thousand-character soft budget, with up to three selected session summaries and relevant originals; these are preferences, not permission to omit mandatory evidence or exceed the full model budget.
- Require explicit model context and output capacity. Missing or oversized mandatory material produces an incomplete/oversized result; bounded per-rubric processing must track all required coverage and cannot falsely produce a complete verdict.

### 8. Persistence and lifecycle

- Retain a local JSON adapter behind a snapshot/versioned commit interface. Serial in-process commits and a process-level write lock protect the local single-writer assumption.
- Model/network operations run outside the commit lock. Check dependencies, generations and expected revisions before applying a candidate state, then publish the new in-memory view only after reliable replacement succeeds.
- Confirmation/evidence/progress application and the corresponding idempotency marker commit consistently. A failed save reports the last reliable revision, keeps prior committed state intact and does not announce success.
- Persist input reception and necessary tool boundaries; combine associated field changes, do not rewrite state for every field or streamed token. Auxiliary tracing and maintenance do not justify delaying critical business saves.
- Keep product data directories configurable and separate from installed package assumptions. Document local state, backups and trace scope; do not ship credentials or personal state with the repository.
- Migrate with backup, isolated candidate construction, schema/reference validation and successful atomic switching. Repeated migration is harmless; future or invalid schema cannot silently overwrite the original state.
- Lifecycle policies belong to each data owner; application coordination handles cross-domain cleanup. Merge duplicates, retire superseded values, and clear unreferenced temporary content while preserving current basis evidence and unresolved items.
- Compression explicitly transfers source coverage, open issues, constraints and references from rolling to session summaries. Unprocessed text cannot be marked compressed, and summaries cannot create fresh ability judgments.
- Conversation clearing removes associated raw dialogue and narrative summaries, with retained structured learning information explained. Reset creates a new valid goal state while accurately disclosing retained backups/logs. Broader deletion respects its explicit scope and invalidates derived records and late callbacks.
- Operational failures remain available as minimal evaluation events when temporary working content is cleaned; they do not become ability evidence. Detailed evaluation collection, buffering and success-rate definitions remain a separate later design.

### 9. Prompt library and configuration control

- The current library contains twenty registered task/context/stage prompts, each with stable ID, version, content hash, purpose, output contract, acceptance linkage and legacy-current status. Existing runtime text is intentionally preserved for compatibility.
- The prompt manifest is a review lock and packaged resource. Unknown IDs, unregistered constants or content drift fail offline checks; prompt changes require corresponding version/contract review and a regenerated manifest.
- The model entry point records registered static prompt identities/hashes in optional per-turn traces without copying dynamic user content into prompt provenance. Metadata collection adds no model operation and must not fail a valid request.
- Current prompt registration is not proof that the current stages comply with new product requirements. New output contracts, self-review, matrix, Decision and periodic review capabilities require implemented validators before production prompt activation.
- Tune only with development evidence. A new semantic prompt or rubric change requires fresh frozen configurations and complete reevaluation; independent evaluation data cannot repeatedly guide tuning while retaining its claimed holdout role.

### 10. Acceptance data and protocol

- Keep the existing thirty development samples and eight old holdout samples unchanged. Do not describe the eight samples as meeting the new thirty-sample minimum.
- The new thirty synthetic candidates contain six per each of five judges and two normal, two boundary and two adversarial samples per judge, with critical cases identified. All remain pending human review; source and reviewer fields must not be fabricated.
- The thirty-five workflow scenarios encode the current acceptance cases and remain unexecuted specifications; their existence cannot close the corresponding implementation or coverage gaps.
- Human reviewers independently determine expected labels under product/task rubrics, resolve disputes, then freeze eligible acceptance data and configuration. Repeated input, near-duplicates or using failure outputs for tuning do not create independent sample coverage.
- Formal judge acceptance runs the complete frozen dataset three times, reporting each run and judge/domain/risk strata, agreement, errors, coverage and critical failures. Every run must achieve at least ninety percent agreement, pass all critical cases and contain no missing effective coverage or invocation errors.
- Never average, majority-vote, cherry-pick a run or retry only failed cases to replace a full run. Network recovery requests do not count as additional evaluation rounds.
- Candidate validation is offline by default and explicitly reports not executed plus review blockers. Live acceptance requires reviewed eligible data, a matching freeze manifest, explicit holdout permission, output location and locally configured credentials.
- Configuration identity includes code, prompt manifest, dataset and model/temperature; detect code/prompt changes before/after evaluation. Schema validation or a perfect mocked model does not establish real model quality.

## Testing Decisions

The primary seam is the user-confirmed local application event interface: user Event to ApplicationResult, confirmation requests and reliably committed state. This is the highest stable behavior surface for workflow, tools, data access and recovery. Test through it instead of asserting private handler order or a single exact valid exploration trajectory.

| Test group | External behaviors to verify | Existing practice to reuse |
|---|---|---|
| Installation and startup | Core install works without RAG model download; missing configuration is explicit; data location is usable and explained | Offline invocation and temporary-environment smoke checks |
| Goal and budget | Optional fields do not block; actual short capacity preserved; teaching/practice/feedback sum fits budget | Profile, plan and stage assertion tests |
| Matrix and source | Confirmed scope precedes assessment; real source supports its citation; unavailable material is acknowledged | Stubbed resource adapters plus independent source review |
| Plan and confirmation | Review failures return for revision; pending/rejected/stale versions cannot activate; replay does not reactivate | Existing confirmation-gate and workflow fixtures |
| Submission and evidence | Original question/submission is judged; questions do not count; invalid/failure results do not score or advance; assistance remains separate | Assessment, submission, judgment and structured-contract tests |
| Completion and review | Mandatory rubric gaps block attainment; retention interval is correctly measured; one automatic review task per actual session | Cursor fixtures extended with explicit clock and session events |
| Tool execution | Duplicate registration, unknown/hidden tools, invalid parameters and forged identity cannot execute; actual saved state is reported | Capability completeness, write-contract and guardrail patterns |
| Data and context | Correct Router/field projection; cache cannot cross scope; mandatory originals cannot be silently truncated; deletion invalidates derived views | In-memory snapshots, context assembly fixtures and source-reference assertions |
| Cancellation and persistence | Cancellation is responsive; stale/late results rejected; failed saves preserve old complete state; checkpoints do not duplicate side effects | Fake clock/model/store with isolated real-file adapter tests |
| Compression and lifecycle | Long inputs retain tail coverage; L1 information reaches L2; archive policy runs on every write path; no duplicated hidden summaries survive clearing | Memory regression tests expanded to full entry-point scenarios |
| Prompt management | Inventory complete; content drift fails; unknown IDs rejected; only static provenance appears in metadata | New offline prompt catalog contracts |
| Evaluation protocol | Pending labels cannot pass; full-run ordering retained; critical failures override a high mean; malformed or failed runs remain visible | New protocol tests with deterministic injected judge outputs |
| Local continuous learning | At least five actual sessions over at least seven days, interruption/return and a qualifying sixteen-hour retest | Prospective manual observation with task and evidence identities |

Use dependency injection for model, resource, clock, ID generation and persistence. Deterministic tests run without a real API key or real user state. The concrete storage adapter separately verifies lock ownership, write failure, corruption, migration and restart recovery; prompt/evaluation tooling has separate offline contract tests as explicitly agreed.
Existing tests that enforce superseded semantics must be revised with new failure reproductions and preserved safety intent, not removed just to improve counts. Report PASS/FAIL/SKIP separately; skipped real-model tests cannot justify quality acceptance.
Live model tests supplement deterministic behavior and human-reviewed source/plan quality. They require an explicit request and valid local configuration; this design task does not initiate paid calls. Measure latency and usage as baselines, not unapproved new release thresholds.

## Out of Scope

- Multi-user online operation, account systems, subscriptions, organizations, remote database deployment and cloud job infrastructure.
- Multiple Way management or automatic cross-goal ability inheritance; the current scope remains one local active path.
- A mandated GUI framework, detailed visual design or an obligatory local HTTP server; the common application interface enables later presentation work.
- Independent Review Agent, dynamic multi-Agent orchestration, a task-tree execution engine or a full Plan-and-Execute layer.
- An unrestricted tool/SQL/file execution surface, model-managed authorization or arbitrary direct state mutation.
- Mandatory vector search, automatic video-content parsing or a code execution sandbox; local RAG remains an optional adapter.
- New claims of generalized learning efficacy, causal improvement, long-term mastery or a required percentage learning gain.
- Full Agent evaluation metrics, charts, success-rate denominators or evaluation data retention policy, beyond the necessary event and isolation boundary.
- Treating generated labels as human-reviewed/frozen, altering the old holdout to tune prompts, or claiming prospective workflow scenarios have executed.
- Implementing all target backend features, migrating user data, running paid evaluation, committing changes or publishing software as part of writing this specification.
- Ticket decomposition; the user's latest request calls for a development specification only.

## Further Notes

Development should begin with the existing critical judgment, source-binding and authorization defects, then deliver a narrow complete application-event path. Follow with tool dispatch/resource capabilities, matrix/plan review and version confirmation, learning/evidence/acceptance, reliable session closing and retrieval, lifecycle and periodic review, and finally clean-environment user experience and prospective learning observation. Each step retains a verifiable deterministic baseline and targeted regression evidence.
The current branch has implemented prompt inventory/manifest/provenance, new pending acceptance candidates and workflow scenario inventory, and the separate three-full-run evaluation protocol. It has not implemented the LocalApplication target, all registered model tools, data Routers, new evidence semantics, complete recovery or the entire ten-step learning closure. Existing gaps remain until repaired and verified.
Parent-side verification runs offline regression with model credentials removed from test subprocesses; prompt and acceptance-protocol tests are included. The final complete offline regression reports 256 passes, zero failures and eight explicitly skipped live-API cases; the subsequent dataset enum validation hardening also passed its six focused protocol tests. Full evidence is recorded in the validation report. This is offline regression evidence only; it is not a real model agreement rate, full product acceptance or proof that generated candidates are independent holdout data.
Unresolved acceptance dependencies are human label review, dispute resolution, untouched independent data where tuning has occurred, frozen real-model runs, and the prospective multi-session observation. Supplier data-processing facts still need verification before broader trials. No new product-level decision is required by this specification; engineering limits remain tunable and must be assessed by actual use.
The issue tracker and triage configuration have not been provided. The to-spec skill requires: “If not, tell the user to run /setup-matt-pocock-skills.” This local specification is complete; publication to the configured tracker with ready-for-agent remains pending that setup. Do not infer a publication destination, claim an issue exists or publish tickets in its place.
