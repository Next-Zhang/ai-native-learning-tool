# 技术选型与模块接口设计

日期：2026-11-01。状态：目标开发设计，尚未实现。项目负责人已选择 Electron 桌面形态；本方案沿用现有 Python 核心，以 TypeScript 开发桌面交互，不进行整体 TypeScript 重写。

本文负责技术、依赖方向、进程通信和替换接口；产品行为以 [PRD](PRD.md) 为准，业务事件、领域对象与 tools 见 [本地后端设计](backend-design.md)。现有代码仍为 Python CLI v0.18，本文目录、命令和接口均不得当成已交付功能。

## 1. 技术选择与 feature 对照

| 功能 | 选用技术及落点 | 选择理由与实现边界 |
|---|---|---|
| 桌面窗口、菜单、退出、系统对话框 | Electron 主进程，TypeScript | 管理桌面生命周期与 Python 子进程；不持有学习规则 |
| 聊天、目标/矩阵、测评、计划与确认、结果/证据视图 | React + TypeScript + shadcn/ui（Base UI）+ Tailwind CSS，渲染进程 | 按项目负责人指定的 shadcn/ui 组件实现展示；复用应用结果，先用 React 自带状态管理，不加 Redux 或独立前端业务状态机 |
| 桌面构建与后续打包 | Electron Forge + Webpack TypeScript 模板，npm | 使用一套桌面工具链；本期交付源码运行，安装包不是首轮验收前提 |
| 界面到主进程 | preload 的 contextBridge + 固定 Electron IPC 通道 | 只暴露 submitEvent/query/onProgress；不暴露 ipcRenderer、文件或 shell 的通用调用 |
| 主进程到 Python | Node.js child_process.spawn + stdin/stdout，UTF-8 NDJSON | 一个长期运行后端；无本地端口、HTTP 服务或额外服务发现 |
| 跨语言数据契约 | Python Pydantic 2 定义 wire DTO → JSON Schema → 生成 TypeScript 类型；TS 用 Ajv 2020 校验 | Python 为契约权威；前端类型不手写另一套；类型检查不替代运行时校验 |
| 应用事件、确认、幂等、业务提交 | Python LocalApplication 与业务模块 | 服务 CLI 和桌面两种适配器，独立于 Electron 和 React |
| Workflow、复验及七天回顾 | Python 明确规则/状态与时间判断 | 不因换界面引入图引擎；关闭软件期间不承诺定时运行，返回时检查到期事项 |
| Agent 理解、行动选择、局部 ReAct | Python 受限循环 + 工具注册表 | 沿用已定 Workflow/Agent 分工；不新增 LangChain/LangGraph 依赖 |
| 模型调用 | 现有 openai Python SDK，默认沿用可配置的 DeepSeek 接入 | 仅模型适配器知道 SDK；统一重试/超时，不在 TS 再接一套模型调用 |
| prompt 库 | 现有 Python catalog、manifest、显式版本与 SHA-256 | 原文仍由 Python 管理；桌面不复制 prompt，不向界面传完整模型输入 |
| 联网搜索 | Brave Search API 的 Python SearchProvider 适配器，HTTPX | 明确首个供应商，使用用户自己的 BRAVE_SEARCH_API_KEY；需要用户自行开通，缺配置明确返回 configuration_required |
| 网页正文取回 | Python HTTPX + BeautifulSoup 的 html.parser | 先支持静态 HTML/文本；保留标题、段落、代码和来源；视频先保存链接/元数据，不声称已解析内容 |
| 可选本地 RAG | 保留现有实验模块及其可选依赖，通过检索接口接入 | 默认关闭，不强制下载嵌入模型；不拿 Python 教程库代替联网搜索 |
| 领域 Router、上下文与生命周期 | Python 领域模块、明确用途投影、缓存和触发策略 | 复用 [数据访问设计](data-access-design.md)；界面缓存不成为业务权威 |
| 本地状态与事务 | Python JSON 适配器、同目录临时文件 + os.replace、filelock 进程锁 | 保留单文件事务；仅 Python 写业务数据，不先切换数据库 |
| 运行调度、取消、进度 | Python threading + queue.Queue + threading.Event；单主动 worker | 后端输入读取与网络执行分离，取消不排在长调用后面；详见第 5 节 |
| 日志、指标与验收评测 | Python 现有 trace/metrics/evals，离线协议与人工复核 | 原报告和候选集沿用，不把桌面启动成功当作模型质量通过 |
| 自动化验证 | Python 既有断言/测试与 unittest.mock；TS 使用 Vitest；桌面烟测用 Playwright Electron 接口 | 主验收仍走用户 Event → 结果/确认/可靠保存；桌面只补通信和交互关键路径 |

联网搜索不是匿名免费内置能力。未配置搜索时可接受用户提供的资料 URL，但应说明这只完成资料取回，不能宣称完整搜索成功。API Key 不内置到仓库；首版从 Python 环境变量读取，桌面仅显示配置状态。设置界面暂不保存凭据。

## 2. 进程结构与依赖方向

```text
Electron 渲染进程：React 界面
    ↓ 固定 preload 接口
Electron 主进程：IPC 校验、BackendClient、窗口与子进程管理
    ↓ 版本化 NDJSON 消息
Python 进程：stdio 适配器 → LocalApplication
    ├─ Workflow：前置条件、可行动集合、确认点
    ├─ Agent：上下文、模型决策、工具执行与观察
    └─ 业务模块：学习/证据、用户会话、资料、运行记录
         ↓ 各领域 Router 与提交协调
       存储、模型、搜索、网页取回等适配器
```

这是本地模块化应用，通过进程分工隔离界面与核心，不拆微服务。桌面主进程不得重新实现复验排序、预算、画像、证据生效和确认规则。Python 业务模块不得 import Electron、Qt，或通过 print/input 完成交互。

| 模块 | 可以依赖 | 禁止直接依赖 |
|---|---|---|
| renderer | 生成的契约类型、preload 接口、展示组件 | Node fs/child_process、业务状态文件、模型 SDK |
| preload / desktop main | wire 契约、Electron、BackendClient | Python 内部对象结构、业务规则副本 |
| Python 交互适配器（CLI / stdio） | LocalApplication、wire DTO | 私下调用 handler、直接改证据/状态 |
| LocalApplication | Workflow、运行控制、业务模块、提交接口 | 桌面技术、具体供应商 SDK、具体 JSON 文件布局 |
| Workflow / 领域规则 | 领域对象、显式输入、时钟值 | 模型、文件 I/O、UI、网络 |
| Agent / 工具执行器 | Workflow 允许集、模型接口、工具注册表、上下文接口 | 原始状态文件、通用字段 patch、任意函数执行 |
| 上下文模块 | 各领域 Router 的获准投影 | 仓储全量快照、未经检查的缓存 |
| 业务模块 / Router | 本领域规则、类型化查询/提交接口 | 其他模块私有存储结构、供应商响应原始类型 |
| 存储/模型/资料适配器 | 对应接口、第三方库、标准库 | UI，以及反向调用应用协调/Agent |

实例组装集中在 Python composition root；通过构造参数传依赖，不在业务内部创建 SDK client 或读取全局配置。只有确实需要替换或测试隔离的位置定义 Protocol，不给每个函数和领域对象增加接口层。

## 3. 关键模块接口与所有权

| 接口 | 操作与返回 | 必须隐藏/保证的内容 |
|---|---|---|
| LocalApplication | handle(Event) → ApplicationResult；query(Query) → View；subscribe → Progress 流 | 事件幂等、确认版本、冲突和可靠保存状态；不泄漏存储/供应商异常 |
| ModelGateway | generate(ModelRequest, CallContext) → ModelResult | 文本或 tool-call 候选、usage、prompt 引用；SDK 类型不外泄；候选输出仍须业务校验 |
| SearchProvider / ResourceReader | search(Query) → SourceCandidate[]；read(SourceRef) → ResourceResult | 搜索摘要与已读正文分开，记录 URL/取回时间/错误；正文不作为系统指令 |
| ContextBuilder | build(Purpose, ObjectRefs, Budget) → ContextBundle 或明确缺口 | 所有数据经 Router，必需题目/提交/量规不得静默裁剪；返回 basis_versions |
| 领域 Router | read(Purpose, Refs, Fields) → AuthorizedView；写请求转本领域命令 | 校验主体、Way、用途、字段及版本；禁止通用任意字典写入 |
| CommitCoordinator / StateStore | 提交类型化业务变化；底层 read_snapshot / commit(expected_revision, candidate) | 一个事务合并关联变化，持久化后公布新快照；冲突不部分生效 |
| RunController | start/cancel/status → RunView；观察进度 | 同 Way 单主动运行、代际失效、超时和迟到结果检查 |
| ToolRegistry | lookup(name, task_group) → ToolDefinition | 固定注册、严格参数、前置检查；工具只生成候选或调用业务命令，不绕过确认 |

业务所有权沿用系统设计：Learning 管目标/矩阵/计划/任务；Evidence 管判定、有效证据及画像投影；UserSession 管偏好/对话/摘要；Resource 管资料；Runtime 管运行记录。Evaluation 管评测，IdentityPolicy 管访问策略，后两类不向模型暴露原始敏感数据。

只有应用提交协调负责跨领域一致性。例如“确认判定 → 记录确认、应用证据、更新画像与进度”在同一候选快照中提交；不能由几个 Router 各自 save。网络调用与摘要生成在提交锁外进行，应用前再核对相关版本。缓存只存投影并带版本，不成为第二份权威状态。

内部失败统一为 code、message、retryable、details 的结构，至少区分 configuration_required、validation_error、conflict、network_error、timeout、cancelled、persistence_error、backend_unavailable。对外 details 只含可展示信息，不包含凭据、堆栈或完整 prompt。工具失败、模型输出无效与用户能力不达标分别表达。

## 4. 跨语言通信契约

Python 定义专用 wire DTO，不将整个领域模型和存储 schema 导出给前端。构建时导出 JSON Schema 及共同的合格/不合格样例；通过 json-schema-to-typescript 生成 TS 类型，Ajv 2020 校验传输消息。Python 用 Pydantic 再次校验输入。生成产物可提交用于审查，CI 检查重新生成后无差异；禁止手工改生成类型。前端展示状态不回写为业务事实。

传输协议 v1 为一行一个 JSON 的 UTF-8 字节流；正文中的换行必须 JSON 转义。按换行解帧并使用增量 UTF-8 解码，不能假设一次 stdout chunk 就是一条消息。stdout 只写协议帧，诊断写 stderr；旧 print 必须先从后端调用链移除/重定向。

每帧包含 protocol_version、kind、connection_id、request_id、payload。后端启动先发 ready，包含支持的协议版本、后端版本、schema_hash 和当前保存 revision；主进程握手通过后才接受业务输入。协议或 schema_hash 不匹配明确阻止操作，不尝试猜测字段。

| kind / 操作 | 输入与响应 |
|---|---|
| request: handle | typed Event；response 返回 ApplicationResult。event_id 为业务幂等身份，request_id 只关联传输 |
| request: query | learning_view、pending_confirmations、run_status、event_status（按 event_id 查结果）、configuration_status；response 返回获准 View，不接收任意文件路径或表达式 |
| request: shutdown | 生命周期操作；停止接收新工作，取消当前运行并报告最后保存点，不作为模型工具 |
| response | 匹配 request_id；结果或结构化错误。运行被 accepted 后可继续通过 progress 更新 |
| progress | run_id、递增 seq、revision、阶段/观察/终态；不等于另一次业务提交 |

preload 暴露 submitEvent(event)、query(query)、onProgress(listener)（返回取消订阅函数）；业务取消使用 cancel_run 事件，不另建通用控制入口。主进程校验 IPC sender/frame、结构和允许操作，再调用 BackendClient；Python 注入 local-owner，忽略或拒绝客户端自报身份。

工程起点：每帧最多 2 MiB（解码前按字节检查），每连接最多 32 个未完成请求，ready 最多等待 15 秒，普通 handle/query 接收响应最多 10 秒。长任务尽快返回 accepted，120 秒模型调用不阻塞该响应。大资料由 Python 保存，前端通过对象引用读取限定视图；超限明确报错，不截断提交。以上为可配置运输限制，需要实测，不是产品输入长度或性能验收标准。

连接超时/断开不代表业务未保存。重连后先 query 事件结果及保存 revision，再决定是否以同 event_id 重送；不得生成新 event_id 自动重放提交/确认。换连接创建新 connection_id，丢弃旧连接消息；进度缺序或窗口重载后查询权威快照，不要求无限保留历史进度。

## 5. 生命周期、调度与数据位置

Electron 主进程使用 spawn 启动明确路径的 Python 解释器和参数数组，shell:false、windowsHide:true；不拼接 shell 命令，不 detached。源码运行使用配置路径或项目 .venv，不静默寻找任意系统 Python；缺失时显示环境准备步骤。Python 使用 -u，管道显式 UTF-8。父进程始终消费 stdout/stderr 并处理 stdin drain，避免管道阻塞。

一个桌面实例只管理一个 Python 后端；Electron 单实例检查负责窗口体验，Python 对数据目录持有进程锁才有写权限，独立 CLI 也受同一锁约束。已在使用的数据目录返回明确错误，不让桌面和 CLI 同时写入。

Python 输入线程持续读帧；一个业务提交锁串行处理快速事件与可靠提交；一个主动 worker 执行模型/网络与 Agent 步骤。取消用 Event 和代际使旧结果失效，不能等待网络完成后才接收。进度按步骤/批次合并，最多以 100ms 间隔向桌面刷新展示；终态与最后保存 revision 必须可查询，不逐 token 写状态文件。达到队列限制返回 busy；已经接受的用户输入不得静默丢弃。

沿用单调用含首次最多 5 次/总计 120 秒、局部运行 12 动作/600 秒/连续 2 次同输入无进展的既有设计。SDK 内建重试关闭，由一处策略控制。HTTPX 连接/读取超时不能代替总 deadline：运行控制到期即拒绝应用结果；同步请求仍占 worker 时显示正在释放，不无限新增线程接替。保留有效保存点，不承诺取消即停止供应商计算或计费。

正常退出发送 shutdown，Python 先保存有效结果并使在途调用失效；桌面工程等待上限默认 10 秒，超时终止自己管理的直接子进程，并将退出视为 interrupted。stdin EOF/父管道关闭触发同一停止逻辑；次启动恢复已保存状态，不自动重放副作用。强制关闭/断电不保证退出钩子执行，因此仍须关键事件保存和启动恢复；不把会话结束依赖于窗口回调成功。

桌面默认将数据目录设为 Electron userData 下的 backend，并以 COACH_DATA_DIR 传入 Python；源码 CLI 保留项目 data 默认值，也可指定同一目录。两种入口必须显示实际路径。旧 data 不自动覆盖或无提示搬迁，复用时显式选择同一路径，按迁移协议备份/校验。业务状态、备份和诊断分别存放；运行时资料及评测产物不进 Git。

JSON 提交过程为候选完整校验 → 同目录临时写入/flush/fsync → 原子替换 → 更新内存 revision；失败保留旧快照。不能把原子替换宣传为所有文件系统/断电场景下绝对不丢数据。辅助日志不与学习业务做分布式事务；状态检查点保存必要调用身份，诊断失败不得伪造业务成功或污染证据。

## 6. 目录与接口演进

下列为开发落点，不是现有目录清单。不要求一次搬空重写现有 coach 模块，按贯穿路径迁移，禁止保留两套生效规则。

```text
desktop/                 Electron 工程，独立 package.json 与 npm lock
  src/main/              窗口、BackendClient、子进程管理
  src/preload/           固定桥接方法
  src/renderer/          React 界面、展示状态、组件
  src/contracts/         生成类型/Schema，只含 wire 契约
coach/
  application/           统一应用入口、wire DTO、提交协调与实例组装
  desktop_stdio/         协议读写、握手、生命周期适配器
  cli/                   保留 CLI，逐步接入同一应用入口
  domain/                领域对象与确定性规则
  orchestration/         Workflow、Agent 运行与工具注册/执行
  services/              学习、证据、会话、资料、Router、上下文及生命周期
  llm/                   模型网关适配器
  storage/               JSON 仓储、迁移、锁
  prompts/               prompt 原文、目录与 manifest
```

更换模型只改 ModelGateway 适配器及配置；更换搜索只改 SearchProvider；换数据库只改 StateStore 及迁移，不改变业务确认；修改界面只改 renderer；未来 Web 接入实现新的应用传输适配器。在线身份、并发与部署届时单独设计，不把替换 stdio 为 HTTP 说成已完成在线产品。

## 7. 依赖、交付与验证

Python 保持现有 >=3.10 声明，首个桌面验证环境选 Python 3.12 + Windows；这是待验证基线，不声明全版本/全平台已支持。Node 开发工具链选实施时处于维护期的 LTS，并写入 engines；Electron 自带的 Node 与开发机 Node 分开管理。

Python 核心继续 openai、Pydantic，目标新增直接依赖 HTTPX、BeautifulSoup、filelock；旧 RAG 的 requests 等保留可选，不为本次设计安装依赖。桌面使用 React/react-dom、Ajv 及 shadcn/ui 对应组件依赖；样式采用 Tailwind CSS，经 PostCSS 接入 Webpack。遵循用户指定的 Base UI 路线，不混用另一套组件底座。组件源码放 renderer/components/ui，按需引入；具体依赖以实际选择的组件注册表为准，不把 shadcn 当成一次安装即可获得全部组件的黑盒。开发依赖 Electron、TypeScript、Forge/Webpack、样式构建、类型生成器及验证工具。TypeScript 开 strict；开发实际生成 package-lock.json，Python 生成验证环境的 constraints 锁定文件，并记录完整环境。具体版本在首次安装/烟测后锁定，不虚构已经验证的版本组合。

目标源码体验为先准备 Python 虚拟环境并安装核心，再进入 desktop 使用 npm ci / npm start；这些入口待实现后才可写入根 README 为可用命令。Python 由 Electron 启动，用户不用手动启动第二个服务。初版不承诺免 Python 安装的一键包；后续若做安装包，再将 Python 后端作为独立可执行产物随 Electron 分发，并验证各平台构建。

桌面只加载本地应用页面，开启 contextIsolation、sandbox，关闭 nodeIntegration；开发服务器仅用于开发配置。外部资料在系统浏览器打开；模型回复和资料不得作为可执行 HTML/脚本加载到有权限的窗口。首版可先展示纯文本和独立代码块，不为格式化放开任意 HTML。

开发顺序与检查：

1. 修复既有判定/确认/保存缺陷，提取 LocalApplication；CLI 通过同一接口回归。
2. 定义 wire DTO 与合格/不合格样例，验证 Python 与 TS 两端一致接受/拒绝，检查生成产物无漂移。
3. 打通 Electron → Python → 查询/确认/保存的一条最小路径，再添加目标、计划、学习等界面；不先复制整套业务到 TS。
4. 补通信验证：拆帧/合帧、中文跨 chunk、异常 stdout、超限、协议不匹配、断连后确认去重、取消后迟到结果、文件锁、退出与恢复。
5. Python 用假模型/搜索/时钟和临时存储验证业务；TS 用 Vitest 验证 BackendClient/preload 展示契约，Playwright 做桌面启动、提交、确认、取消和后端退出烟测。真实模型评测仍按原验收协议单独执行。
6. 通过干净 Windows 环境源码安装/启动后，记录可用版本和实际资源/延迟/成本；再按持续学习协议试用。不提前声称新技术栈降低资源或成本。

架构约束通过导入检查落实：TS renderer 禁止 Node/Electron imports，Python 领域规则禁止 UI/网络/存储 imports；可用现有 lint 或小型静态检查，不为检查本身引入依赖治理平台。每条检查都对应上述实际依赖规则。

## 8. 官方依据

- [Electron IPC](https://www.electronjs.org/docs/latest/tutorial/ipc)、[contextIsolation 与有限桥接](https://www.electronjs.org/docs/latest/tutorial/context-isolation)：桌面通信与隔离机制。
- [Node.js child_process](https://nodejs.org/api/child_process.html)：子进程与 stdio 机制；本项目选择 spawn 而非 shell 拼接。
- [Forge TypeScript/Webpack 模板](https://www.electronforge.io/templates/typescript-+-webpack-template.md)、[React 接入](https://www.electronforge.io/guides/framework-integration/react-with-typescript.md)：构建起点，不代表该页面示例版本已在本项目验证。
- [OpenAI Python SDK](https://github.com/openai/openai-python)、[HTTPX 超时](https://www.python-httpx.org/advanced/timeouts/)：适配器配置与超时语义。
- [Brave Search API 认证](https://api-dashboard.search.brave.com/documentation/guides/authentication)：用户自行提供搜索凭据，本文不承诺免费额度或价格。

- [shadcn/ui Radio Group（Base UI）](https://ui.shadcn.com/docs/components/base/radio-group)、[手动安装与 Tailwind 配置](https://ui.shadcn.com/docs/installation/manual)：项目负责人指定的前端组件来源。首版设计及限制见 [前端原型说明](frontend-prototype.md)。

技术选择是开发决定；具体实现、跨平台可用性和性能结论必须由代码与验证报告提供证据。
