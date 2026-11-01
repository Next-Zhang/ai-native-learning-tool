# 判定评测

本目录评估 LLM 非确定性判定，不等于验证完整学习效果。
指标与验收要求以 [PRD 1.0 第 8 节](../docs/PRD.md#8-成功标准与试用门槛) 为准，执行证据与协议操作见 [验证报告](../docs/validation.md)；数据格式见 [Schema](schema.md)；
实现及接口缺口见 [交付清单](../docs/delivery.md)。

## 对象

| judge | 被测函数 | 比对字段 |
|---|---|---|
| assessment_verdict | assessment.record_answer | verdict |
| evaluation_completion | evaluation.evaluate | completion / next_action |
| submission_detect | daily_task.detect_submission | is_submission |
| plan_confirm | planning.confirm_plan | confirmed |
| profile_extract | profile.extract_profile | 当前画像抽取字段 |

run_eval.py 调用服务；dataset/dev.jsonl 用于开发，holdout.jsonl 用于独立验收。
数据集条数、有效执行数、错误数与分层结果只在运行报告/验证报告登记。

## 使用

在 App_landing 目录：

```powershell
python evals/run_eval.py
python evals/run_eval.py --show
python evals/run_eval.py --show --filter evaluation
python evals/run_eval.py --live --repeat 3
python evals/run_eval.py --live --format csv --out evals/results/m01.csv
```

默认只校验格式与分布；--show 显示内容，不调用模型。
--live 需要 API Key、会调用真实模型并写结果；未指定 --out 时输出到 evals/results/。
--export-md 可导出可读总览，该总览是派生物，标签应在 JSONL 源数据维护。
对 holdout 跑 --live 需要显式 --allow-holdout；不能反复用验收集调参。

## 解释与边界

- M-01 每次 ≥90%；独立验收集至少 30 条、5 类 judge 各至少 6 条，人工复核并冻结；完整评测 3 次，每次关键错误必过，不能以均值或投票替代。现有 --repeat 3 的逐样本汇总不直接等于逐次完整运行达标报告；正式验收需按验证报告保留各次索引、分层与有效覆盖。本轮未扩充数据集或修改 runner。
- 一致率按有效比对计算；调用失败/无效判定必须同时报告，不能以排除错误后的高分宣称可靠。
- 同时看 judge、domain、risk 分层；期望标签需要人工复核。
- 部分服务已改为 PerceptionResult，旧 live 回归用例尚有接口漂移；评测前核对调用者。
- profile_extract 已能区分调用失败，但评价中的“有效输出”仍需内容契约；空对象默认值问题见 D-04。
- 本评测覆盖判定点，不证明计划质量、跨次保持、持续使用收益或任意领域普适性。
- 当前数据仍对应旧画像与流程；持续学习的目标、复验及接续需补独立场景，不能用旧数据直接证明新定位有效。

## 本地初版补充协议

新协议见 [本地验收与评测](../docs/acceptance-protocol.md)。新增 acceptance-candidate 30 条均待人工复核，workflow-scenarios 35 条是未执行流程规格；原 dev/holdout 不改。`python evals/acceptance_protocol.py` 只做离线就绪检查，正式三轮采用显式冻结和 live 参数，不能用旧 --repeat 汇总代替。
