# 评测集 Schema 与标注规则

> 对应 PRD `docs/PRD.md` §3.3.1（评测数据与防泄漏）、§3.3.2（指标字典 M-01）、§3.3.4（发布门槛）。
> 本文件定义**评测集的字段格式、判定 rubric 与标注规则**，供标注者与 `run_eval.py` 共同遵循。

## 1. 评测边界：只评「非确定性判定」

本评测集**只覆盖 LLM 判定点**。确定性逻辑（状态机守卫、计划清洗、分数聚合、薄弱点阈值、游标推进等）已由
`tests/` 的 **73 个用例**（66 确定性 + 7 集成）覆盖，属于**固定回归集**，**不重复进入评测集**。

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
| `notes` | ❌ | string | 补充说明、已知争议点 |

## 3. 标注规则（最重要）

1. **以生产提示词的口径为准**，不以标注者的个人偏好为准。每条 `expected` 必须能在对应 `*_SYSTEM_PROMPT` 里找到依据。
2. **边界优先**：宁可多写"看起来很普通但其实容易判错"的用例（如"我会了"但无产出），也不要堆同质化的正常用例。
3. **不确定就标注争议**：写进 `notes`，不要强行给一个标签。争议用例不计入一致率的分子/分母由复核决定。
4. **不得为了让结果好看而改标签**。标签只依据 rubric。
5. **dev 与 holdout 严格分离**：调提示词时**只能看 dev**；holdout 用于发布判断，查看前不得据其反复调参（PRD §3.3.1 防泄漏规则）。

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

| completion | 口径 | 对应 next_action（**由代码强制**，见 `evaluator.normalize_action`） |
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
  "plan": { "horizon_days": 7, "start_date": "2026-09-22", "days": [ { "day": 1, "theme": "...", "tasks": [ { "goal": "..." } ] } ] },
  "user_input": "用户这句话"
},
"expected": { "confirmed": true }
```

`true` 仅当用户**明确同意开始**（"可以""没问题""就这样""开始吧""按这个来"）；含糊、反问、质疑、要求修改一律 `false`。

### 4.5 `profile_extract`

文本字段**不做精确字符串比对**（措辞有合理变化），改用关键字与归一化值：

```json
"input":    { "text": "用户这一句话" },
"expected": {
  "learning_goal_keywords": ["Python", "数据分析"],
  "current_level_keywords": ["基础"],
  "daily_minutes": 30,
  "target_date": "一个月"
}
```

| 字段 | 比对方式 |
|---|---|
| `learning_goal_keywords` | 列表中**全部**关键字须出现在抽取值中（大小写不敏感）。**空列表 = 该字段必须为空（null）** |
| `current_level_keywords` | 同上 |
| `daily_minutes` | 整数精确比对；`null` = 必须为 null（无法解析就宁缺勿错） |
| `target_date` | 去掉空白后精确比对；`null` = 必须为 null（如"尽快""年底"这类模糊表达） |

**证据要求**：抽取只应采纳用户**明确说出**的信息，不得推测、补充常识或编造。

## 5. 一致率计算（M-01）

```
一致率 = 与期望一致的用例数 ÷ 参与比对的用例数
```

- **分层报告**：总体一致率 **+ 按 judge 分层 + 按 domain 分层**。PRD §3.3.4 明确要求"关键分层不得被总体均值掩盖"。
- **错误（error）单列**：模型调用失败（返回 `None`）或判定调用失败的用例记为 `error`，**不计入分母**，但必须在报告中醒目列出——否则会把"接口挂了"误读成"判得准"。
- **阈值**：M-01 目标 **≥90%**，当前状态为 **待定**（PRD §3.7 O-02：先测基线再定阈值）。本评测集**不预设结论**。

## 6. 已知局限（如实标注）

1. **心理学领域代码尚未实现**（PRD S-02/S-05 = ⬜待实现）。心理学用例现阶段只能验证**判定提示词在心理学内容上的表现**，不能验证领域化的计划/出题逻辑；待 S-05 落地后价值完整。
2. **`profile_extract` 的失败不可区分**：该函数在调用失败时返回"空画像"，与"用户确实没提供信息"在返回值上一致。因此该 judge 的 `error` 可能被误计为一致（当期望恰为全 null 时）。已在报告中标注该限制。
3. **单次运行有波动**：即使 `temperature=0`，模型输出仍可能变化。判定一致率应按**重复运行**理解（PRD M-01 要求写清重复或容错规则）；建议发布判断时跑 ≥3 次取稳定值。
4. **样本量小**：30 条仅够发现明显问题，**不足以支撑统计显著性结论**（PRD §3.3.4 已知例外）。
