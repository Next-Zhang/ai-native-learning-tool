# 测试审计报告

- 用例总数：**212**
- **无 Key 时跳过**：**8**（live 用例，有 Key 才会真正跑；runner 单列 SKIP，**不计入通过数**）
- → 无 Key 时实际校验 **204** 条；有 Key 时实际校验 **212** 条
- assert 语句总数：725（平均每用例 3.4 条）

## 一、按断言对象分层

| 分层 | 用例数 | 占比 |
|---|---|---|
| 纯函数 | 121 | 57% |
| 行为（跨 domain 之外） | 45 | 21% |
| 持久化 / IO | 19 | 9% |
| 跨层 / 编排 | 10 | 5% |
| 契约 / 规格钉桩 | 9 | 4% |
| live 真实模型（默认跳过） | 8 | 4% |

## 二、按文件分层

| 文件 | 用例 | 纯函数 | 行为（跨 | 跨层 | 持久化 | 契约 | live |
|---|---|---|---|---|---|---|---|
| `test_assessment.py` | 12 | 10 | 0 | 0 | 0 | 0 | 2 |
| `test_capabilities.py` | 26 | 20 | 0 | 1 | 0 | 4 | 1 |
| `test_confirmation.py` | 16 | 8 | 2 | 0 | 5 | 1 | 0 |
| `test_daily.py` | 12 | 7 | 4 | 0 | 0 | 0 | 1 |
| `test_dialogue.py` | 15 | 2 | 3 | 9 | 0 | 1 | 0 |
| `test_evaluation.py` | 11 | 5 | 5 | 0 | 0 | 0 | 1 |
| `test_memory.py` | 31 | 24 | 7 | 0 | 0 | 0 | 0 |
| `test_metrics.py` | 18 | 0 | 12 | 0 | 5 | 1 | 0 |
| `test_plan.py` | 28 | 18 | 8 | 0 | 0 | 0 | 2 |
| `test_profile.py` | 13 | 11 | 0 | 0 | 0 | 1 | 1 |
| `test_reset.py` | 11 | 0 | 2 | 0 | 9 | 0 | 0 |
| `test_stages.py` | 19 | 16 | 2 | 0 | 0 | 1 | 0 |

## 三、发现的问题

- ✅ **已修复**：8 条 live 用例在无 Key 时显式 `raise SkipTest`，runner（`tests/_runner.py`，已接入 12 个测试文件）单列 SKIP 并**不计入通过数**——「204 通过 / 8 跳过」是诚实读数（数字由本脚本按当前用例数算出，不写死）。
- （信息性）**2 条没有显式 `assert`**：['test_ensure_action_registered_accepts_registered_action', 'test_ensure_action_registered_skips_for_write_level'] —— 属「调用后不抛异常」型**隐式断言**（被测函数一旦抛错，用例即失败），仍然有效，此处仅作提示。
- （信息性）**38 条断言 ≤ 1 处**——不一定有问题，但薄断言容易在重构后失去意义，值得抽查（含上面那些没有显式断言的用例）。
- **9 条是契约钉桩**（只断言常量/提示词文本，不调用任何被测函数）：它们能防误删，但**不证明任何行为**——X-16 的第一次修复正是「提示词写对了、测试也过了」却仍然翻车。

## 四、分类规则（启发式，可按明细推翻）

按顺序判定，先命中先归类：

1. `live` —— 函数体内出现 `DEEPSEEK_API_KEY` 判空（真调模型，无 Key 时跳过）
2. `io` —— 调用文件系统（`write_text`/`read_text`/`mkdir`/`rmtree`/`copy2`/`unlink`/`open`…）
3. `integration` —— 触及 `coach.orchestration` 或调用 `run_turn`
4. `contract` —— **没有调用任何被测函数**，但断言里引用了导入的静态名（常量 / 提示词文本）
5. `pure` —— 所有被测调用都落在 `coach.domain` / `coach.config`
6. `behavior` —— 其余（跨 domain 之外的服务调用）
