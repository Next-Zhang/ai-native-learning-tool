# AI 产品需求文档（AI PRD）模板调研报告

> 调研目的：为一个真实 AI 产品（AI Native Learning Tool：以 LLM 为核心执行者的学习教练 Agent，Python + DeepSeek API，状态机闭环 + 本地 RAG 知识库）撰写 PRD，需要判断业界是否存在比经典 10 节模板更标准的「AI PRD」结构。
>
> 调研方法：优先抓取一手/权威来源正文（官方文档、标准、监管说明），逐条核对。**本报告中每一条断言均可回溯到文末「参考来源」中的链接；无法核实的明确标注「未验证」。**
>
> 网络环境说明：本次调研所在网络**无法直接抓取 `pair.withgoogle.com`（Google PAIR）与 `developers.openai.com` 的页面正文**（连接被重置 / HTTP 403）。这两个来源的内容仅通过搜索结果标题与 URL 结构交叉印证，凡未取得正文者均已单独标注。详见第 5 节。

---

## 1. 结论：业界是否存在「标准 AI PRD 模板」？

### 判断：**部分存在（Partial）。** 不存在一份被广泛采用、以「AI PRD」命名的统一文档模板；但存在一组被广泛采用、且互补的**权威框架**，它们共同定义了 AI 产品需求中「传统 PRD 没有的那部分」应该写什么。

**依据（可验证的推理链）：**

1. **标准与监管层存在，但它们是「风险治理 / 管理体系」框架，不是 PRD 模板。**
   - NIST AI RMF 1.0 明确说明其 Core 由 **govern / map / measure / manage** 四个功能构成，并**明确写道「Actions do not constitute a checklist, nor are they necessarily an ordered set of steps」**——即它刻意不是一份填空式模板（[NIST AI RMF Core](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）。
   - EU AI Act 是**法律框架**，规定 high-risk 系统在上市前须满足的义务（风险评估与缓解、数据集质量、活动日志可追溯、技术文档、给部署者的信息、人类监督、鲁棒性/网络安全/准确性），这是**合规要求**而非文档模板（[AI Act | Shaping Europe's digital future](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)）。
   - ISO/IEC 42001 的官方标准页在本次调研中返回 403（Cloudflare 拦截），**未能取得正文**，因此本报告不对其章节结构下任何具体断言（[ISO/IEC 42001:2023 标准页](https://www.iso.org/standard/81230.html)，访问受阻）。

2. **平台厂商层存在「设计 / 架构 / 评测」框架，同样不叫 PRD，也不构成统一模板。**
   - Microsoft 的 HAX Toolkit 自述为「面向构建 user-facing AI 产品的团队」，**用于「早期设计流程（Use it early in your design process）」以及「需求定义阶段（the requirements definition stage of planning a new product）」**，其产物是「优先化的待办项」，不是 PRD（[HAX Toolkit](https://www.microsoft.com/en-us/haxtoolkit/)、[HAX Workbook](https://www.microsoft.com/en-us/haxtoolkit/workbook/)）。
   - AWS Well-Architected Generative AI Lens 是**架构最佳实践 lens**，覆盖 operational excellence / security / reliability / performance efficiency / cost optimization / sustainability 六大支柱，以及 scoping → model selection → customization → development → deployment → continuous improvement 生命周期（[AWS Generative AI Lens](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)）。
   - Microsoft Azure Well-Architected 的 AI workload 指南把「Testing and evaluation」「Responsible AI」「Grounding data design」「MLOps and GenAIOps」列为独立的设计领域（[AI workload documentation](https://learn.microsoft.com/en-us/azure/well-architected/ai/)）。

3. **「AI PRD 模板」这一命名主要出现在社区/培训机构/个人仓库中，属于二手或非权威来源。**
   - 本次调研找到若干以「AI PRD Template」为名的仓库文件（如 [vasilyu1983/AI-Agents-public 的 ai-prd-template.md](https://raw.githubusercontent.com/vasilyu1983/AI-Agents-public/refs/heads/main/frameworks/shared-skills/skills/docs-ai-prd/assets/prd/ai-prd-template.md)）与其引用的 [institutepm.com AI Feature PRD Template](https://www.institutepm.com/knowledge-hub/ai-feature-prd-template)。前者结构完整且自述引用了 NIST AI RMF 1.0 / NIST GenAI Profile / ISO/IEC 42001 / EU AI Act / OpenAI eval guides / OWASP GenAI，**但它们不是厂商、标准机构或监管机构发布的官方模板，不可当作「标准」引用**。
   - **未找到** OpenAI、Anthropic、Google、Microsoft、AWS 任何一家发布过名为「AI PRD」的官方模板。这一点是**「未找到证据」，不等于「不存在」**。

4. **因此，对实际写作最有价值的判断是：** 把 AI PRD 视为「**经典 PRD 骨架 + 四类权威框架的强制增补**」——
   - 风险与治理 → NIST AI RMF 1.0 / NIST AI 600-1 GenAI Profile / EU AI Act；
   - 交互与信任 → Microsoft HAX Guidelines / Google PAIR Guidebook；
   - 架构与运维 → AWS Generative AI Lens / Azure Well-Architected AI；
   - 评测与验收 → OpenAI evals 与 Anthropic「Define success criteria and build evaluations」/「Building effective agents」。

---

## 2. 来源清单与逐个要点

以下按「来源机构 → 名称 → 适用场景 → 它新增了哪些传统 PRD 没有的章节」组织。**标注 `[已取正文]` 者为本次调研实际抓取并逐条核对过内容；标注 `[仅检索印证]` 者为页面正文未能取得正文。**

### 2.1 NIST — AI Risk Management Framework (AI RMF) 1.0 `[已取正文]`
- **机构**：美国国家标准与技术研究院（NIST）
- **链接**：https://airc.nist.gov/airmf-resources/airmf/5-sec-core/ （Core 章节正文）
- **适用场景**：任何 AI 系统的风险治理、跨职能对话与生命周期管理；自愿性框架。
- **新增章节/要素（对照传统 PRD）**：
  - **Govern（治理，横切）**：法律与监管要求的识别与管理（Govern 1.1）、风险评估级别与组织风险容忍度（1.3）、风险管理的持续监控与周期评审（1.5）、AI 系统清单（1.6）、**系统下线与淘汰流程（1.7）**、角色与责任（2.1）、高管对 AI 风险决策负责（2.3）、**human-AI 配置与监督的角色区分（3.2）**、**第三方软件与数据的供应链风险（6.1）及第三方数据/AI 系统失败的应急流程（6.2）**。
  - **Map（情境化）**：预期用途与部署情境、用户期望与正负面影响（Map 1.1）、**业务价值（1.4）**、**系统需求（如「系统应尊重用户隐私」）（1.6）**、任务与方法（分类器/生成模型/推荐器）（2.1）、**系统知识边界与人类监督方式（2.2）**、**TEVV 与数据采集/选择/代表性（2.3）**、**潜在成本含非货币成本（3.2）**、**人类监督流程（3.5）**、**第三方组件的法律与 IP 风险（4.1）**。
  - **Measure（度量）**：无法度量的风险须明确记录（Measure 1.1）、独立评审者参与（1.3）、**测试集/指标/工具文档化（2.1）**、**生产环境中的功能与行为监控（2.4）**、**安全评估与「可安全失败（fail safely）」（2.6）**、**安全性与韧性（2.7）**、**可解释性（2.9）**、**隐私风险（2.10）**、**公平性与偏差（2.11）**、**环境影响（2.12）**、**面向终端用户与受影响群体的反馈/申诉机制（3.3）**。
  - **Manage（处置）**：**是否继续开发/部署的判定（1.1）**、风险优先级与处置（缓解/转移/规避/接受）（1.3）、**残余风险文档（1.4）**、**非 AI 替代方案对比（2.1）**、**停用/脱离/停机的机制与责任人（2.4）**、**预训练模型纳入常态监控（3.2）**、**部署后监控、申诉与覆盖、下线、事件响应、恢复、变更管理（4.1）**、**事件与错误的沟通与跟踪（4.3）**。

### 2.2 NIST — AI 600-1：Generative AI Profile `[已取正文]`
- **机构**：NIST
- **链接**：https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence （DOI: https://doi.org/10.6028/NIST.AI.600-1）
- **适用场景**：生成式 AI 的跨行业风险画像，是 AI RMF 1.0 的配套 profile；2024-07-26 发布。
- **新增要素**：它把 AI RMF 的通用风险条目**落到生成式 AI 特有风险**上（如内容真实性、信息完整性等）。因正文 PDF 未在本次调研中逐页核对，**具体风险清单条目未验证**；此处仅确认其定位与发布时间。

### 2.3 欧盟委员会 — EU AI Act（Regulation (EU) 2024/1689） `[已取正文]`
- **机构**：European Commission（DG CONNECT）
- **链接**：https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai ；法条原文 https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32024R1689
- **适用场景**：在欧盟投放/使用 AI 系统的 provider 与 deployer；四档风险分级（unacceptable / high-risk / transparency / minimal）。
- **对 PRD 的强制新增章节**：
  - **风险分级与法律定性**（本产品是否落入 high-risk；注意 educational institution 相关用途被明确列入 high-risk，如「scoring of exams」）。
  - **High-risk 义务清单**（页面原文）：充分的风险评估与缓解系统；**用于喂给系统的数据集的高质量（以降低歧视性结果风险）**；**活动日志以保证结果可追溯**；**详尽技术文档**以供主管机构评估合规；向 deployer 提供清晰充分的信息；**适当的人类监督措施**；**高水平的鲁棒性、网络安全与准确性**。
  - **透明度义务**：聊天机器人场景下须让人知晓在与机器交互；生成式 AI provider 须保证 AI 生成内容可识别；深度伪造与面向公众的信息性文本须清晰显著标注。
  - **GPAI 相关**：训练内容公开摘要模板要求披露数据来源（含大型数据集与顶级域名）。
  - **时间线**（页面当前表述）：AI Act 于 2024-08-01 生效、2026-08-02 成为 applicable（含例外）；禁止性实践自 2025-02-02 适用；GPAI 义务自 2025-08-02 适用；high-risk 敏感领域（Annex III）延至 **2027-12-02**，嵌入受监管产品的 high-risk（Annex I）延至 **2028-08-02**（因 AI Omnibus 简化提案）。**页面「Last update」为 2026-08-03，上述日期以该页面当前表述为准。**

### 2.4 AWS — Well-Architected Framework: Generative AI Lens `[已取正文]`
- **机构**：Amazon Web Services
- **链接**：https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html （发布日期 2025-11-19）
- **适用场景**：在 AWS 上设计、部署与运营生成式 AI 应用的架构师、builder、安全专家、MLOps 工程师与决策者；基于 Amazon Bedrock / SageMaker AI 的基础模型。
- **新增章节/要素（页面逐条列出）**：
  - **Operational excellence**：**维持一致的模型输出质量**、监控并管理运营健康、**保持可追溯性**、自动化生命周期管理、**判断何时执行模型定制（customization）**。
  - **Security**：保护生成式 AI 端点、**缓解有害输出与「excessive agency（过度自主权）」风险**、监控与审计事件、**保护 prompt 并修复模型投毒风险**。
  - **Reliability**：吞吐要求、可靠组件通信、**可观测性**、**优雅处理失败**、**制品（artifact）版本化**、分布式推理。
  - **Performance efficiency**：捕获并改进模型性能、**数据检索性能**。
  - **Cost optimization**：**选择成本优化的模型**、**平衡推理成本与性能**、**为成本而工程化 prompt**、**优化向量存储与 agent 工作流**。
  - **Sustainability**：最小化训练/定制/托管/数据处理与存储的算力。
  - **生命周期阶段划分**：scoping → model selection → customization → development → deployment → continuous improvement；并强调 model producer / provider / consumer 之间的**共享责任**。

### 2.5 Microsoft — HAX Toolkit（Guidelines for Human-AI Interaction 等） `[已取正文]`
- **机构**：Microsoft Research / Microsoft HAX
- **链接**：https://www.microsoft.com/en-us/haxtoolkit/ ；18 条指南 https://www.microsoft.com/en-us/haxtoolkit/ai-guidelines/ ；工作簿 https://www.microsoft.com/en-us/haxtoolkit/workbook/
- **适用场景**：面向用户的 AI 产品；**在早期设计流程与「需求定义阶段」使用**；跨 UX / AI / 项目管理 / 工程协作。
- **新增章节/要素**：
  - **AI 行为规范**（系统在各种情况下应如何表现），按四个时机制定：**initial interaction / during interaction / when the AI system is wrong / over time**（[ai-guidelines](https://www.microsoft.com/en-us/haxtoolkit/ai-guidelines/)）。
  - **失败规划**：HAX Playbook 用于「识别常见失败，以便规划缓解措施」，并自述适用于**使用自然语言处理（NLP）的应用**——页面原文：「identify common failures so you can plan for mitigating them」。
  - **跨学科需求估算**：HAX Workbook 要求对每条高优先级指南估算 **UI / AI / data / engineering requirements**，并用 T-shirt sizing 排序取舍。
  - **一句被记录下来的从业者反馈**（可用于说服团队为何 AI 需求要进 spec）：页面引用团队原话「**if the spec doesn't have that built into it, it's gonna be rigid to respond**」，以及「AI is the most ambiguous space I've ever worked in … There aren't any real rules and we don't have a lot of tools.」
- **边界说明**：HAX 是**交互与信任**框架，不覆盖模型选型、成本预算、合规分级。

### 2.6 Microsoft — Azure Well-Architected Framework: AI workloads `[已取正文]`
- **机构**：Microsoft
- **链接**：总览 https://learn.microsoft.com/en-us/azure/well-architected/ai/ ；Testing and evaluation https://learn.microsoft.com/en-us/azure/well-architected/ai/test
- **适用场景**：设计 AI workload 的架构与工程团队，明确以「**非确定性行为**」作为 AI workload 与传统 workload 的根本差异。
- **新增章节/要素**：
  - **评测与测试分离**：「Evaluation」是开发阶段选模型/调参的迭代活动；「Testing」是**变更管理策略（non-negotiable change management strategy）**，验证端到端系统（含非 AI 组件）是否达到目标并防止质量回退。
  - **质量指标**：**Groundedness（回答是否由所给上下文支撑而非编造）**、fairness 等，并明确「避免只依赖单一指标」，指标作为**调参与部署的决策门槛（decision gates）**。
  - **Golden dataset**：由人创建或校验的可信输入-输出对，作为客观基准；样本不足时用合成数据补足多样性与覆盖。
  - **Agentic workflow 验证**：因 agent **非确定性**，静态测试不足；须验证从用户输入到最终回答的完整链路（grounding data 检索 → 工具调用 → 回答生成）；建议的专项检查包括 **intent resolution（是否理解请求）**、**tool call accuracy（工具与参数是否正确）**、**task adherence（输出是否符合任务与前序推理）**。
  - **安全测试**：jailbreak 测试（攻击者常先打编排层）、内容安全（用户 prompt 与 grounding context 都过安全服务）、端点安全。
  - **确定性组件与路由逻辑的单元测试**：路由逻辑要做功能/性能/可靠性测试；用 Semantic Kernel / LangChain 时须单测 prompt 模板、工具选择逻辑、数据格式与决策树。
  - **推理端点测试**：功能与集成、性能与负载（**token/秒 或 token/分 比传统请求大小更有意义**）、缩容与 GPU 优化、**失败处理（429 限流、后端超时、服务不可用；验证重试、退避、熔断）**。
  - **Grounding data / RAG 工作流测试**（对本产品尤其直接）：数据加载完整性、**索引 schema 向后兼容**、预处理与分块及 embedding 计算、**数据新鲜度与质量检查（陈旧数据、版本错配、空表）**、索引负载测试、**文档按访问控制分区时的权限测试**。
  - **模型衰减（model decay）**：区分 **data drift（输入数据变化）** 与 **concept drift（外部条件变化）**；用自动化测试比对预测与真实结果，用统计指标监控漂移，并把用户反馈（如 thumbs up/down）作为信号。

### 2.7 Google — People + AI Guidebook（PAIR） `[仅检索印证，正文未能抓取]`
- **机构**：Google People + AI Research (PAIR)
- **链接**：https://pair.withgoogle.com/guidebook/ ；示例章节 https://pair.withgoogle.com/chapter/mental-models
- **说明**：本次调研网络**无法建立到 `pair.withgoogle.com` 的连接**（连接被重置），因此**未能取得正文**。以下仅为可通过检索结果 URL 结构与标题印证的章节名，**建议使用者在可联网环境下自行核对后再引用**：
  - 检索结果中出现的指南/工作表文件名与章节路径包括 **Mental Models**（`/chapter/mental-models`）、**Explainability + Trust**、**Feedback + Control**、**Errors + Graceful Failure**、**Data Collection + Evaluation**、**User Needs + Defining Success**（依据：检索返回的 PAIR 工作表 PDF 路径 `pair.withgoogle.com/worksheet/People + AI Guidebook - All Worksheets.pdf` 与章节 URL）。
  - **未验证**：各章节的具体内容、完整章节数、以及是否有更新版本。

### 2.8 Anthropic — 「Building effective agents」 `[已取正文]`
- **机构**：Anthropic（作者 Erik S.、Barry Zhang；2024-12-19）
- **链接**：https://www.anthropic.com/engineering/building-effective-agents
- **适用场景**：构建 LLM agent / agentic system 的团队；本产品作为「学习教练 Agent」高度相关。
- **新增章节/要素**：
  - **workflow vs agent 的架构定性**：「workflows 是由预定义代码路径编排 LLM 与工具」「agents 是 LLM 动态决定自身流程与工具使用」。**PRD 需要先声明本产品属于哪一种**——这直接决定测试策略与验收标准。
  - **是否需要 agent 的论证**：建议先用最简单方案；agentic system 往往**用延迟与成本交换任务表现**；很多场景「用 retrieval 与 in-context examples 优化单次 LLM 调用就已足够」。
  - **复杂度与可调试性的取舍**：框架会引入抽象层，**掩盖底层 prompt 与 response，使其更难调试**。
  - **模式选择**：prompt chaining（含中间步骤的 programmatic gate 校验）、**routing（把简单/常见问题路由到更小更省的模型，难题路由到更强模型，以优化表现）**、parallelization（sectioning / voting）、orchestrator-workers、**evaluator-optimizer（有明确评估标准时用 LLM 做评估反馈循环）**、autonomous agents（**须有停止条件如最大迭代次数以保持控制**）。
  - **Human-in-the-loop 设计**：「agents 可在检查点或遇到阻塞时暂停等待人工反馈」。
  - **三原则**：保持设计简洁、**显式展示 agent 的规划步骤以提升透明度**、精心设计 agent-computer interface (ACI) 并通过**充分的工具文档与测试**打磨。
  - **已知风险**：「自主性意味着更高成本，以及**误差累积（compounding errors）**的风险」，建议在沙箱环境充分测试并加 guardrails。

### 2.9 Anthropic — 「Define success criteria and build evaluations」 `[仅检索印证]`
- **链接**：https://platform.claude.com/docs/en/test-and-evaluate/develop-tests
- **说明**：该 URL 在本次调研中发生 cross-origin 重定向至 `anthropic.com`，**正文未取得**。可确认的是该文档存在且标题为「Define success criteria and build evaluations」，并含 `#building-evals-and-test-cases` 锚点（依据检索结果）。**具体内容未验证。**

### 2.10 OpenAI — Evals / evaluation best practices `[仅检索印证]`
- **链接**：https://developers.openai.com/api/docs/guides/evaluation-best-practices ；https://developers.openai.com/api/reference/resources/evals ；https://developers.openai.com/api/docs/guides/agent-evals
- **说明**：`developers.openai.com` 在本次调研中对多个路径返回 **HTTP 403 Forbidden**，**正文未取得**。可确认的仅为页面存在与标题（「Evaluation best practices」「Evals」「Evaluate agent workflows」「Testing Agent Skills Systematically with Evals」）。**具体最佳实践条目未验证。**

### 2.11 社区/非权威来源（仅供补充，不应作为「标准」引用）
- [AI PRD Template (AI Feature / AI System)](https://raw.githubusercontent.com/vasilyu1983/AI-Agents-public/refs/heads/main/frameworks/shared-skills/skills/docs-ai-prd/assets/prd/ai-prd-template.md) `[已取正文]`：一份结构完整的社区模板，自述引用 NIST AI RMF 1.0、NIST GenAI Profile、ISO/IEC 42001、EU AI Act、OpenAI eval guides、OWASP GenAI security guidance。**非厂商/标准机构发布。** 它的存在本身是对第 1 节结论的佐证：社区需要自建模板，恰因没有官方统一模板。
- [institutepm.com — AI Feature PRD Template](https://www.institutepm.com/knowledge-hub/ai-feature-prd-template) `[仅检索印证]`：培训机构内容，**未核正文**。
- [Sequoia Capital — Generative AI's Act Two](https://sequoiacap.com/article/generative-ai-act-two) `[正文抓取为空]`：页面返回 200 但正文为空，**本报告不基于它提出任何主张**。

---

## 3. AI 产品特有需求要素清单（要素 | 说明 | 来源）

> 来源列中的链接指向文末参考来源。标注「（社区）」者为非权威来源，仅作补充。

| # | 要素 | 说明（为什么传统 PRD 没有） | 来源 |
|---|------|------------------------------|------|
| 1 | **模型选择与路由策略** | 传统 PRD 不涉及模型；AI 产品需声明选哪个模型、何时路由到更小/更便宜的模型、何时升级到更强模型 | Anthropic《Building effective agents》routing 段（[链接](https://www.anthropic.com/engineering/building-effective-agents)）；AWS GenAI Lens「Select cost-optimized models」（[链接](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)） |
| 2 | **workflow vs agent 架构定性** | 决定测试策略、验收标准与自主权边界；传统 PRD 无此维度 | Anthropic《Building effective agents》（[链接](https://www.anthropic.com/engineering/building-effective-agents)） |
| 3 | **Prompt / 上下文（ACI、工具描述）设计** | Prompt 与工具描述是需要被评审、测试与版本化的「接口」，而非实现细节 | Anthropic《Building effective agents》Appendix 2 与三原则（[链接](https://www.anthropic.com/engineering/building-effective-agents)）；Azure「单测 prompt 模板、工具选择逻辑」（[链接](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)） |
| 4 | **RAG / grounding 知识源与更新、索引测试** | 知识源、分块与索引 schema、新鲜度、权限分区需要独立验收 | Azure WAF AI「Test the grounding data workflow」「Grounding data design」（[链接](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)、[链接](https://learn.microsoft.com/en-us/azure/well-architected/ai/)） |
| 5 | **评测与基准（evals）：golden dataset、ship bar、guardrail bar** | 需要预先定义可复现的评测集与「发布门槛」，而非只定义业务 KPI | Azure WAF AI：golden dataset、decision gates、避免单一指标（[链接](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)）；NIST Measure 1.1/2.1（[链接](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）；OpenAI/Anthropic 评测文档（[OpenAI](https://developers.openai.com/api/docs/guides/evaluation-best-practices)、[Anthropic](https://platform.claude.com/docs/en/test-and-evaluate/develop-tests)，**均未核正文**） |
| 6 | **非确定性下的验收标准** | 同一输入可能产生不同输出，传统「通过/不通过」式验收失效；须改为指标门槛 + 抽样 + 人工评审 | Azure WAF AI：静态测试不足、scenario-based test + 自动评分 + 人工评审、intent resolution / tool call accuracy / task adherence（[链接](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)） |
| 7 | **幻觉与失败兜底（groundedness、优雅失败）** | 需定义「答不出来时怎么办」以及可安全失败 | Azure WAF AI：Groundedness 指标（[链接](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)）；NIST Measure 2.6「can fail safely」（[链接](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）；AWS GenAI Lens 「handle failures gracefully」（[链接](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)）；Microsoft HAX Playbook「识别常见失败以规划缓解」（[链接](https://www.microsoft.com/en-us/haxtoolkit/)） |
| 8 | **Human-in-the-loop 边界与人类监督** | 需明确哪些决策必须人类确认、哪些副作用需审批 | NIST Map 3.5 / Measure 1.3 / Govern 3.2（[链接](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）；EU AI Act high-risk 义务「appropriate human oversight measures」（[链接](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)）；Anthropic「可在检查点暂停等待人工反馈」（[链接](https://www.anthropic.com/engineering/building-effective-agents)） |
| 9 | **成本与延迟预算** | token 成本与延迟随用量线性增长，须作为需求约束而非事后优化 | AWS GenAI Lens Cost optimization 支柱（[链接](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)）；Anthropic「agentic system 用延迟与成本交换表现」（[链接](https://www.anthropic.com/engineering/building-effective-agents)）；Azure「stress testing 成本影响」（[链接](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)） |
| 10 | **安全：prompt 注入、jailbreak、工具滥用、过度自主权、模型投毒** | 传统 PRD 的安全章节不覆盖 LLM 特有攻击面 | AWS GenAI Lens Security 支柱「excessive agency」「secure prompts」「model poisoning」（[链接](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)）；Azure WAF AI「jailbreak testing、content safety、endpoint security」（[链接](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)） |
| 11 | **隐私与数据权利、保留、驻留、第三方数据风险** | 涉及供应商数据使用条款、评测数据所有权与新鲜度策略 | NIST Map 4.1 / Measure 2.10 / Govern 6.1（[链接](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）；EU AI Act 数据集质量义务、GPAI 训练内容披露（[链接](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)） |
| 12 | **合规分级与技术文档** | 需先判定风险等级，再据此决定文档深度；教育场景在 EU 被明确列为 high-risk 情形之一 | EU AI Act 四档风险与 high-risk 义务（[链接](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)）；NIST Govern 1.1（[链接](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)） |
| 13 | **可观测性、日志、可追溯与监控** | 需要记录输入输出与决策链路，才能复现与审计 | AWS GenAI Lens Operational excellence「maintain traceability」（[链接](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)）；EU AI Act「logging of activity to ensure traceability」（[链接](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)）；NIST Measure 2.4（[链接](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)） |
| 14 | **漂移与模型衰减监控（data drift / concept drift）** | 上线后质量会自然劣化，需常态监控而非一次性验收 | Azure WAF AI「Testing for model decay」data drift vs concept drift（[链接](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)） |
| 15 | **人工接管 / 降级 / 停机与下线** | 需要明确「何时脱离、停用、下线」的责任人与机制 | NIST Manage 2.4、Govern 1.7（[链接](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）；AWS GenAI Lens reliability「handle failures gracefully」（[链接](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)） |
| 16 | **模型与制品版本变更管理** | 模型/提示/索引任一变更都可能改变行为，须纳入变更管理与回归测试 | AWS GenAI Lens「version artifacts」「automate lifecycle management」（[链接](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)）；NIST Manage 4.1「change management」、Manage 3.2「预训练模型纳入常态监控」（[链接](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）；Azure「Testing 是变更管理策略，防止质量回退」（[链接](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)） |
| 17 | **透明度与用户告知** | 用户须知道在与机器交互；AI 生成内容需可识别 | EU AI Act transparency 义务（[链接](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)）；Microsoft HAX Guidelines（[链接](https://www.microsoft.com/en-us/haxtoolkit/ai-guidelines/)）；Google PAIR Explainability + Trust（**未验证**） |
| 18 | **心智模型与用户期望管理** | AI 能力边界需被用户正确理解，否则产生误用与失望 | Google PAIR「Mental Models」章节（[链接](https://pair.withgoogle.com/chapter/mental-models)，**正文未验证**）；Microsoft HAX「when the AI system is wrong」时机（[链接](https://www.microsoft.com/en-us/haxtoolkit/ai-guidelines/)） |
| 19 | **用户反馈与申诉/覆盖机制** | 需要建立用户上报问题与申诉系统结论的通道，并纳入评测指标 | NIST Measure 3.3、Manage 4.1（appeal and override）（[链接](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）；Azure 用户 thumbs up/down 作为漂移信号（[链接](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)） |
| 20 | **训练/微调数据来源与许可；是否需要定制模型** | 需声明数据来源、权利基础、是否微调及何时定制 | NIST Map 2.3、Map 4.1（[链接](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）；AWS GenAI Lens「determine when to execute model customization」（[链接](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)）；EU AI Act GPAI 训练内容摘要模板（[链接](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)） |
| 21 | **共享责任与第三方/供应链风险** | 使用外部模型即引入供应商依赖与条款风险 | AWS GenAI Lens「shared responsibilities between model producers, providers and consumers」（[链接](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)）；NIST Govern 6.1/6.2、Manage 3.1（[链接](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)） |
| 22 | **可及性/公平性/偏差评估** | 生成式系统可能对不同群体产生不均衡影响 | NIST Measure 2.11（[链接](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）；Azure「即使 groundedness 强也可能有偏差，需纳入公平性评估」（[链接](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)） |
| 23 | **非 AI 替代方案与「为什么必须用 AI」** | 需要论证 AI 相对于确定性代码/人工流程的增量价值 | NIST Manage 2.1「对比可行的非 AI 替代方案」（[链接](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）；Anthropic「先找最简单方案，必要时才增加复杂度」（[链接](https://www.anthropic.com/engineering/building-effective-agents)） |
| 24 | **上线策略：shadow / canary / A-B / kill switch / 回滚** | 非确定性系统的发布需要分阶段与停止规则 | NIST Manage 4.1、Govern 1.7（[链接](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）；Azure「side-by-side deployments、A/B tests、告警」（[链接](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)） |
| 25 | **评测集与评测数据治理（所有权、新鲜度、盲点）** | 评测集会随产品演进失效，需明确维护责任 | Azure golden dataset 与合成数据补足（[链接](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)）；NIST Measure 1.2「定期评估指标适用性与控制有效性」、Measure 1.1「无法度量的风险须记录」（[链接](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)） |
| 26 | **环境/可持续性影响** | 训练与推理的算力消耗需被评估 | NIST Measure 2.12（[链接](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）；AWS GenAI Lens Sustainability 支柱（[链接](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)） |

---

## 4. 推荐的 AI PRD 章节结构（含与经典 10 节的映射）

### 4.1 设计原则

1. **不推翻经典 10 节，而是保留其骨架**：问题陈述、用户画像、成功指标、用户故事、不做范围、依赖风险、待定问题在 AI 产品中依然成立，且 NIST Map 1.4 明确要求「业务价值或业务使用情境必须被清楚定义」——经典章节是它的实现方式（[NIST AI RMF Core](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）。
2. **新增章节来自四组权威框架的强制增补**，而不是凭空的「AI 味道」清单。
3. **把「验收标准」从一节拆成两节**（业务成功指标 vs AI 质量评测），因为 Azure WAF 明确要求把 evaluation 与 testing 视为不同过程并使用不同数据集，且 NIST 要求记录「无法度量的风险」（[Azure](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)、[NIST](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）。

### 4.2 推荐章节结构与映射表

| 推荐节 | 与经典 10 节的映射 | 为什么（来源支撑） |
|--------|-------------------|-------------------|
| **0. 执行摘要** | 经典 §1 执行摘要（保留） | 保留；但摘要中应增加一句「本产品的 AI 自主权等级与风险分级」。依据：Anthropic 的 workflow vs agent 定性会改变整个系统的成本/延迟/测试策略（[Anthropic](https://www.anthropic.com/engineering/building-effective-agents)）；EU AI Act 要求先定风险等级（[EU](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)）。 |
| **1. 问题陈述与「为什么必须用 AI」** | 经典 §2 问题陈述（合并增强） | **新增论证**：对比可行的非 AI 替代方案或人工流程基线。依据：NIST Manage 2.1；Anthropic 建议「先找最简单方案，只有明显提升结果时才增加复杂度」（[NIST](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)、[Anthropic](https://www.anthropic.com/engineering/building-effective-agents)）。 |
| **2. 用户画像与心智模型** | 经典 §3 用户画像（合并增强） | **新增**：用户对 AI 能力的预期与误解、以及系统如何主动校准这些预期。依据：Google PAIR 把「Mental Models」列为独立章节（[PAIR Mental Models](https://pair.withgoogle.com/chapter/mental-models)，**正文未验证**）；Microsoft HAX 把「initial interaction」与「when the AI system is wrong」列为必须设计的时机（[HAX](https://www.microsoft.com/en-us/haxtoolkit/ai-guidelines/)）。 |
| **3. 战略背景、风险分级与合规定性** | 经典 §4 战略背景（扩展） | **新增**：风险等级判定（本产品若进入教育机构场景，EU AI Act 明确把「AI solutions used in education institutions, that may determine the access to education」列入 high-risk）、以及由此触发的技术文档与人类监督义务（[EU AI Act](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)；NIST Govern 1.1）。 |
| **4. 方案概述：系统边界与架构定性** | 经典 §5 方案概述（拆分之一） | **新增**：输入/输出、运行位置、**workflow vs agent 定性**、**模型选择与路由策略**、工具与集成权限、**系统可触发的副作用及其审批边界**。依据：Anthropic routing 与 agent 定义；AWS GenAI Lens Security 支柱的「excessive agency」；NIST Map 2.1/2.2（[Anthropic](https://www.anthropic.com/engineering/building-effective-agents)、[AWS](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)、[NIST](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）。 |
| **5. Prompt / 上下文 / 工具接口设计** | 经典 §5 方案概述（拆分之二，**全新**） | **新增整节**。Prompt 与工具描述是需要被评审、测试、版本化的接口。依据：Anthropic 三原则之一「carefully craft your agent-computer interface (ACI) through thorough tool documentation and testing」，并把工具定义与整体 prompt 同等对待；Azure 要求对 prompt 模板与工具选择逻辑做单元测试（[Anthropic](https://www.anthropic.com/engineering/building-effective-agents)、[Azure](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)）。 |
| **6. 知识源与 RAG 规格**（本产品必需） | 经典 §7 依赖（部分）＋**新增** | **新增整节**。知识源清单、权利基础、分块与索引 schema、更新频率与新鲜度阈值、索引权限分区、检索质量验收。依据：Azure WAF AI「Test the grounding data workflow」逐项列出数据加载、schema 兼容、分块与 embedding、**数据新鲜度检查**、索引负载、**访问控制分区测试**；并设有独立的「Grounding data design」设计领域（[Azure](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)、[Azure AI 总览](https://learn.microsoft.com/en-us/azure/well-architected/ai/)）。 |
| **7. 成功指标（业务层）** | 经典 §6 成功指标（保留，收窄为业务指标） | 保留为业务价值指标；与第 8 节显式区分。依据：NIST Map 1.4 要求业务价值被清楚定义（[NIST](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）。 |
| **8. AI 质量评测与验收标准（evals）** | 经典 §6 成功指标（拆分之二，**全新重点节**） | **新增整节**：golden dataset 与标注方法、质量指标（含 groundedness）、安全指标、成本/延迟指标、**ship bar 与 guardrail bar**、离线/人工/在线三层评测、**已知盲点**、**无法度量的风险须明确记录**。依据：Azure WAF「evaluation 与 testing 是不同过程、不同数据集」「指标作为决策门槛」「避免单一指标」「scenario-based tests + 自动评分 + 人工评审」「intent resolution / tool call accuracy / task adherence」；NIST Measure 1.1/1.2/2.1、Measure 2.6「fail safely」（[Azure](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)、[NIST](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）；平台侧可参考 [OpenAI evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices) 与 [Anthropic develop-tests](https://platform.claude.com/docs/en/test-and-evaluate/develop-tests)（**两者正文均未验证**）。 |
| **9. 用户故事 + AI 交互行为规格** | 经典 §7 用户故事（扩展） | **新增**：按 HAX 的四个时机制定系统行为——initial interaction / during interaction / **when the AI system is wrong** / over time；并给出 AI 不可用时的降级行为。依据：Microsoft HAX Design Library 明确按这四个时机制定行为规范（[HAX](https://www.microsoft.com/en-us/haxtoolkit/ai-guidelines/)）。 |
| **10. 失败模式、幻觉与安全兜底** | 经典 §8 不做范围（并列**新增**） | **新增整节**：失败模式 × 用户/业务伤害 × 可能性 × 检测方式 × 缓解 × 残余风险。依据：Microsoft HAX Playbook 的用途就是「识别 NLP 应用的常见失败以便规划缓解」；NIST Measure 2.6 要求系统**可安全失败**、Manage 1.4 要求记录残余风险；AWS 要求 handle failures gracefully（[HAX](https://www.microsoft.com/en-us/haxtoolkit/)、[NIST](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)、[AWS](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)）。 |
| **11. 不做范围（Non-goals）与自主权边界** | 经典 §8 不做范围（合并增强） | **新增**：明确哪些决策系统**永不自作主张**（尤其对学习者的评估结论与画像更新），以及哪些副作用必须人工审批。依据：NIST Map 3.5 人类监督流程、Manage 2.4 脱离/停机机制；AWS「excessive agency」风险（[NIST](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)、[AWS](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)）。 |
| **12. Human-in-the-loop 与人工接管** | **全新** | 明确人类介入点、审批门、接管与申诉路径。依据：EU AI Act 对 high-risk 要求「appropriate human oversight measures」；NIST Govern 3.2 要求区分 human-AI 配置与监督的角色责任、Measure 3.3 要求建立反馈与申诉；Anthropic「agent 可在检查点暂停等待人工反馈」（[EU](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)、[NIST](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)、[Anthropic](https://www.anthropic.com/engineering/building-effective-agents)）。 |
| **13. 成本与延迟预算** | 经典 §9 依赖风险（拆出，**全新**） | **新增整节**：每次交互的 token/成本上限、P95 延迟目标、超预算时的降级策略（如路由到更小模型）。依据：AWS GenAI Lens 把「select cost-optimized models / balance cost and performance of inference / engineer prompts for cost」列为 Cost optimization 支柱的具体条目；Anthropic 指出 agentic system 用延迟与成本交换表现；Azure 提醒压测本身有成本（[AWS](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)、[Anthropic](https://www.anthropic.com/engineering/building-effective-agents)、[Azure](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)）。 |
| **14. 依赖、第三方与模型版本变更管理** | 经典 §9 依赖风险（扩展） | **新增**：模型/prompt/索引三个版本轴的变更管理、回归测试与回滚触发条件。依据：AWS「version artifacts」「automate lifecycle management」；NIST Manage 4.1「change management」、Manage 3.2「预训练模型纳入常态化监控」、Govern 6.1/6.2 第三方风险；Azure 把 Testing 定义为「防止质量回退的变更管理策略」（[AWS](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)、[NIST](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)、[Azure](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)）。 |
| **15. 监控、漂移与事件响应** | **全新** | 生产质量信号、漂移检测、告警阈值、事件分级与处置、上线后监控计划。依据：Azure「Testing for model decay」区分 data drift 与 concept drift 并建议用统计指标 + 用户反馈监控；NIST Measure 2.4 生产环境监控、Measure 3.1 持续跟踪风险、Manage 4.1 部署后监控与事件响应（[Azure](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)、[NIST](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）。 |
| **16. 安全、隐私与合规** | 经典 §9 依赖风险（拆出，**全新**） | **新增整节**：prompt 注入与 jailbreak 测试、工具滥用与越权、内容安全、日志与审计、数据保留与驻留、监管适用性与分类、自主副作用的审批要求。依据：AWS Security 支柱「secure prompts」「model poisoning」「excessive agency」「monitor and audit events」；Azure「jailbreak testing / content safety / endpoint security」；NIST Measure 2.7/2.10、Govern 1.1；EU AI Act 的技术文档、日志、数据集质量义务（[AWS](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)、[Azure](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)、[NIST](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)、[EU](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)）。 |
| **17. 上线与回滚策略** | **全新** | shadow / canary / A-B、feature flag 与 kill switch、停止规则、回滚触发条件、go/no-go 决策责任人。依据：NIST Manage 4.1（部署后监控、申诉与覆盖、下线、事件响应、变更管理）与 Manage 2.4（脱离/停用）；Azure 建议 side-by-side deployment、A/B test 与告警；AWS 生命周期含 continuous improvement（[NIST](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)、[Azure](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)、[AWS](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)）。 |
| **18. 待定问题（Open Questions）** | 经典 §10 待定问题（保留） | 保留；建议额外列出「尚未被度量覆盖的风险」（NIST Measure 1.1 要求把无法度量的风险明确记录）（[NIST](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）。 |

### 4.3 如果必须压缩：最小新增集（4 节）

若文档篇幅受限，按「传统 10 节之外**必须新增**」的优先级，只加这 4 节即可覆盖绝大部分 AI 特有风险：

1. **§8 AI 质量评测与验收标准（evals）** —— 没有它，非确定性系统无法被验收（[Azure](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)）。
2. **§6 知识源与 RAG 规格** —— 本产品的核心能力载体（[Azure grounding data workflow](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)）。
3. **§10 失败模式、幻觉与安全兜底** —— HAX Playbook 的成立前提就是「失败必然发生」（[HAX](https://www.microsoft.com/en-us/haxtoolkit/)）。
4. **§12 Human-in-the-loop 与自主权边界 / §11 不做范围中的自主权部分** —— 学习教练会输出对学习者的评估结论与画像，属于「AI 决定影响人」的场景（[NIST Govern 3.2 / Map 3.5](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)、[EU human oversight](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)）。

### 4.4 针对本产品的三个额外提示（基于已核来源）

- **成本与延迟**是本产品的高风险项：状态机闭环（目标澄清→能力测评→学习计划→每日任务→结果验收→画像更新）意味着**多轮 LLM 调用**，而 Anthropic 明确指出 agentic system 存在「更高成本」与「**误差累积（compounding errors）**」风险，并建议「在沙箱环境充分测试并加 guardrails」（[Anthropic](https://www.anthropic.com/engineering/building-effective-agents)）。
- **状态机的每一步都应可独立评测**：Azure 建议对编排链路做 scenario-based 测试，并检查 **intent resolution / tool call accuracy / task adherence** 三类指标，这正好对应状态机的各转移（[Azure](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)）。
- **本地 RAG 需要 schema 兼容与权限测试**：Azure 明确要求测试「index schema compatibility（向后兼容）」「data freshness（陈旧数据、版本错配、空表）」与「按访问控制分区时的权限测试」（[Azure](https://learn.microsoft.com/en-us/azure/well-architected/ai/test)）。

---

## 5. 未能验证 / 存在争议的点

**必须如实说明的限制：**

1. **Google PAIR《People + AI Guidebook》正文未取得。** 本次调研网络无法建立到 `pair.withgoogle.com` 的连接（`fetch failed`／连接被重置），PowerShell 直连亦失败（`基础连接已经关闭: 接收时发生错误`）。因此：
   - 报告中对 PAIR 章节名（Mental Models、Explainability + Trust、Feedback + Control、Errors + Graceful Failure、Data Collection + Evaluation、User Needs + Defining Success）的引用**仅来自检索结果的 URL 路径与文件名**，**未逐字核对正文**；
   - **未验证**其完整章节数、各章具体准入标准（criteria）与是否有新版。
2. **OpenAI 官方文档正文未取得。** `developers.openai.com` 的 `evaluation-best-practices`、`agent-evals`、`api/reference/resources/evals` 等路径在本次调研中返回 **HTTP 403 Forbidden**（"This request was blocked"）。**未验证**其具体最佳实践条目、评分器（graders）设计方法与推荐指标。
3. **Anthropic「Define success criteria and build evaluations」正文未取得。** 该 URL 发生 cross-origin 重定向，抓取被拒。**未验证**其具体内容与建议门槛。
4. **ISO/IEC 42001 正文未取得。** `iso.org` 标准页返回 403（Cloudflare "Just a moment..."）。因此本报告**未对 ISO/IEC 42001 的条款结构与要求做任何具体断言**，仅在「来源要求」意义上承认其存在（AI 管理体系标准）。**未验证**其具体章节。
5. **NIST AI 600-1（Generative AI Profile）只核到元数据。** 已确认标题、作者、发布时间（2024-07-26）、DOI 与定位（AI RMF 1.0 的生成式 AI 配套 profile）。**未验证**其具体风险清单条目。
6. **未找到任何厂商/标准机构发布的官方「AI PRD」模板。** 这是一个**否定性发现**：它意味着「AI PRD 没有官方统一模板」这一判断**只能被表述为「未找到证据」，而不能被表述为「已被证明不存在」**。本报告第 1 节因此采用「部分存在」而非「不存在」。
7. **「AI PRD」这一术语本身的来源不可考。** 检索显示该词主要出现在社区仓库与培训机构页面（如 institutepm.com、个人 GitHub 仓库）。**未验证**该术语最早出处与被行业采纳的程度。
8. **社区模板的引用真实性未复核。** 例如 [vasilyu1983/AI-Agents-public 的 ai-prd-template.md](https://raw.githubusercontent.com/vasilyu1983/AI-Agents-public/refs/heads/main/frameworks/shared-skills/skills/docs-ai-prd/assets/prd/ai-prd-template.md) 自述引用 NIST AI RMF 1.0、ISO/IEC 42001、EU AI Act、OWASP GenAI 等，但**它本身不是这些机构的出版物**，其对上述来源的转述**未逐条复核**，不应作为权威引用传递。
9. **EU AI Act 的日期信息以页面当前表述为准。** 抓取到的页面「Last update」为 2026-08-03，其中包含 2026 年的新闻条目与「AI Omnibus 于 2026-07-27 生效」等表述。本报告如实转录该页面表述，但**未通过 EUR-Lex 原文（CELEX:32024R1689）逐条交叉验证**这些时间线与义务的对应关系。
10. **存在争议/张力的一点**：Microsoft HAX 把自身定位为可在「**需求定义阶段（requirements definition stage）**」使用的工具，并在工作簿中要求估算「UI, AI, data, and engineering requirements」（[HAX Workbook](https://www.microsoft.com/en-us/haxtoolkit/workbook/)）——这是最接近「AI 需求文档」的官方产物；但 NIST AI RMF 又明确声明其 Core **不是 checklist**（[NIST](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)）。**两者并不矛盾，但都说明：权威机构刻意回避提供「填空式 AI PRD template」**，这是本报告判断「部分存在」而非「存在」的核心依据。

---

## 6. 参考来源

**已取得并核对正文的来源（Primary，已核）**

1. NIST — AI Risk Management Framework 1.0, AI RMF Core（govern / map / measure / manage 全部分类与子类）— https://airc.nist.gov/airmf-resources/airmf/5-sec-core/
2. NIST — AI 600-1: Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile（2024-07-26）— https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence ；DOI https://doi.org/10.6028/NIST.AI.600-1
3. European Commission — AI Act（四档风险、high-risk 义务、透明度义务、GPAI、时间线）— https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai ；法条 https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32024R1689
4. AWS — Well-Architected Framework: Generative AI Lens（2025-11-19）— https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html
5. Microsoft — HAX Toolkit 首页 — https://www.microsoft.com/en-us/haxtoolkit/
6. Microsoft — Guidelines for Human-AI Interaction / HAX Design Library — https://www.microsoft.com/en-us/haxtoolkit/ai-guidelines/
7. Microsoft — HAX Workbook（requirements definition stage、UI/AI/data/engineering 估算）— https://www.microsoft.com/en-us/haxtoolkit/workbook/
8. Microsoft — Azure Well-Architected Framework: AI workloads 总览（Testing and evaluation / Responsible AI / Grounding data design / MLOps and GenAIOps）— https://learn.microsoft.com/en-us/azure/well-architected/ai/
9. Microsoft — Azure Well-Architected Framework: Test and evaluate AI workloads on Azure（groundedness、golden dataset、agentic 验证、RAG 测试、model decay）— https://learn.microsoft.com/en-us/azure/well-architected/ai/test
10. Anthropic — Building effective agents（2024-12-19，Erik S. & Barry Zhang）— https://www.anthropic.com/engineering/building-effective-agents
11. 社区模板 — AI PRD Template (AI Feature / AI System)（**非权威**）— https://raw.githubusercontent.com/vasilyu1983/AI-Agents-public/refs/heads/main/frameworks/shared-skills/skills/docs-ai-prd/assets/prd/ai-prd-template.md

**存在但正文未能取得（Secondary / 待复核，已标注）**

12. Google PAIR — People + AI Guidebook（网络不可达）— https://pair.withgoogle.com/guidebook/ ；Mental Models 章节 https://pair.withgoogle.com/chapter/mental-models ；工作表 https://pair.withgoogle.com/worksheet/People%20+%20AI%20Guidebook%20-%20All%20Worksheets.pdf
13. OpenAI — Evaluation best practices（HTTP 403）— https://developers.openai.com/api/docs/guides/evaluation-best-practices
14. OpenAI — Evaluate agent workflows（HTTP 403）— https://developers.openai.com/api/docs/guides/agent-evals
15. OpenAI — Evals API reference（HTTP 403）— https://developers.openai.com/api/reference/resources/evals
16. Anthropic — Define success criteria and build evaluations（cross-origin 重定向，未取得）— https://platform.claude.com/docs/en/test-and-evaluate/develop-tests
17. ISO/IEC 42001:2023 — AI management system 标准页（HTTP 403，Cloudflare）— https://www.iso.org/standard/81230.html
18. institutepm.com — AI Feature PRD Template（培训机构内容，未核正文）— https://www.institutepm.com/knowledge-hub/ai-feature-prd-template
19. Sequoia Capital — Generative AI's Act Two（页面返回 200 但正文为空，本报告未据其提出主张）— https://sequoiacap.com/article/generative-ai-act-two

---

*报告生成时间：本次会话；所有链接均为调研当时可访问地址。标注 `[仅检索印证]` / 「未验证」的条目，建议在可自由联网的环境中复核后引用。*
