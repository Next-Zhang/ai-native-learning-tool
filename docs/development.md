# 开发与运行指南

更新：2026-10-13。本页负责操作方式；需求、结构、待办、结果分别见 [PRD](PRD.md)、[当前架构](architecture.md)、[交付清单](delivery.md)、[验证报告](validation.md)。
以下命令是操作说明，本轮文档调整未执行它们。

## 1. 安装与配置

在 App_landing 目录用 Python >=3.10 创建 venv，激活后 python -m pip install -e .。
核心依赖由 pyproject.toml 声明；requirements.txt 还包含 RAG 依赖，不是最小安装清单。

| 环境变量 | 用途 |
|---|---|
| DEEPSEEK_API_KEY | 模型凭据，不能写入代码或提交 |
| COACH_MODEL / COACH_BASE_URL | 覆盖模型与 API 地址 |
| COACH_PRICE_IN_PER_MTOK / COACH_PRICE_OUT_PER_MTOK | 每百万 token 单价；未配置成本记未知 |
| COACH_METRICS / COACH_METRICS_PATH | 指标启用与输出路径覆盖 |

python app.py、python -m coach、learning-coach 均启动 CLI。路径当前锚定包所在项目目录，状态默认落在 data/。
可安装为其他形式不代表已具备任意目录部署或多用户隔离能力。

## 2. 新能力的当前接入方式

1. 在 domain/capabilities.py 的 REGISTRY 声明阶段、槽位、顺序、读写键与自主权。
2. 在 orchestration/executor.py 的 PRECONDITIONS、HANDLERS 中登记前置条件与处理函数。
3. 业务规则放 domain；模型调用走 services → llm.client；通常不需改 turn.py。
4. 更新能力完整性、行为与写入契约 fixture；新增写字段同步 schema 与逻辑归区。
5. 改产品要求先改 PRD；改实现同步架构和交付清单；运行结果进验证报告。

注册表不会自动取得用户确认。新增危险动作必须接通 require_human_confirmation，
不能把 action_id 已登记当成授权；统一执行门缺口见 D-05。
reads/writes 主要由测试检查，不是运行时隔离。保留 I-1～I-14 的约束，见架构决策。

## 3. 回归测试

使用 tests/_runner.py，PASS / FAIL / SKIP 三态；不用 pytest 作为现有标准入口。
每个 tests/test_*.py 都能独立运行，例如：

```powershell
python tests/test_stages.py
python tests/test_dialogue.py
python tests/test_perception.py
python tests/test_contracts.py
```

完整运行示例（收集每个脚本退出码）：

```powershell
$failedScripts = @()
Get-ChildItem tests/test_*.py | Sort-Object Name | ForEach-Object {
    python $_.FullName
    if ($LASTEXITCODE -ne 0) { $failedScripts += $_.Name }
}
if ($failedScripts.Count -gt 0) { throw ("失败脚本：" + ($failedScripts -join ", ")) }
```

有 DEEPSEEK_API_KEY 时 live 用例会调用真实模型。无 Key 时必须 raise SkipTest，不能 return 伪装通过。
当前部分 live 测试仍使用旧结果接口（D-09）；不能用跳过的结果宣称它们有效。
涉及 IO 的用例会产生测试临时产物，执行前检查是否满足当前任务的文件操作边界。

python tests/audit.py 是静态审计，会更新 docs/test-audit.md；它不执行完整回归，不输出行为覆盖率。
实际通过/失败/跳过、代码状态和环境写入验证报告或运行产物。

## 4. 判定评测与指标

[evals 说明](../evals/README.md) 提供 dev / holdout 运行方法；[Schema](../evals/schema.md) 定义 rubric 与标注。
先验证接口、人工复核标签，再做真实模型评测；holdout 只用于独立验收。

```powershell
python evals/run_eval.py
python evals/run_eval.py --show
python evals/run_eval.py --live --repeat 3
python -m coach.metrics.export
```

默认 eval 是格式校验；--live 调用 API 并保存结果，不属于只读操作。
metrics 默认由 CLI 开启，输出 data/metrics/events.jsonl；trace 在 data/traces/ 下记录单轮过程。
trace 含用户输入与回答；测试与工具不应误开真实数据采集。
当前指标 P95 是调用级，不能直接当作端到端延迟，见 D-10。

## 5. 可选 RAG

当前源码目录下安装可选依赖：

```powershell
python -m pip install -e ".[rag]"
python -m rag.build
python -m rag.retrieve "字典的 get 方法"
python -m rag.retrieve --selfcheck
```

数据源为 runoob Python3 教程，使用本地 BGE-M3 ONNX embedding 和 Qdrant。
首次运行可能下载较大模型、联网抓取并写 data/rag/；当前 pyproject 包清单未含 rag，
上述方式依赖源码目录，不能当作已验证的独立分发包。

单阶段命令：python -m rag.crawl --limit 3、python -m rag.chunk、python -m rag.embed_store --force。
重建命令：python -m rag.build --rebuild。运行会写文件、消耗资源，按需使用。
Agent 由 /rag on 开启，检索失败按无参考资料继续；引用存在不等于内容正确。

## 6. 开发用重置

优先在 CLI 使用带确认的 /reset 与 /reset all，清理限制见 README 和 D-03。

退出会话后，开发者可直接使用以下工具。**这些命令会修改学习状态，命令行工具自身不询问确认。**

```powershell
python -m coach.storage.reset
python -m coach.storage.reset --history
python -m coach.storage.reset --stage assessment
```

默认先备份，最近 5 份；--no-backup 禁用备份。只操作用户状态和备份，不清 RAG 数据。
不能在真实学习状态上为测试随意执行；阶段跳转只用于准备测试，不是用户产品流程。
