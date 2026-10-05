# AI Native Learning Tool

> 一个以 AI 为核心的学习教练：让 AI 成为学习流程的**核心执行者**，帮助学习者真正掌握技能，而不是「听过就忘」。

## 这是什么

- **不是聊天机器人**：围绕「目标澄清 → 能力测评 → 学习计划 → 今日任务 → 结果验收 → 画像更新 → 动态调整」的闭环运转，并带**复习系统**（间隔重复，对抗遗忘）。
- **以验收为准**：学习者说「我会了」不算掌握，通过任务验收才算。
- **当前进度**：V0.01（DeepSeek 基础聊天）✅ / V0.1（持久化对话状态）✅ —— 已从「能聊天」升级为「能记住用户状态」。

## 快速开始

环境要求：Python 3.14+，Windows（PowerShell）。

```powershell
cd App_landing

# 创建或使用已有虚拟环境
python -m venv .venv          # 已存在 .venv 可跳过
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

# 设置 DeepSeek API Key（只从环境变量读取，绝不写入代码）
$env:DEEPSEEK_API_KEY = "sk-..."

python app.py
```

## 使用

- 启动后直接与教练对话，输入 `exit` 退出。
- 用户状态（含对话历史）保存在 `data/user_state.json`，**重启程序后可继续之前的对话**。
- 该文件包含真实学习数据，已被 `.gitignore` 排除，不会提交到仓库。

## 项目结构

```
App_landing/
├── app.py              # 薄入口：from coach.cli.main import main
├── pyproject.toml      # 项目元数据与依赖（可选 pip install -e .）
├── coach/              # 主包（分层，依赖方向自上而下，见下节）
│   ├── config.py           # Settings：模型/温度/base_url/Key（导入不抛错）
│   ├── llm/                # client.py —— 唯一 LLM 入口（json_call / chat）
│   ├── domain/             # 纯逻辑：models / stages / *_rules / cursor / state_schema
│   ├── prompts/            # 提示词集中：stages / tasks
│   ├── services/           # 用例：profile / assessment / planning / daily_task / evaluation / coach
│   ├── storage/            # state_store.py（读写）/ reset.py（清理与备份）
│   ├── orchestration/      # turn.py —— 单轮流程 run_turn()
│   └── cli/                # main.py —— 终端界面
├── rag/                # RAG / 知识库（本期不在 MVP 范围；详见下方章节）
│   ├── crawl.py        # 爬虫：抓 runoob Python3 教程 → data/rag/raw/*.json
│   ├── chunk.py        # 切块：raw → data/rag/chunks.jsonl（按 token，≤350）
│   ├── embeddings.py   # 本地 BGE-M3 向量化引擎（onnxruntime，无 torch）
│   ├── embed_store.py  # 向量化并写入 Qdrant 本地库
│   ├── retrieve.py     # 检索：query → top-k（含 recall@k 自检）
│   └── build.py        # 一键管道：crawl → chunk → store
├── data/               # 用户状态 + RAG 产物（均不提交）
│   ├── user_state.json
│   └── rag/            # raw/ chunks.jsonl qdrant/ models/
├── evals/              # 评测集（dev/holdout）+ M-01 判分一致率 runner（详见下方章节）
├── tests/              # 确定性回归测试（73 个用例）
└── .gitignore
```

### 代码分层（依赖方向自上而下，下层不依赖上层）

| 层 | 目录 | 职责 | 约束 |
|---|---|---|---|
| 接口层 | `coach/cli/` | 终端交互与渲染 | 只读 `TurnResult`，不含业务逻辑 |
| 编排层 | `coach/orchestration/` | 单轮流程 `run_turn()` | 决定"先做什么后做什么"，不直接调 LLM |
| 应用层 | `coach/services/` | 用例（抽取/测评/计划/任务/验收/对话） | 可调 LLM，**不做状态机推进、不落盘** |
| 持久化 | `coach/storage/` | 状态读写与清理备份 | 只碰 `data/` |
| 提示词 | `coach/prompts/` | 纯文本提示词 | 无逻辑 |
| 模型访问 | `coach/llm/` | 唯一 LLM 出口 | **模型名只在此配置**（`coach/config.py`） |
| 领域层 | `coach/domain/` | 纯逻辑（守卫、游标、聚合、清洗） | **无 IO、无 LLM、可单测** |

两条历史包袱已消除：① 模型名原本硬编码在 6 个文件里，现只在 `coach/config.py` 定义一处；② `_json_call()` 原本在 5 个模块里各有一份，现只有 `coach/llm/client.py` 一份。

> 分层的原因与取舍见 `docs/PRD.md` 的 **S-03（统一模型配置）** 与 §2.1 架构定性。

#### 旧模块 → 新位置对照（V0.8 重构）

下方 **V0.2–V0.3e 章节按当时的文件名**记录（那是历史事实，未改写）；若要照它找代码，请用本表换算：

| 旧模块（已删除） | 新位置 |
|---|---|
| `agent.py` | `coach/services/coach.py`（消息组装）+ `coach/llm/client.py`（模型调用） |
| `config.py` | `coach/config.py`（`Settings`；**导入不再抛错**） |
| `profile_extractor.py` | `coach/services/profile.py`（抽取）+ `coach/domain/models.py`（`UserProfile`） |
| `assessor.py` | `coach/domain/assessment_rules.py`（判定映射/聚合/薄弱点）+ `coach/services/assessment.py`（出题/判分） |
| `planner.py` | `coach/domain/plan_rules.py`（期限/窗口/清洗/兜底）+ `coach/services/planning.py`（生成/确认） |
| `daily.py` | `coach/domain/cursor.py`（游标/任务查找）+ `coach/services/daily_task.py`（展示/提交识别） |
| `evaluator.py` | `coach/domain/evaluation_rules.py`（完成度/动作一致性）+ `coach/services/evaluation.py`（判定/画像更新） |
| `state.py` | `coach/domain/state_schema.py`（schema + `ensure_keys`）/ `coach/domain/profile_rules.py`（画像合并）/ `coach/storage/state_store.py`（读写） |
| `stages.py` | `coach/domain/stages.py`（阶段常量/守卫/转换）+ `coach/prompts/stages.py`（阶段提示词） |
| `reset.py` | `coach/storage/reset.py`（命令改为 `python -m coach.storage.reset`） |
| `app.py`（252 行脚本） | `app.py`（薄入口）+ `coach/orchestration/turn.py`（单轮流程）+ `coach/cli/main.py`（界面渲染） |

**不受影响**：`data/user_state.json` 的路径与 schema 未变（`ensure_keys` 仍能平滑升级旧文件），`rag/` 未改动，`tests/` 用例内容未变（仅导入路径更新）。

## 路线图

| 版本 | 内容 | 状态 |
|---|---|---|
| V0.01 | DeepSeek 基础聊天（API/SDK/CLI） | ✅ 已完成 |
| V0.1 | 持久化 Agent State（重启可续） | ✅ 已完成 |
| V0.2 | 结构化用户画像（LLM 抽取 → 状态） | ✅ 已完成（抽取 + 合并 + 阶段推进 + 状态回灌） |
| V0.3 | Agent 状态机（含能力测评） | ✅ 已完成（V0.3a 骨架 / b 测评 / c 计划 / d 每日任务 / e 验收与画像更新） |
| V0.4 | Human-in-the-loop | 待开始 |
| V0.5 | Evaluation（学习效果评估） | 🔸 评测集（30 条 dev + 8 条 holdout）与 M-01 判分一致率 runner 已建立（`evals/`）；事件级指标采集与导出待做 |
| V0.6 | Tools（代码执行/检索/进度） | 🔸 Retrieval Tool 已实现（rag/tool.py） |
| V0.7 | RAG / 知识库 | ✅ 本地向量库 + Agent 接入完成（recall@5=100%，回答带来源引用；**本期不在 MVP 范围**） |
| V0.8 | **代码结构重构（分层包 `coach/`）** | ✅ 平铺模块 → 分层包（cli / orchestration / services / storage / prompts / llm / domain）；统一模型配置与 LLM 入口；73 个测试全绿 |
| V1.0 | Web MVP | 后续 |

## RAG / 知识库（rag/）

抓取 [runoob Python3 教程](https://www.runoob.com/python3/python3-tutorial.html) 全 84 章，构建本地向量库：

```powershell
# 全流程（已抓过的章节自动跳过；已有向量库时 store 阶段会跳过）
.\.venv\Scripts\python.exe -m rag.build

# 强制重建向量库（改完切块/embedding 后使用）
.\.venv\Scripts\python.exe -m rag.build --rebuild

# 单独跑某阶段
.\.venv\Scripts\python.exe -m rag.crawl --limit 3   # 试抓前 3 章
.\.venv\Scripts\python.exe -m rag.chunk             # 重切块
.\.venv\Scripts\python.exe -m rag.embed_store --force   # 重新入库

# 检索
.\.venv\Scripts\python.exe -m rag.retrieve "字典的 get 方法"
.\.venv\Scripts\python.exe -m rag.retrieve --selfcheck   # recall@k 自检
```

技术要点：
- **切块**：按 bge tokenizer 计数，单块目标 300 token、重叠 50、硬上限 350（远低于模型上限）。
- **Embedding**：`BAAI/bge-m3` 官方 ONNX 直跑（onnxruntime CPU，无需 torch/PyTorch）；首次运行下载约 2GB 模型到 `data/rag/models/`。
- **向量库**：Qdrant 本地嵌入式模式（1024 维、cosine），数据在 `data/rag/qdrant/`，无需 Docker。
- 所有产物在 `data/` 下，已被 `.gitignore` 排除，不提交仓库。

### Agent 接入（RAG 闭环）

> **当前状态：默认关闭**（暂时不调用 RAG）。向量库与 `rag.retrieve` 仍可独立使用。
> 需要时在对话里输入 `/rag on` 临时开启。

开启后，教练会**自动判断**用户消息是否需要查知识库：出现具体概念（列表/字典/函数…）
或问句特征时才检索，目标澄清类消息（如"我想学 Python"）不会触发。

```powershell
.\.venv\Scripts\python.exe app.py
# ... 你：/rag on
# 知识库检索： 已开启
# 你：字典的 get 方法默认返回什么
# Coach：根据参考资料 [1]：dict.get(key, default=None) ...（回答末尾标注来源）
# [参考资料] [1] Python3 字典 / 字典内置函数&方法；[2] ...
#
# 输入 /rag off 可随时关闭检索（用于对照"无 RAG"的回答）
```

实现要点：
- `rag/tool.py`：`should_retrieve()` 门控 + `build_context()` 构造带 `[1][2]` 编号的参考资料。
- `agent.py`：检索结果作为**独立的第二条 system 消息**注入（不写入对话历史，避免历史膨胀）；
  要求模型优先依据资料回答、标注编号、资料不足时明说。
- `chat_with_coach()` 返回 `(回答, 来源列表)`，`app.py` 据此打印来源章节。

## V0.2 结构化用户画像

从"能聊天"升级为"能把用户自然语言变成结构化状态"——这是 Chatbot 到 Agent 的分水岭。

```text
用户："我想一个月学 Python 数据分析，以前学过一点基础，每天能学 30 分钟"
      ↓ extract_profile()  第二次 LLM 调用（JSON 模式 + Pydantic 校验）
{"learning_goal":"Python 数据分析","current_level":"只学过一点基础",
 "daily_minutes":30,"target_date":"一个月"}
      ↓ merge_profile()    只合并非空字段（没提到的不覆盖已收集的信息）
      ↓ maybe_advance_stage()
四项齐全 → current_stage: goal_clarification → assessment
```

设计要点：
- **增量抽取**：只解析最新一条用户消息，累积交给 `merge_profile`（避免历史重算与旧值覆盖新值）。
- **空值不覆盖**：`None` 不写入 state —— "这轮没提到"≠"信息不存在"。
- **阶段守卫**：`learning_goal / current_level / daily_minutes / target_date` 四项全齐才推进到 `assessment`。
- **状态回灌**：把"已收集信息 + 仍缺失字段"注入对话，教练不再重复提问，只追问缺的那项。
- **失败兜底**：抽取失败返回空画像并告警，绝不中断对话。

新增/改动：`profile_extractor.py`（新增）、`state.py`（`merge_profile` / `profile_complete`）、
`agent.py`（已知信息注入）、`app.py`（每轮抽取并打印画像进度）。阶段推进已迁至 `stages.py`。

## V0.3 Agent 状态机

主干阶段（`stages.py` 是转换规则与守卫的唯一来源）：

```text
goal_clarification → assessment → planning → learning → evaluation → profile_update
                                                                          ↓
                                                          learning / review / completed
```

**每个阶段一套系统提示词**——阶段决定"教练此刻该做什么"，这是状态驱动行为的核心：

| 阶段 | 教练行为准则 |
|---|---|
| 目标澄清 | 一次只问 1~2 个最关键的问题，不提前给计划 |
| 能力测评 | 3~5 个由易到难的实际任务，**一次只出一道**，不用"你会不会"来判断 |
| 学习计划 | 只规划**未来 7 天**（滚动窗口；不足 7 天按实际期限） |
| 每日任务 | 每次只给一个 `today_task`（目标/材料/练习/预计时间/完成标准） |
| 结果验收 | 要求提交证据，判定完成度与错误类型，给出 重试/补充/通过 |
| 画像更新 | 更新掌握度与薄弱点；重大变更先征求用户确认 |

**转换守卫**（条件不满足绝不推进，每次只走一步）：

| 转换 | 守卫条件 |
|---|---|
| 目标澄清 → 能力测评 | 四项信息齐全（目标/水平/每日时间/期限） |
| 能力测评 → 学习计划 | 已产出 `skill_profile` |
| 学习计划 → 每日任务 | 已产出 `current_plan` **且用户已确认**（`plan_confirmed`） |
| 每日任务 → 结果验收 | 有 `today_task` 且用户已提交结果 |
| 结果验收 → 画像更新 | 已产出验收结论（`latest_result`） |
| 画像更新 → 每日任务（**回路**） | 验收结论已应用（通过则推进到下一个任务，未通过则重做当前任务） |

其它要点：
- 旧状态文件由 `state.ensure_keys()` **自动补齐** V0.3 新字段（`assessment_progress` / `pending_submission` / `latest_result` / `latest_result_applied` / `plan_confirmed` / `plan_progress`），不覆盖已有数据。
- 主干已闭环；后续版本：V0.4 Human-in-the-loop、V0.5 Evaluation、复习系统、7 天窗口滚动重排（当前窗口排完后暂只提示"已完成"）。

新增/改动：`stages.py`（新增）、`state.py`（新字段 + `ensure_keys`，阶段推进迁出）、
`agent.py`（按阶段选提示词）、`app.py`（走 `try_advance` 并打印阶段变化）。

### V0.3b 能力测评（`assessor.py`）

```text
进入 assessment
  ① ensure_plan()      生成 3~5 道由易到难的大纲（主题 + 难度）→ state["assessment_progress"]
  ② record_answer()    每轮把「上一轮的题 + 本轮用户回答」交给 LLM 判三档
  ③ finalize()         答满题量 → 代码聚合出 skill_profile，并按阈值产出 weak_points
  ④ 守卫自动放行        skill_profile 非空 → planning
```

关键设计：
- **三档判定**：`mastered=1.0 / partial=0.5 / missing=0.0`（中文别名如"掌握/部分正确/不会"自动归一）。
- **聚合与阈值在代码里，不在 LLM 手里**：同一知识点多题取平均；`weak_points = 分数 < 0.6`（阈值/题量都是模块常量，可调）。
- **汇总不额外调 LLM**：判定只有三档，聚合是确定性计算 —— 比"再让模型汇总一次"更省、更稳、可测试。
- **只问当前这道题**：测评进度会注入对话（`assessor.describe_progress()`），避免跳题或一次抛出多题。
- **兜底**：出题失败用目标生成 3 道通用递进题；判卷调用失败按 `missing` 记录，不中断测评。

新增/改动：`assessor.py`（新增）、`agent.py`（注入测评进度）、`app.py`（测评阶段记账与收尾）。

### V0.3c 学习计划（`planner.py`）

```text
进入 planning
  ① plan_horizon()     窗口 = min(7, 期限天数)；期限不足 7 天按实际，解析不出则默认 7
  ② generate_plan()    围绕 目标/水平/每日时间/能力画像/薄弱点 生成 N 天计划（LLM + JSON）
  ③ ensure_plan()      写入 current_plan = {horizon_days, start_date, days, version}
  ④ 教练照实呈现计划（计划摘要会注入对话，不让模型另编一份）
  ⑤ confirm_plan()     **B2：LLM 判断用户是否确认**；确认后 → 守卫放行 → learning
```

关键设计：
- **7 天是"步长"而非"总时长"**：目标是 3 个月，也每次只排最近 7 天，滚动推进。
- **计划结构固定**：每天 `theme` + 1~3 个任务，每个任务含 `goal / material / exercise / minutes / done_criteria`（可执行、可验收）。
- **清洗与兜底在代码里**：天数对齐窗口（截断 + 占位补齐）、重编号、任务数上限 3、空任务丢弃；模型不可用时用**围绕薄弱点的确定性兜底计划**。
- **先确认、后教学**：`plan_confirmed` 未置位时守卫拦在 planning；确认判定由 LLM 完成（含糊、反问、要求修改一律不算确认），判定失败保持等待、绝不误进。

新增/改动：`planner.py`（新增）、`state.py`（+`plan_confirmed`）、`stages.py`（守卫加确认条件）、
`agent.py`（注入计划摘要）、`app.py`（计划阶段接线）。

### V0.3d 每日任务（`daily.py`）

```text
进入 learning
  ① 计划游标 (day, task) → 取出**一个**任务
  ② build_today_task()   写入 today_task：目标/材料/练习/预计时间/完成标准
  ③ 教练照实呈现这一个任务（任务注入对话，不让它另编或提前布置后续任务）
  ④ detect_submission()  判断用户是否提交了可验收结果（LLM）
  ⑤ 命中提交 → 写 pending_submission → 守卫放行 → evaluation
  ⑥ mark_task_done()     验收通过后推进游标（由 V0.3e 调用）
```

游标模型（"每次只给一个任务"）：`plan_progress = {day, task, completed, finished}`
- 当天还有任务 → `task + 1`；当天完成 → 下一天 `task = 1`；全部完成 → `finished = true`
- 全空的天会被跳过；计划排完后不会重复发最后一个任务

关键设计：
- **只讲当前这一个任务**：任务与进度都会注入对话，教练不能跳到后面。
- **提交识别用 LLM**（与 V0.3c 的确认判定同套路）：提问／闲聊／"快好了"都不算提交；判定失败保持 learning，绝不误推进。
- **提交内容原样留存**（代码可原样摘录）到 `pending_submission`，供 V0.3e 验收。

新增/改动：`daily.py`（新增）、`state.py`（+`plan_progress`）、`agent.py`（注入任务与待验收内容）、`app.py`（learning 阶段接线）。

### V0.3e 结果验收与画像更新（`evaluator.py`）

```text
用户提交 (pending_submission)
  ① evaluate()      结构化判定：完成度 / 掌握度 / 错误类型 / 下一步
  ② 完成度三档      completed=1.0 / partial=0.5 / not_completed=0.0（代码映射，不让模型给分）
  ③ 一致性守卫      pass 只在 completed 时允许；partial → supplement；not_completed → retry
  ④ 教练按判定沟通（结论注入对话，不让它另编）
  ⑤ apply_update()  代码侧更新画像并决定下一步：
       pass  → mark_task_done() 推进游标（下一个任务）
       其它  → 保留当前任务、清空提交（让用户重做）
  ⑥ 阶段回路        结果验收 → 画像更新 → 每日任务
```

关键设计：
- **掌握度由完成度推导**（1.0 / 0.5 / 0.0），与 V0.3b 测评口径一致。
- **动作一致性在代码里强制**：模型给出"没做完却通过"时会被纠正为 supplement / retry。
- **画像平滑更新**：已有知识点取新旧平均（避免被单次表现拉偏），薄弱点复用 `< 0.6` 阈值规则。
- **错误类型结构化留存**（如"概念混淆""语法错误"），供后续复习系统使用。
- **判定失败保持 evaluation**（无 Key / 网络异常），绝不写入假判定。

新增/改动：`evaluator.py`（新增）、`state.py`（+`latest_result_applied`）、`stages.py`（+`profile_update → learning` 回路）、
`agent.py`（注入判定结论）、`app.py`（验收阶段接线）。

## 测试用：状态清理

测试阶段经常需要"测前准备 / 测后清理"。工具只操作 `data/user_state.json`（与 `data/backups/`），
**绝不触碰** `.venv`、向量库、embedding 模型。

会内命令（`app.py` 运行中直接输入）：

```
/reset        清空对话历史（画像 / 计划 / 阶段 / 进度都保留）
/reset all    完全重置（回到目标澄清；会先自动备份）
```

命令行工具（`coach.storage.reset`，退出程序后使用）：

```powershell
.\.venv\Scripts\python.exe -m coach.storage.reset                    # 完全重置
.\.venv\Scripts\python.exe -m coach.storage.reset --history          # 只清对话历史
.\.venv\Scripts\python.exe -m coach.storage.reset --stage assessment # 重置并跳到指定阶段（分段测试）
.\.venv\Scripts\python.exe -m coach.storage.reset --no-backup        # 清理前不备份
```

- 每次清理前自动备份到 `data/backups/user_state_<时间戳>.json`，**只保留最近 5 份**
- 备份目录与测试临时目录都已加入 `.gitignore`
- `exit` 只是退出，**不会清理**（学习数据保留）

## 验收测试

- **V0.1**：聊几轮 → `exit` → 重启程序 → 对话历史仍在（`data/user_state.json` 持久化）。
- **V0.2**：自动抽取与状态推进
  ```powershell
  .\.venv\Scripts\python.exe tests\test_profile.py
  ```
  覆盖 schema 清洗、合并规则（空值不覆盖）、阶段守卫（缺一不推进 / 齐全必推进且幂等），
  以及真实抽取用例（输入"我想一个月学习 Python 数据分析…每天能学 30 分钟"→ 抽到 4 字段并进入 `assessment`；未设置 `DEEPSEEK_API_KEY` 时自动跳过）。
- **V0.3a**：状态机骨架
  ```powershell
  .\.venv\Scripts\python.exe tests\test_stages.py
  ```
  覆盖线性阶段链、每阶段标签与提示词（含"7 天""一次只出一道"等关键规则）、守卫拦截与放行、
  单步推进、出口阶段无自动转换、旧状态文件升级与可变默认值隔离。
- **V0.3b**：能力测评
  ```powershell
  .\.venv\Scripts\python.exe tests\test_assessment.py
  ```
  覆盖判定映射与别名归一、大纲清洗（重编号/截断 5 题/空题丢弃/难度收敛/空大纲兜底）、
  知识点聚合与薄弱点阈值边界（0.6 不算薄弱）、进度与结束判定，
  以及**闭环用例**（finalize 后守卫必须能进入 `planning`）；真实出题与判卷用例需 `DEEPSEEK_API_KEY`。
- **V0.3c**：学习计划
  ```powershell
  .\.venv\Scripts\python.exe tests\test_plan.py
  ```
  覆盖期限解析（阿拉伯/中文数字、各时间单位、模糊表达返回 None）、窗口天数（min(7,期限)、
  不足 7 天按实际、默认 7）、计划清洗（对齐窗口/重编号/任务数上限/空任务丢弃/兜底计划）、
  **确认门控**（有计划未确认必须拦住、确认后放行，无 Key 时判定失败也不误置确认），
  以及真实用例（生成 7 天计划 + B2 确认判定：同意 / 要求修改各一次）。
- **V0.3d**：每日任务
  ```powershell
  .\.venv\Scripts\python.exe tests\test_daily.py
  ```
  覆盖计划游标（默认值/字段补齐/异常兜底）、任务查找与越界、顺序推进（task→task、day→day、
  排完返回 None、跳过空白天）、任务构建与游标推进（`mark_task_done` 清空 today_task 与提交）、
  **守卫**（有任务无提交被拦 / 有提交放行）、无 Key 时提交判定不误报；
  真实用例：提问判 false、给出代码判 true 并写入 `pending_submission`。
- **V0.3e**：结果验收与画像更新
  ```powershell
  .\.venv\Scripts\python.exe tests\test_evaluation.py
  ```
  覆盖完成度→掌握度映射、中文/英文别名归一、掌握度由完成度推导（模型给分不作数）、
  **动作一致性守卫**（pass 仅限 completed）、错误类型归一、`apply_update` 的 pass 分支
  （推进游标 + 画像平均 + 薄弱点重算）与 retry 分支（保留任务 + 清空提交）、
  **守卫链**（无判定不得进 profile_update、未应用不得回 learning）、无 Key 时不误判；
  真实用例：提交正确代码判 completed/pass、乱答判 not_completed/retry。
- **状态清理工具**
  ```powershell
  .\.venv\Scripts\python.exe tests\test_reset.py
  ```
  覆盖 `clear_history` 计数、`reset_all`（写回默认 + 自动备份 + 备份内容正确）、
  `reset_history`（清历史但保留画像/计划/阶段/进度）、`reset_to_stage`（非法阶段抛错且不写文件）、
  state 文件缺失时安全重建、备份只保留最近 N 份、`--no-backup` 不产生备份。
  （临时文件建在 `tests/.tmp/`，不写系统临时目录，也不碰真实状态文件。）

## 评测（evals/）

`tests/` 覆盖**确定性逻辑**（状态机守卫、计划清洗、分数聚合、阈值…）；`evals/` 覆盖**无法用断言固定的模型判定**，用于度量 **M-01 判分一致率**。两者互补，不重复。

只评 5 个 LLM 判定点：`assessment_verdict` / `evaluation_completion` / `submission_detect` / `plan_confirm` / `profile_extract`。

```powershell
# dry-run（默认）：只校验数据集格式与分布，不调模型、不花钱
.\.venv\Scripts\python.exe evals\run_eval.py
.\.venv\Scripts\python.exe evals\run_eval.py --dataset holdout

# 真实评测（需要 DEEPSEEK_API_KEY）
.\.venv\Scripts\python.exe evals\run_eval.py --live
.\.venv\Scripts\python.exe evals\run_eval.py --live --repeat 3 --format csv --out evals\results\m01.csv
```

三条纪律：

- **dev 与 holdout 分离**：调提示词只看 `dev.jsonl`；`holdout.jsonl` 只用于发布判断，跑 `--live` 需显式加 `--allow-holdout`（防泄漏）。
- **分层阅读**：报告给出按 judge / domain / risk 的分层一致率——总体均值不得掩盖分层失败。
- **error 单列**：模型调用失败计入 `error`、不计入一致率分母，并醒目告警，避免把"接口挂了"误读成"判得准"。

阈值 **M-01 ≥90% 仍为「待定」**（先测基线再定）。详见 `evals/README.md` 与 `evals/schema.md`。

## 许可证

[MIT](./LICENSE)
