# evals —— 评测集与判分一致率（M-01）

> 对应 PRD `docs/PRD.md`：§3.3.1 评测数据与防泄漏、§3.3.2 指标字典（M-01）、§3.3.4 发布门槛、§9 质量要求。
> 本目录是 **S-07** 的"评测集"部分；S-07 的另一半 —— **事件级指标采集与导出**
> （`tokens / cost / latency / 每轮调用次数`）—— 已在 `coach/metrics/`（`recorder` / `summary` / `export`）
> 实现，并由 `tests/test_metrics.py`（18 条确定性用例）覆盖，用法见 `python -m coach.metrics.export`。

## 这是什么

一套**只评 LLM 非确定性判定**的评测集与 runner。

确定性逻辑（状态机守卫、计划清洗、分数聚合、薄弱点阈值、游标推进…）已由 `tests/` 的 **168 个用例**
（161 确定性 + 7 条 live；无 Key 时 live 记 SKIP 且不计入通过数）覆盖，属于 PRD 的**固定回归集**，本评测集**不重复**。

| judge | 被测函数 | 期望字段 |
|---|---|---|
| `assessment_verdict` | `coach.services.assessment.record_answer` | verdict |
| `evaluation_completion` | `coach.services.evaluation.evaluate` | completion + next_action |
| `submission_detect` | `coach.services.daily_task.detect_submission` | is_submission |
| `plan_confirm` | `coach.services.planning.confirm_plan` | confirmed |
| `profile_extract` | `coach.services.profile.extract_profile` | 四字段 |

## 目录

```
evals/
├── README.md              # 本文件
├── schema.md              # 字段定义、判定 rubric、标注规则、已知局限
├── dataset/
│   ├── dev.jsonl          # 开发评测集（30 条）——调提示词时只看这个
│   └── holdout.jsonl      # 独立验收集（8 条）——只用于发布判断
├── dataset_overview.md    # 自动生成：dev 的可读总览（勿手工编辑）
├── holdout_overview.md    # 自动生成：holdout 的可读总览（勿手工编辑）
├── results/               # 自动生成：--live 的结果导出（CSV / JSONL）
└── run_eval.py            # runner
```

## 怎么用

在 `App_landing` 目录下：

```powershell
# 1) 查看评测集（只读渲染，不调用模型）★ 想"看内容"用这个
.\.venv\Scripts\python.exe evals\run_eval.py --show
.\.venv\Scripts\python.exe evals\run_eval.py --show --filter evaluation   # 按 id/judge/domain/risk 过滤
.\.venv\Scripts\python.exe evals\run_eval.py --show --dataset holdout
.\.venv\Scripts\python.exe evals\run_eval.py --export-md evals\dataset_overview.md   # 导出可读总览

# 2) dry-run（默认）：只校验数据集格式与分布，不调模型、不花钱
.\.venv\Scripts\python.exe evals\run_eval.py
.\.venv\Scripts\python.exe evals\run_eval.py --dataset holdout

# 3) 真实评测（需要 DEEPSEEK_API_KEY）
$env:DEEPSEEK_API_KEY = "sk-..."
.\.venv\Scripts\python.exe evals\run_eval.py --live
.\.venv\Scripts\python.exe evals\run_eval.py --live --repeat 3

# 4) 导出结果（JSONL / CSV）
.\.venv\Scripts\python.exe evals\run_eval.py --live --format csv --out evals\results\m01.csv
```

未指定 `--out` 时，结果写到 `evals/results/m01_<数据集>_<时间戳>.<格式>`。

### 三种"查看"方式

| 想看什么 | 用什么 |
|---|---|
| **逐条看内容**（输入 / 期望 / 判定依据 / 备注） | `--show`（可配 `--filter`） |
| **在编辑器里通读并评审标签** | `--export-md evals\dataset_overview.md`（holdout 用 `evals\holdout_overview.md`） |
| **只看覆盖度**（分布统计，不列内容） | 直接跑（默认 dry-run） |

> `dataset_overview.md` / `holdout_overview.md` 是**自动生成**的派生物，请勿手工编辑——
> 改标签请改 `dataset/*.jsonl` 后重新导出（`--export-md`）。

## 输出怎么读

```
总体一致率（M-01）：xx.x%  （一致 n / 比对 m，错误 e）
按 judge 分层： ...
按 domain 分层： ...
按 risk 分层： ...
```

三条纪律（对应 PRD）：

1. **分层必须看**。PRD §3.3.4 明确"关键分层不得被总体均值掩盖"——总体 90% 但某领域 60% 是不能发布的。
2. **error 不计入分母**。模型调用失败单列并告警；否则会把"接口挂了"误读成"判得准"。
3. **阈值仍未定**。M-01 目标 **≥90%** 属于**待定**（PRD §3.7 O-02：先测基线再定）。本目录**不预设结论**。

## 防泄漏规则（PRD §3.3.1）

- **dev 与 holdout 物理分离**：调提示词、改判定规则时**只看 dev**。
- **holdout 有硬保护**：对 holdout 跑 `--live` 必须显式加 `--allow-holdout`，避免随手拿验收集调参。
- holdout 只用于**发布决策**读数。

## 与 PRD 的对应

| PRD 条目 | 本目录 |
|---|---|
| §3.3.1 开发评测集（20~30 条） | `dataset/dev.jsonl`（30 条） |
| §3.3.1 独立验收集（与开发集分离） | `dataset/holdout.jsonl`（8 条） |
| §3.3.2 M-01 判分一致率 | `run_eval.py` 的分层报告 |
| §3.3.1 防泄漏规则 | dev/holdout 分离 + `--allow-holdout` |
| §3.3.4 分层不得被均值掩盖 | 按 judge / domain / risk 分层输出 |

## 已知局限（如实标注，详见 `schema.md` §6）

1. **心理学领域代码尚未实现**（S-02/S-05 = ⬜待实现）：心理学用例现在只能验证判定提示词在该内容上的表现。
2. **`profile_extract` 的调用失败不可区分**（失败时返回空画像，与"确实没提供信息"在返回值上一致）。
3. **单次运行有波动**：即使 `temperature=0` 也可能变化，发布判断建议 `--repeat 3`。
4. **样本量小**：dev 30 条 / holdout 8 条，仅够发现明显问题，**不足以支撑统计显著性结论**。
5. **标注由 AI 起草、人工复核**：`rubric` 字段写明每条期望的依据，复核时直接对照生产提示词修改。
6. **争议用例不自动剔除**：runner 一律计入分子/分母，争议条须在复核阶段改标签或移出数据集（详见 `schema.md` §6.5）。

## 待办

- [ ] 人工复核 30 条 dev + 8 条 holdout 的 `expected` 与 `rubric`（当前为 AI 起草）。
- [ ] 跑出第一份 M-01 基线，据此确定阈值（O-02）。
