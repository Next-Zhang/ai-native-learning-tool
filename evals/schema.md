# 评测集 Schema 与标注规则

> 验证口径与发布协议见 [验证报告](../docs/validation.md)，产品需求见 [PRD](../docs/PRD.md)。本文件只定义评测数据格式与标注规则。
> 本文件定义**评测集的字段格式、判定 rubric 与标注规则**，供标注者与 `run_eval.py` 共同遵循。

## 1. 评测边界：只评「非确定性判定」

本评测集只覆盖 LLM 判定点。确定性逻辑由 tests/ 回归；测试数量与实际执行结果在验证报告登记，不在这里重复维护。
当前字段对应已有实现，不能直接证明新的持续学习体验有效；新增目标、接续与复验场景需补充独立评测。

| judge 值 | 被测函数 | 被测提示词 | 期望字段 |
|---|---|---|---|
| `assessment_verdict` | `coach.services.assessment.record_answer` | `coach.prompts.tasks.ASSESSMENT_JUDGE_SYSTEM_PROMPT` | `verdict` |
| `evaluation_completion` | `coach.services.evaluation.evaluate` | `coach.prompts.tasks.EVALUATION_JUDGE_SYSTEM_PROMPT` | `completion`, `next_action` |
| `submission_detect` | `coach.services.daily_task.detect_submission` | `coach.prompts.tasks.SUBMISSION_SYSTEM_PROMPT` | `is_submission` |
| `plan_confirm` | `coach.services.planning.confirm_plan` | `coach.prompts.tasks.CONFIRM_SYSTEM_PROMPT` | `confirmed` |
| `profile_extract` | `coach.services.profile.extract_profile` | `coach.prompts.tasks.EXTRACT_SYSTEM_PROMPT` | 四字段（见 §4.5） |

## 2. 通用字段

每条用例是一个 JSON 对象（JSONL，一行一条）：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `id` | ✅ | string | 唯一编号。dev 用 `DEV-<judge缩写>-<序号>`；holdout 用 `HO-...` |
| `domain` | ✅ | string | `programming` \| `psychology`（用于**分层一致率**，不允许总体均值掩盖分层失败） |
| `judge` | ✅ | string | 见 §1 的 5 个值 |
| `risk` | ✅ | string | `normal` \| `boundary` \| `adversarial` |
| `input` | ✅ | object | 送入被测函数的输入（结构随 judge 变化，见 §4） |
| `expected` | ✅ | object | 期望判定结果（结构随 judge 变化，见 §4） |
| `rubric` | ✅ | string | **为什么这个期望是对的**（人工可复核的依据） |
| `notes` | ❌ | string | 补充说明、已知争议点（`--show` 与 `--export-md` 都会渲染出来） |

## 3. 标注规则（最重要）

1. **以已确认产品规则和任务量规为准**，不以个人偏好或模型输出为准；生产提示词与新规则不一致时登记契约差距，开发评测与目标验收分别说明，不降低标准迎合旧提示词。
2. **边界优先**：宁可多写"看起来很普通但其实容易判错"的用例（如"我会了"但无产出），也不要堆同质化的正常用例。
3. **不确定就标注争议**：写进 `notes`，不要强行给一个标签。**争议用例的处置在标注/复核阶段完成**（改标签或移出数据集）——`run_eval.py` 不做自动剔除，见 §6.5。
4. **不得为了让结果好看而改标签**。标签只依据 rubric。
5. **dev 与 holdout 严格分离**：调提示词时只能看 dev；holdout 用于独立验收，不据其反复调参。

### 三个关键的"反直觉"口径（易错点）

| 情形 | 正确判定 | 依据 |
|---|---|---|
| 用户说"我会了 / 做好了"但**没有实际产出** | `missing`（测评）/ `not_completed`（验收）/ `is_submission=false` | 各提示词明确写有该规则 |
| 用户**在提问 / 要提示 / 闲聊 / 说"快好了"** | `is_submission=false` | `SUBMISSION_SYSTEM_PROMPT` |
| 用户回复**含糊、反问、质疑、要求修改** | `confirmed=false`（只有明确同意才算 true） | `CONFIRM_SYSTEM_PROMPT` |

## 4. 各 judge 的输入与期望结构

### 4.1 `assessment_verdict`

```json
"input":    { "topic": "知识点", "coach_reply": "上一轮教练出的题", "user_answer": "用户本轮回答" },
"expected": { "verdict": "mastered | partial | missing" }
```

| verdict | 口径（摘自 JUDGE_SYSTEM_PROMPT） |
|---|---|
| `mastered` | 完全正确，或思路完整、结论正确 |
| `partial` | 部分正确、有小错、思路不完整 |
| `missing` | 没有作答、答非所问、明确表示不会；**只说"我会了"但没有实际作答 → missing** |

### 4.2 `evaluation_completion`

```json
"input": {
  "task": { "goal": "...", "exercise": "...", "done_criteria": "..." },
  "submission": { "content": "用户提交的内容" }
},
"expected": { "completion": "completed | partial | not_completed", "next_action": "pass | retry | supplement" }
```

| completion | 口径 | 对应 next_action（**由代码强制**，见 `coach.domain.evaluation_rules.normalize_action`） |
|---|---|---|
| `completed` | 完全达成完成标准 | `pass` |
| `partial` | 部分达成，有小错、缺步骤或边界未处理 | `supplement` |
| `not_completed` | 未达成：错误、答非所问、**没有实际产出** | `retry` |

> `next_action` 的期望值**由完成度决定**，不是模型自由给出的；若模型给出"没做完却 pass"，`EvaluationResult` 的一致性守卫（`coach.domain.evaluation_rules.normalize_action`）会纠正它。因此这两项一起比对。

### 4.3 `submission_detect`

```json
"input":    { "task": { "goal": "...", "exercise": "...", "done_criteria": "..." }, "user_input": "用户这句话" },
"expected": { "is_submission": true }
```

`true` = 给出了答案/代码/运行结果/作业说明等**可检验产出**；`false` = 提问、要提示、闲聊、还没开始、只是在确认要求。

### 4.4 `plan_confirm`

```json
"input": {
  "plan": { "length": 3, "unit": "session", "start_date": "2026-09-22", "milestone_id": "M1",
            "days": [ { "day": 1, "theme": "...", "tasks": [ { "goal": "..." } ] } ] },
  "user_input": "用户这句话"
},
"expected": { "confirmed": true }
```

`plan` 就是**执行窗口** `state["current_window"]`：`length` = 单元数，`unit` = `session`（按"次"）
或 `day`（按"天"）。**旧字段名是 `horizon_days`，v0.14 起改为 `length`**（旧值由
`state_schema.upgrade_window_shape` 迁移，见 `tests/test_stages.py`）。

`run_eval.py` 把它原样交给 `planning.confirm_plan`，判定依据是 `planning.describe_plan()` 渲染出的摘要
（会读取路线图、窗口与确认状态；`length` 缺失时退回 `len(days)`）。数据集里的 `length` 必须与 `days` 的条数一致。

`true` 仅当用户**明确同意开始**（"可以""没问题""就这样""开始吧""按这个来"）；含糊、反问、质疑、要求修改一律 `false`。

### 4.5 `profile_extract`

文本字段**不做精确字符串比对**（措辞有合理变化），改用关键字与归一化值：

```json
"input":    { "text": "用户这一句话" },
"expected": {
  "learning_goal_keywords": ["Python", "数据分析"],
  "current_level_keywords": ["基础"],
  "session_minutes": 30,
  "target_date": "一个月"
}
```

| 字段 | 比对方式 |
|---|---|
| `learning_goal_keywords` | 列表中**全部**关键字须出现在抽取值中（大小写不敏感）。**空列表 = 该字段必须为空（null）** |
| `current_level_keywords` | 同上 |
| `session_minutes` | 整数精确比对；`null` = 必须为 null（无法解析就宁缺勿错）。**旧字段名是 `daily_minutes`，已废弃** |
| `target_date` | 去掉空白后精确比对；`null` = 必须为 null（如"尽快""年底"这类模糊表达） |

**证据要求**：抽取只应采纳用户**明确说出**的信息，不得推测、补充常识或编造。

## 5. 一致率计算（M-01）

```
一致率 = 与期望一致的用例数 ÷ 参与比对的用例数
```

- **分层报告**：总体一致率及 judge / domain / risk 分层；关键分层不能被总体均值掩盖。
- **错误单列**：PerceptionResult.ok=False 等调用/判定失败记为 error，不计入有效比对分母；同时报告错误数、有效覆盖与失败率。
- **无效输出**：当前服务可能接受空对象等默认值（D-04），因此 ok=True 也需要内容契约审查，不能仅看接口形状。
- **阈值与数量**：PRD 的 M-01 每次 ≥90%，独立验收集至少 30 条不同样本、5 类 judge 各至少 6 条，人工复核并冻结；完整评测 3 次，每次关键错误必过，单独报告各次分层/故障/覆盖。均值/投票/择优不能代替每次达标；重复不增加独立样本，网络重试不增加评测轮数。

## 6. 已知局限（如实标注）

1. **领域边界**：某领域的判定样例通过，不能证明完整出题、计划、持续学习或任意领域普适性。
2. **失败契约**：profile_extract 已用 PerceptionResult 区分调用失败；内容有效性、测评故障记分与空输出仍存在缺口，见交付清单。
3. **单次运行有波动**：即使 temperature=0 也可能变化；重复运行分别报告，不以少数重复称为长期稳定。
4. **样本量小**：当前样本不足以支撑统计显著性或持续学习收益结论；具体数量与标签复核状态见验证报告。
5. **争议用例不做自动剔除**：runner 没有跳过争议条的开关；有效比对计入分母，调用失败单列。
   标注为争议的用例（写在 `notes` 里，`--show` / `--export-md` 会显示）必须在**复核阶段**决定处置：
   要么按生产提示词口径定标签，要么把它移出数据集。**不要指望 runner 帮你去掉它**。
6. **`rubric` 只做非空校验**：`run_eval.py` 只能检查 `rubric` 是否存在，无法判断它是否真的支撑该期望；
   rubric 与生产提示词的口径一致性靠人工复核，并将结果记入验证报告。

## 候选与正式验收附加字段

新候选包含 review_status（pending/reviewed）、reviewer、origin、critical（布尔）。人工未独立复核和处置争议前不得标 reviewed；critical 名单在冻结前确定。正式协议额外检查至少 30 条、五类各至少 6 条、三类 risk 和关键样例，并在完整三轮分别判定。旧数据兼容读取不自动补造 reviewed。
workflow-scenarios 使用独立字段 id/acceptance_id/given/when/expected/execution/verification，属于流程规格，不交给五类 judge runner 执行。
