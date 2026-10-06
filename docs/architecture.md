# Agent 架构决策记录（v1）

> **状态**：已定稿（2026-09-22），作为 `coach/` 的架构依据。
> **范围**：只定"agent 的基本架构采用什么框架"，不含具体功能排期（见 [PRD](PRD.md) §2.10）。
> **读者**：未来的自己、评审者、以及任何要往这个 agent 里加能力的人。

---

## 1. 决策摘要

| # | 决策轴 | 结论 | 一句话理由 |
|---|---|---|---|
| 1 | **编排范式** | **自研状态机 + 矩阵驱动 + 可替换 Selector**，不引入图编排框架 | 需要"代码守卫为唯一推进来源"与"能看见完整 messages"；框架抽象会隐藏 prompt，而实测缺陷（X-16）正出在消息组装层。**把"选步骤"抽成策略后，升级 hybrid 只是换一个类**（见 §5） |
| 2 | **能力扩展机制** | **能力注册表 + 阶段×能力矩阵** | 现在加任何能力都要改 `orchestration/turn.py`；注册表把隐式依赖变成显式契约，且不改守卫语义 |
| 3 | **自主权模型** | **三级授权（read / write / danger）+ 统一声明清单** | S-08 已有"门"，缺的是"每个动作属于哪一级"的单一来源；未声明默认 `danger`（fail-closed） |
| 4 | **感知契约** | **先写契约文档，落地时再改代码** | 统一 4 个判定点会动到已测代码，当前收益不足；先定形状与不变量，新增判定点时再统一 |
| **5** | **执行模型** | **Step / Selector / Policy 三件分离**：Planner 只**提议**，Executive **唯一执行**，Policy 定**权限** | 提议错了不会直接造成副作用；"该容易改的（策略）容易改，该难改的（不变量）挡得住"（见 §5） |
| **6** | **计划模型（v2 新增）** | **双层**：长期**路线图**（不滚动）+ 短期**执行窗口**（滚动）；**单位 = 次（session）**，由时间预算决定 | 碎片化下"天"不是正确单位（一天可能 3 次、也可能 3 天 1 次）；一套模型同时覆盖碎片化与整块时间（见 §11） |
| **7** | **记忆分层（v2 新增）** | 长期 / 计划 / 短期窗口 / 工具 / **提议** 五层，**每层声明写入者** | 全量 history 注入是已实测的成本问题；分层是"按需触发"落地的前提（见 §12） |
| **8** | **趣味化（v2 新增）** | 只作为 **`kind="engagement"` 的反馈层能力**，不进入判定链 | 趣味化能提升留存，但**绝不能污染验收信号**（红线 I-9，见 §13） |

**被明确否决的选项**：

| 否决 | 理由 |
|---|---|
| LangGraph 作为主编排 | 检查点/HITL 中断在本机 CLI 单用户场景收益有限（状态本就是 JSON，确认门已实现）；代价是重写守卫与用例 |
| 纯动态 agent（模型决定步骤） | 与"以验收为准""不可逆动作需确认"直接冲突 |
| CrewAI / AutoGen | 多智能体**角色交接**，与"单教练多阶段"不是同一个问题 |
| DSPy / 事件总线 / 微服务 | 分别是另一个问题、或对本机单进程属过度设计 |
| 保留"每个测试文件自带 runner" | 已由 `tests/_runner.py` 统一（见 §8） |

> **一个诚实的备注**：项目有"双读者"（用户 + 评审者）。"用过 LangGraph" 确实是作品集信号，但**不建议在主链路换框架**。若确实需要该信号，做法是**新增一个可替换的编排后端做对照实验**，主链路不动。

---

## 2. 十条不变量（任何改动不得违反）

> **I-2 / I-3 来自真实运行实测出的缺陷**（见 PRD §13 X-16 / X-17），不是理论推演。
> I-6…I-10 由"碎片化定位 + 提议机制"两项决策推导而来（v2 新增）。

| # | 不变量 | 违反后会怎样 |
|---|---|---|
| **I-1** | **阶段推进只能由 `coach/domain/stages.py` 的守卫决定**；模型永远不能推进阶段 | 学习路径被模型自由裁量，"以验收为准"失效 |
| **I-2** | 教练对话使用的阶段 = **本轮起始阶段**（`TurnResult.stage_before`） | 模型抢在代码判定前宣布验收结论 → 用户先后收到矛盾结论（**X-16 实际发生过**） |
| **I-3** | 注入的**「当前权威状态」优先于对话历史中的任何自述**，且注入位置必须在历史**之后** | 模型沿用历史里自己编的任务，状态说 A、用户看到 B（**X-17 实际发生过**） |
| **I-4** | 任何**不可逆动作**必须过 `coach/domain/confirmations.py` 的确认门；**未登记的动作直接抛错** | 不可逆动作被单方面执行且无法审计 |
| **I-5** | 每个能力必须**声明副作用级别**；**未声明默认 `danger`** | 新增能力绕过确认门（fail-open） |
| **I-6** | **模型的提议不得越出当前阶段的允许动作集**；越界一律拒绝并回退默认步骤 | 模型用"越界的合法步骤"绕过矩阵，流程失去确定性 |
| **I-7** | **用户提供的原始计划只读保留、禁止静默丢弃**；系统只产出"优化后计划 + **差异说明**"，且必须经用户确认 | 用户的意图被悄悄替换，信任一次性崩坏 |
| **I-8** | **记忆按层声明写入者**；跨层写入视为缺陷 | 任意能力乱写记忆，状态被污染且无法归因 |
| **I-9** | **趣味化机制不得影响验收结论与画像**（不得为"鼓励"放宽判定、不得篡改掌握度） | 学习信号被"游戏化"腐蚀，产品差异化（验收）失效 |
| **I-10** | **验收档位由代码决定（单次时长 + 累积证据）**；模型**不得自行降档或改档** | 模型为"让用户感觉好"而放水；"验收是质量锚点"变成空话 |

---

## 3. 架构分层与职责

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 接口层    coach/cli/                    只渲染 TurnResult，无业务逻辑      │
├──────────────────────────────────────────────────────────────────────────┤
│ 编排层    coach/orchestration/                                             │
│             ├ executor（待建）          唯一执行者：校验→执行→观察→回退   │
│             └ turn.py                   装配上下文 + 驱动 executor         │
│              └ 状态机 coach/domain/stages.py    ← 唯一推进来源（I-1）      │
├──────────────────────────────────────────────────────────────────────────┤
│ 策略层    Selector（矩阵 / 未来 hybrid）+ Policy（三级授权，见 §6）        │
│              └ 危险动作登记 coach/domain/confirmations.py（已有）          │
├──────────────────────────────────────────────────────────────────────────┤
│ 认知层    Planner（LLM，待建）          内容规划 + 子任务分解 + 步骤提议   │
│                                         **只提议，无执行权**（见 §5）      │
├──────────────────────────────────────────────────────────────────────────┤
│ 能力层    coach/services/ + 能力注册表                                     │
│             perception / planning / evaluation / tool / **engagement**     │
├──────────────────────────────────────────────────────────────────────────┤
│ 记忆层    长期 · 计划 · 短期窗口 · 工具 · 提议（**每层声明写入者**，I-8）  │
│                                         （见 §12）                        │
├──────────────────────────────────────────────────────────────────────────┤
│ 状态层    coach/storage/ + coach/domain/state_schema.py  schema 版本与迁移 │
├──────────────────────────────────────────────────────────────────────────┤
│ 基础层    coach/llm/ · coach/prompts/ · coach/metrics/                     │
└──────────────────────────────────────────────────────────────────────────┘
```

**依赖方向自上而下，下层不依赖上层。** 目前只有 **`executor` 与 `Planner` 待建**；
`policy`（授权判定）与 `memory`（长期记忆）的**职责已经存在**，只是还没有独立的包边界——
**在需要第二个实现之前不急于拆包**（避免为抽象而抽象）。

---

## 4. 能力注册表（决策 2）

### 4.1 声明契约

每个能力声明一张卡：

| 字段 | 含义 | 例 |
|---|---|---|
| `name` | 唯一 id | `perception.submission_detect` |
| `kind` | 类别 | `perception` / `planning` / `evaluation` / `tool` / `memory` / `teaching` / **`engagement`** |
| `stages` | 在哪些阶段参与 | `("learning",)` |
| `reads` | 读 state 的字段 | `("today_task",)` |
| `writes` | 写 state 的字段 | `("pending_submission",)` |
| `calls_llm` | 是否调模型（成本与延迟由此可算） | `True` |
| `autonomy` | 副作用级别（见 §6） | `"write"` |
| `order` | 同阶段内的确定性顺序 | `10` |
| `enabled` | 开关 | `True` |

### 4.2 规则

1. **声明即契约**：`reads` / `writes` 之外的 state 字段，能力**不得**触碰（越界视为缺陷）。
2. **顺序确定**：同阶段内按 `order` 升序执行；**不允许**依赖"字典顺序"或隐式时序。
3. **未声明默认 `danger`**（I-5）：新能力若忘了写 `autonomy`，会被当作危险动作处理。
4. **关闭即摘除**：`enabled=False` 时不参与矩阵，`turn.py` 无需改动。
5. **模型输出不写 state**：只有能力自己的结构化产出（经 Pydantic 校验）才允许写入。
6. **`autonomy` 是上限**：能力试图执行高于自身级别的动作 → **抛错**（不是降级执行）。
7. **工具默认 `read`**：只读检索可自主；任何写外部系统的工具必须是 `write` 或 `danger`。

### 4.3 骨架槽位 × 能力矩阵

**骨架槽位是固定的**（改它 = 改流程，应当难改）；**能力可插拔**（加它 = 不动 `turn.py`）。
一轮里有 **4 个推进点**，位置属于状态机契约（I-1）：

| 槽位 | 阶段 | 能力（按 order） | 调模型 | 副作用 | 状态 |
|---|---|---|---|---|---|
| `intake` | 任意 | `perception.profile_extract`（**仅画像未齐时**） | 是 | write | 现有 |
| `stage_pre` | `planning` | `perception.plan_confirm` → `planning.plan_generate` | 是 | write | 现有 |
| `stage_pre` | `learning` | `perception.submission_detect` → `planning.daily_task_build` | 是 / 否 | write | 现有 |
| `stage_pre` | `evaluation` | `evaluation.judge` | 是 | write | 现有 |
| `stage_pre` | `planning` | `perception.plan_parse` → `planning.plan_align` → `planning.plan_diff` | 是 | write | **待建 S-16** |
| `stage_pre` | `evaluation` | `perception.evidence_check` | 是 | read | **待建 S-13** |
| — | — | **【骨架推进点 #1】** | — | — | 现有 |
| `stage_post` | `assessment` | `planning.assessment_outline` | 是 | write | 现有 |
| `stage_post` | `evaluation` | `evaluation.ask_followup`（**上限 1 次**） | 是 | write | **待建 S-13** |
| `dialogue` | 任意 | `dialogue.coach_reply`（**用本轮起始阶段** —— I-2） | 是 | read | 现有 |
| `after_dialogue` | `assessment` | `perception.assessment_verdict` → `memory.assessment_finalize` | 是 / 否 | write | 现有 |
| — | — | **【骨架推进点 #2：测评收尾后（条件）】** | — | — | 现有 |
| `evaluation_apply` | `evaluation` / `profile_update` | `memory.profile_apply`（**内部含推进 #3、#4**） | 否 | write | 现有 |
| `closing` | `learning` | `planning.window_finish_check`（**用本轮起始阶段快照**） | 否 | read | 现有 |
| `closing` | `learning` | `planning.window_roll`（**会调模型**：生成新窗口） | 是 | write | 现有（v0.14） |
| `closing` | 任意 | `memory.commit_history` | 否 | write | 现有 |
| `closing` | 任意 | `engagement.feedback`（**仅反馈层**） | 否 | read | **待建 S-15** |
| 任意阶段（登记例外） | 任意 | `policy.exception_transition`：换任务 / 缩短本次 / 结束窗口 / 跳过测评 / 换目标 | 否 | write / **danger** | **待建 S-14** |

> **这张表就是 `turn.py` 原有 11 步硬编码顺序的显式化**，由 `coach/domain/capabilities.py`
> 声明、`coach/orchestration/executor.py` 执行。`turn.py` 已退化为薄壳（装配上下文 + 收尾）。

### 4.4 两处必须精确的语义（实现时踩过）

| 语义 | 为什么不能想当然 | 落地方式 |
|---|---|---|
| **阶段快照** | 原 `turn.py` **在不同位置取不同快照**：③ 用推进**前**的阶段算 `in_learning`，⑥ 用推进**后**的阶段。统一用实时阶段会让"窗口完成检查"被静默跳过 | 注册表字段 `stage_source ∈ {live, turn_start}`；`select_capabilities()` 按每条能力各取所需快照 |
| **推进点归属** | 推进 #1 是无条件的骨架动作；#2/#3/#4 是**条件性**的，属于对应能力的语义（"测评收尾"、"应用判定"） | #1 在 `execute_slots` 的槽位边界；#2/#3/#4 在 `_h_assessment_finalize` / `_h_profile_apply` 内部 |

> **`metrics` 不是能力**：指标记录是**横切**的（在 `llm/client.py` 与 `run_turn` 里内联），
> 不参与执行循环，因此不登记为能力。

### 4.5 校验：声明与实现不得脱节

`tests/test_capabilities.py` 断言：

- `validate_registry()` 无问题（名称唯一、`(slot, order)` 不冲突、`autonomy` 声明有效、每个阶段都有已启用能力…）
- **`missing_handlers()` 为空** —— 声明了能力却没写 handler/precondition 是最危险的漏步形态
- `engagement.*` **不得写任何判定字段**（**I-9 的结构化落实**）
- `dialogue.coach_reply` 的 `writes == ()`（教练回复不得隐式污染状态）
- 现有能力集合与 `turn.py` 的 11 步**逐条对应**
- 执行顺序钉桩（`tests/test_dialogue.py`）：`intake → stage_pre → 推进 → stage_post → dialogue → after_dialogue → evaluation_apply → closing`

---

## 5. 执行模型：Step / Selector / Policy（决策 5）

> 这一节回答"**后续是否容易更改**"。现在的 `turn.py` 把 11 步顺序**硬编码在控制流里**，
> 于是"加能力要改控制流、换范式要重写控制流"。把**"选步骤"抽成可替换策略**后，这两件事都变成改声明。

```
run_turn(ctx):
    steps = selector.select(ctx)          # ← 可替换策略（今天=矩阵，明天=混合）
    for step in steps:
        if not step.precondition(ctx): continue
        policy.ensure_allowed(step, ctx)  # ← 三级授权；越级抛错（I-4 / I-5）
        step.run(ctx)
    state_machine.try_advance(ctx.state)  # ← 唯一推进来源（I-1，不可让渡）
```

### 5.1 三个协作件

| 协作件 | 归属 | 职责 | **不得**做什么 |
|---|---|---|---|
| **Step** | `coach/domain/` | 一个可执行步骤：`name` / `precondition` / `run` / `autonomy` / `reads` / `writes` | 不得推进阶段；不得越出 `writes` |
| **Selector** | 编排层 | 决定**本轮跑哪些 Step、按什么顺序** | 不得绕过 Policy；不得直接改 state |
| **Policy** | `coach/domain/confirmations.py`（扩展） | 判定 step 是否被允许（三级授权 + 允许集） | 不得静默放行未登记动作（I-4） |

**关键收益：提议错了不会直接造成副作用。** Planner 只能"递方案"，Executive 决定"做不做"。

### 5.2 三种 Selector（同一条链，只换第一个组件）

| Selector | 语义 | 何时用 |
|---|---|---|
| **`MatrixSelector`** | 查【阶段×能力矩阵】定步骤 | **现在**（等价于当前行为） |
| `HybridSelector` | 默认走矩阵；**用户意图落在矩阵外时，允许模型提议步骤**，提议须过校验与守卫 | **固定路径覆盖不足被实测证实**之后 |
| `ModelSelector` | 模型决定全流程 | **不采用**（会牺牲"验收不可被裁量"） |

> **提议权可以给模型，决定权留在代码。** 守卫与授权门不变。

### 5.3 提议契约（启用 `HybridSelector` 时才落地）

```python
@dataclass(frozen=True)
class PlanProposal:
    intent: str                  # 模型对用户意图的理解（给人看）
    actions: tuple[str, ...]     # 从**允许集**里选，有序
    rationale: str               # 为什么这样选
```

**规则（对应 I-6）**：提议只能从当前阶段的允许集里选；**越界 → 拒绝 + 回退矩阵默认步骤**。
**绝不因提议失败而卡死** —— 与"判定失败保持当前阶段"是同一个设计原则。

另需显式声明上限：`max_steps`（一轮内最多几步）、`max_followups`（允许追问几次）。
**退出条件由代码判定，不由模型宣布。**

### 5.4 升级到 hybrid 的硬前置

| # | 前置 | 理由 |
|---|---|---|
| 1 | **补编排层测试覆盖**（当前仅 4/116 ≈ **3%**，而 X-16/X-17 正发生在这一层） | 没有仪表就开快车 |
| 2 | **把模型行为类缺陷转入评测集**（X-16 / X-17） | 确定性与行为层都要有防线 |
| 3 | **实测证实"固定路径覆盖不足"**（用户意图频繁落在矩阵外） | 避免为想象中的需求付代价 |

> **风险**：开了提议权，模型出错会从**内容错**升级为**流程错**，爆炸半径更大。
> **代价**：提议本身是一次模型调用 → 每轮调用数 +1（现 avg 2.2 → 约 3.2），直接撞 PRD §8 护栏。

---

## 6. 三级自主权（决策 3）

### 6.1 级别定义

| 级别 | 判定标准 | 是否需要确认 | 例 |
|---|---|---|---|
| **`read`** | 只读、或只写**派生且可重算**的状态 | 不需要 | 联网检索、渲染任务、记录指标 |
| **`write`** | 改变 **state 中影响后续行为**的字段 | 需要**记录**；若可逆则不必逐次确认 | 写画像、写计划、写 `pending_submission`、写 `latest_result` |
| **`danger`** | **不可逆**或影响用户长期权益 | **必须过确认门**（拒绝/超时/异常一律不执行） | 删学习历史、改长期目标、重建计划、标记技能已掌握 |

### 6.2 危险动作登记（已有）

`coach/domain/confirmations.py` 的 `GATED_ACTIONS` 是**唯一来源**，现登记 4 项：

| action_id | 级别 | 现状 |
|---|---|---|
| `rebuild_plan` | danger | 已登记；业务路径未实现 |
| `change_learning_goal` | danger | 已登记；业务路径未实现 |
| `delete_history` | danger | 已登记且**已端到端接线**（`/reset`、`/reset all`） |
| `mark_skill_mastered` | danger | 已登记；业务路径未实现 |

**未登记动作 → 抛 `UnknownActionError`**（不是静默放行）。

### 6.3 与能力的衔接规则

- 能力的 `autonomy` 是它的**上限**：能力试图执行超过自身级别的动作 → **抛错**。
- **工具默认 `read`**：只读检索、查询可自主；任何写外部系统的工具必须是 `write` 或 `danger`。
- 跨级提升需要**改登记表**，而不是散落在业务代码里写 `if`。

---

## 7. 感知契约草案（决策 4：先文档，后代码）

### 7.1 目标形状

```python
@dataclass(frozen=True)
class PerceptionResult:
    kind: str                  # 判定点 id：profile / submission / plan_confirmation /
                              #            assessment_verdict / evaluation_verdict
    payload: dict             # 该判定点的结构化产出（各自 Pydantic schema）
    ok: bool                  # 本次判定是否成功
    needs_confirm: bool       # 是否触发人机确认（转交策略层）
    raw: str | None = None    # 原始模型输出，仅用于排查与指标
```

### 7.2 不变量

| # | 不变量 | 理由 |
|---|---|---|
| P-1 | `ok=False` 时**不得写入任何"判定性"字段** | 失败必须走兜底（保持阶段 / 保守记 missing），不得把失败伪装成判定 |
| P-2 | `payload` 必须经 Pydantic 校验后才允许进入 state | 防模型自由文本污染状态 |
| P-3 | `raw` **只进日志/指标**，不进 state | 避免上下文膨胀与不可控内容入状态 |
| P-4 | 判定失败时**保持当前阶段、不推进** | 与 I-1 一致：没有判定就没有推进依据 |

### 7.3 现状与落地时机

当前 4 个判定点（`extract_profile` / `detect_submission` / `confirm_plan` / 两个 `*_judge`）
**各自实现了这套语义但没有统一类型**。**改代码的时机**：出现**第 5 个判定点**（例如工具调用、
teaching 的诊断）时一并统一——那时抽象才有第二个以上真实用例，避免现在改已测代码。

---

## 8. 与既有实现的衔接

| 架构要素 | 现状 | 本次是否需要动 |
|---|---|---|
| 状态机守卫 | `coach/domain/stages.py`，已被 10 个用例锁定 | 不动（I-1 的载体） |
| 单轮编排 | `coach/orchestration/turn.py`，11 步硬编码 | **改造为按矩阵驱动 + Step / Selector / Policy**（决策 2 / 5） |
| 确认门 | `coach/domain/confirmations.py`，16 个用例 | 扩展为**统一三级授权声明清单**（决策 3）+ 登记**例外转移**（S-14） |
| **计划模型** | 单一 `current_window` + 固定 `min(7, 期限)` | **改为双层 `roadmap` + `current_window`**，窗口自适应（决策 6 / S-12） |
| **时间预算** | `daily_minutes`（单字段） | 改为 `session_minutes` + `sessions_per_week` + `deadline_flex`（§11.3） |
| **验收** | `EvaluationResult`（completion / mastery / next_action） | 增加 `tier` / `evidence_form` / `mastery_declared`；**档位由代码定**（I-10 / S-13） |
| 提示词 | `coach/prompts/` 集中 | 不动（新增档位与计划的提示词） |
| 模型出口 | `coach/llm/client.py` 唯一出口 + 指标采集 | 不动 |
| 记忆 | 仅长期 `state`；**每轮注入全量 history** | **分层**（§12 / S-09） |
| 工具 | 不存在 | **待做**（S-04）；`ToolSpec` 形式由注册表 + 授权决定 |
| **趣味化** | 不存在 | **待做**（S-15）；**仅反馈层**（§13 / I-9） |
| 测试骨架 | `tests/_runner.py`（PASS / FAIL / **SKIP**）+ `audit.py` | 不动；新增能力须补用例与矩阵行 |

---

## 9. 演进路线与触发条件

| 阶段 | 内容 | 触发条件 |
|---|---|---|
| **现在** | 落地决策 2 / 3 / 5：**能力注册表 + 阶段×能力矩阵 + 三级授权清单 + Step / Selector / Policy** | — |
| **紧接着** | **S-12 双层计划模型 → S-13 验收档位 → S-14 例外转移 → S-16 自带计划** | 定位已修正（PRD v0.11） |
| 下一步 | 新增能力时**先登记卡片**，再写实现 | 任何加能力的需求 |
| 之后 | 第 5 个判定点出现时统一为 `PerceptionResult`（决策 4） | 工具 / teaching 落地 |
| 条件触发 | **启用 `HybridSelector`**（模型提议步骤） | ① 编排层测试补齐；② 模型行为类缺陷入评测集；③ **实测证实固定路径覆盖不足**（§5.4） |
| 条件触发 | 拆出 `coach/policy/` 包 | 授权规则超过登记表能表达的范围 |
| 条件触发 | 拆出 `coach/memory/` 包 | 记忆层实现超过 2 种（§12） |
| 条件触发 | 评估图编排框架作为**可替换后端** | 需要多日无人值守恢复、或需要持久化检查点 |

---

## 10. 与 PRD 的对应

| 本文 | PRD |
|---|---|
| §1 决策摘要、§2 十条不变量 | §2.1 方案总览与架构定性 |
| §3 分层 | §2.4 方案要素清单（S-01…S-16） |
| §4 能力注册表 | §2.2 需求→方案映射、§2.4 S-12～S-16 |
| **§5 执行模型（Step / Selector / Policy）** | §2.1 升级触发条件 |
| §6 三级自主权 | §3.4 冲突/人工介入、§2.4 S-08 / S-14 |
| §7 感知契约 | §2.6 生成式输出契约（模块 A） |
| §8 衔接 | §3.3.4 发布门槛（测试与审计要求） |
| §9 演进 | §2.10 版本范围与实现顺序 |
| **§11 计划模型与时间预算** | **§2.3 计划模型、S-12** |
| **§12 记忆分层与写入者** | **S-09、UR-06** |
| **§13 趣味化的位置与红线** | **S-15、UR-12、I-9** |

---

## 11. 计划模型与时间预算（决策 6）

### 11.1 为什么"天"不是正确单位

碎片化定位下，用户可能**一天学 3 次**，也可能**3 天学 1 次**。"3 天窗口"对他们没有意义。
**正确单位是"次（session）"。**

### 11.2 双层结构

| 层 | state 字段 | 粒度 | 滚动 |
|---|---|---|---|
| **长期** | `roadmap` | 目标 → **里程碑** | **不滚动**；仅里程碑达成 / 目标变更时更新 |
| **短期** | `current_window` | **一次一个可完成单元** | **滚动**；窗口结束后按实际进度生成下一窗口 |

### 11.3 时间预算字段（替代 `daily_minutes`）

| 字段 | 含义 | 默认 |
|---|---|---|
| `session_minutes` | **单次**可用时长（碎片化的基本单位） | 15 |
| `sessions_per_week` | 每周大约几次（可空 = 不承诺） | 5 |
| `deadline_flex` | 期限弹性：`hard` / `soft` / `none` | `soft` |

**推导规则**：`unit = "session" if session_minutes < 45 else "day"`
→ 一套模型同时覆盖**碎片化**与**整块时间**；`unit="day"` 时旧的 7 天窗口模型仍然可用（**旧资产不废弃**）。

### 11.4 窗口长度自适应（不再固定 3/7 天）

| 条件 | 窗口长度 |
|---|---|
| 有期限 + 每周次数 | 由里程碑与剩余可用时间推导 |
| 无期限、按里程碑 | = 该里程碑 `sessions_est`（默认 3–5 次） |
| **只想学一次** | **1 次**（无 `roadmap`） |
| 整块时间用户 | `unit="day"`，沿用 7 天模型 |
| **用户自带计划** | 按用户的阶段结构对齐里程碑（S-16） |

**"滚动" = 重估，不只是换下一批**：若 M1 估 5 次、实际用 8 次，则后续 `sessions_est` **上调**、
窗口长度随之调整。否则"滚动"只是换个任务列表。

### 11.5 约束与确认门

| 规则 | 说明 |
|---|---|
| **任务粒度约束** | 单任务预计时长 ≤ `session_minutes`，**由代码校验**（不靠模型自觉） |
| **确认门防打扰** | `roadmap` 首次**必须**确认；同里程碑内的窗口滚动**不打扰**；**跨里程碑需确认**；**改目标 = `danger`**（I-4） |
| **计划来源** | `roadmap.source ∈ {generated, user_provided}`；用户原始计划存 `roadmap.original`，**只读保留（I-7）** |
| **迁移** | `current_window` 平滑过渡为 `current_window`（`ensure_keys`），旧 state 文件不炸 |

---

## 12. 记忆分层与写入者（决策 7）

**现状**：只有长期 `state`，且**每轮注入全量 `conversation_history`**（已实测的成本问题，见 PRD X-09 / S-09）。

### 12.1 五层

| 层 | 存什么 | 生命周期 | **可写者**（对应注册表 `writes`） |
|---|---|---|---|
| **长期** | 画像四字段 / `skill_profile` / `weak_points` | 长期 | `memory.profile_apply` |
| **计划** | `roadmap` / `current_window` / 游标 / `original` | 目标周期 | `planning.*` |
| **短期窗口** | 最近 N 条对话 + 阶段小结 | 窗口 | 对话层 |
| **工具** | 检索结果缓存（TTL） | TTL | `tool.*` |
| **提议** | 提议历史（用于算采纳率与评测） | 会话 | `executive` |

**规则（对应 I-8）**：**每层声明写入者；跨层写入视为缺陷。**

### 12.2 短期窗口方案（S-09）

```
阶段隔离：非当前阶段的明细不注入
窗口：最近 8 条
归档：移出窗口的明细进 archive
阶段小结：进入新阶段时生成一句话小结，写进长期
```

**小结进长期、明细进归档** —— 既不丢信息，又控住上下文。

---

## 13. 趣味化的位置与红线（决策 8）

趣味化（连续次数、里程碑达成等）**能提升留存**，但对本项目有一个特殊风险：

> **它会奖励"把任务变小、把标准放低"** —— 而"验收"正是本产品的差异化。

### 13.1 位置

趣味化只作为 **`kind="engagement"` 的能力挂在"反馈层"**：

```
执行链：  … → evaluation.judge → memory.profile_apply → 【engagement.feedback】 → 回复用户
                      ↑ 判定链（engagement 不得进入）        ↑ 反馈层（只读）
```

- `autonomy = read`（只读画像与进度，产出一段反馈文本）
- **不得写** `latest_result` / `skill_profile` / `plan_progress` / `current_window`
- state 侧预留 `engagement` 字段（连续次数、里程碑、反馈历史）

### 13.2 红线（I-9）

| 禁止 | 说明 |
|---|---|
| 为"鼓励"放宽判定 | 趣味化**不得**影响 `completion` / `mastery` / **档位** |
| 篡改掌握度 | 画像只能由 `memory.profile_apply` 写 |
| 让趣味反馈成为通过依据 | 反馈是**输出**，不是**输入** |

### 13.3 验收测试要求

加入趣味化后，**必须**有一条用例断言：

> **开启趣味化前后，同一份提交得到完全相同的 `tier` 与 `completion`。**

没有这条用例，I-9 就只是一句口号。

---

## 附录 A · 框架完成度与缺口（滚动更新）

> 本附录回答一个问题：**"Agent 的基本框架搭完了吗？"**
> **框架件** = 与业务能力无关的结构性部件；**加新功能不应需要动它们**。
> 最后更新：2026-09-22（v0.14）。

### A.1 已完成（9 件）

| # | 框架件 | 载体 | 版本 |
|---|---|---|---|
| 1 | 分层包 + 依赖方向（下层不依赖上层） | `coach/` | v0.8 |
| 2 | 状态机 + 守卫（**I-1**） | `domain/stages.py` | v0.3 |
| 3 | 能力注册表 + 骨架槽位（**唯一流程来源**） | `domain/capabilities.py` | v0.12 |
| 4 | 执行器（唯一执行者） | `orchestration/executor.py` | v0.12 |
| 5 | 三级授权（read / write / danger，fail-closed） | `domain/autonomy.py` | v0.12 |
| 6 | 双层计划模型（路线图 + 执行窗口） | `domain/plan_rules.py` | v0.14 |
| 7 | 确认门（fail-closed；未登记动作抛错） | `domain/confirmations.py` | v0.6 |
| 8 | 指标与评测 | `coach/metrics/` + `evals/` | v0.7 |
| 9 | 状态迁移（幂等、不覆盖新值、不删旧键） | `domain/state_schema.py` | v0.13 |

### A.2 缺口（**下一步的工作清单**）

| 序 | 框架件 | 现状 | 说明 |
|---|---|---|---|
| **F1** | **感知契约 `PerceptionResult`** | ⬜ | 统一现有 4 个判定点。**§7.3 的触发条件即将满足**：S-13 会新增 2 个判定点（证据检查 / 限定追问），届时一并统一 |
| **F2** | **Planner（只提议）+ `PlanProposal` 契约** | ⬜ | 见 §5.3。含 `max_steps` / `max_followups` 上限与**失败回退** |
| **F3** | **记忆分层 + 写入者声明（I-8）** | ⬜ | 见 §12。现状是每轮注入全量 history（已实测的成本问题） |
| **F4** | **内容层护栏 guardrails** | ⬜ | 内容层的可验证约束，独立于编排层，可叠加 |
| **F5** | **单轮因果链（可观测）** | ⬜ | 现仅事件级指标；X-16 排查时只能人肉比对。目标：`输入 → 判定 → 状态变化 → 回复` **可回放** |
| **F6** | **状态 schema 显式版本号** | 🔸 | 已有 `ensure_keys` + 三类幂等迁移，缺 `schema_version` 字段 |
| **F7** | **`reads/writes` 的契约测试** | ⬜ | 见 A.3 |
| 条件 | `HybridSelector`（模型提议步骤） | ⬜ | **三条硬前置**见 §5.4 |

### A.3 已知风险：`reads/writes` 目前只是文档

`Capability.reads` / `writes` 的结果**没有任何测试校验**，因此已发现 **8 处欠声明**（声明少于实现实际读写）：

| 能力 | 欠声明 |
|---|---|
| `planning.daily_task_build` | `writes` 缺 `plan_progress` |
| `evaluation.judge` | `writes` 缺 `latest_result_applied` |
| `memory.assessment_finalize` | `writes` 缺 `assessment_progress` |
| `memory.profile_apply` | `writes` 缺 `latest_result_applied` / `today_task` / `pending_submission` |
| `planning.window_roll` | `writes` 缺 `pending_submission` / `latest_result` / `latest_result_applied` |
| `planning.window_finish_check` | `reads` 缺 `current_window` |
| `planning.plan_generate` | `reads` 缺 `skill_profile` |
| `perception.plan_confirm` | `reads` 缺 `roadmap` / `plan_progress` |

> **§4.2 规则 1（"声明即契约"）需要一条测试才能真正生效**：断言每个 enabled 能力的
> `writes ⊇ 该 handler 实际改动的 state 键`。这正是 **F7**。
>
> 补充说明：所有能力都不声明 `current_stage`，但骨架的 4 个推进点会写它 ——
> 这是**有意设计**（推进不属于任何能力，是 I-1 的载体），不算欠声明。
