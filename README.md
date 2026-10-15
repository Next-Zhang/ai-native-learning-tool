# AI Native Learning Tool

一个面向持续学习的 AI 教练：围绕能力目标制定路线图，把每次学习落实为任务，记录练习表现，支持跨次接续、补强与复验。

当前为单用户、本机 CLI 原型，软件版本 v0.18。持续学习是当前产品方向；完整复验、回顾、目标收尾及部分可靠性机制仍待交付。
实现状态见 [交付清单](docs/delivery.md)，验证边界见 [验证报告](docs/validation.md)。

## 文档入口

| 想了解什么 | 文档 |
|---|---|
| 全部文档如何分工 | [文档导航](docs/README.md) |
| 产品名词、状态与编号 | [术语与文档规范](docs/terminology.md) |
| 产品目标、用户流程与验收要求 | [PRD](docs/PRD.md) |
| 实际 Agent 架构与代码职责 | [当前架构](docs/architecture.md) |
| 为什么这样设计 | [架构决策](docs/decisions.md) |
| 当前能力与下一步 | [交付清单](docs/delivery.md) |
| 测试证据与持续学习验证 | [验证报告](docs/validation.md) |
| 验收案例与现有测试/样本的对应关系 | [验收覆盖映射](docs/acceptance-coverage.md) |
| 加能力、测试、指标、RAG、重置工具 | [开发指南](docs/development.md) |

## 快速开始

Windows / PowerShell。项目元数据声明 Python >=3.10；其他 Python 版本的实际兼容性以验证结果为准。

```powershell
cd App_landing
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
$env:DEEPSEEK_API_KEY = "你的 API Key"
python app.py
```

核心依赖为 openai 与 pydantic。requirements.txt 当前还包含可选 RAG 的依赖；
只运行学习闭环时使用上面的核心安装方式。需 RAG 时见开发指南。

也可使用 learning-coach 或 python -m coach 入口。
凭据从环境变量读取。缺 Key 时 CLI 会退出；测试及库导入不必依赖真实 Key。

## 使用与数据

- 输入自然语言目标，与教练完成澄清、测评、计划确认、任务和验收。
- exit / quit：退出，已保存的状态用于下次接续。
- /rag on、/rag off：临时开启或关闭本地检索，默认关闭。
- /reset：确认后清空近期原文和归档；**当前摘要仍保留并可能继续使用**，详见 D-03。
- /reset all：确认后重置学习状态并备份；**备份、指标和 trace 不随之删除**。

状态保存在 data/user_state.json。CLI 开启本机指标与 trace；trace 包含输入和回复。
学习内容会发送至模型 API；供应商的数据留存规则尚待核实。
重置进度不等于彻底删除个人数据，相关完善项见交付清单。

## 代码入口

```text
app.py
coach/
  cli/              终端交互
  orchestration/    单轮执行与能力调度
  domain/           状态机、契约、规则、游标与证据
  services/         模型用例及状态更新
  prompts/          提示词
  llm/              统一模型调用
  storage/          状态读写与重置
  metrics/          指标
  observability/    单轮 trace
rag/                可选本地知识库
tests/              回归测试与测试审计
evals/              非确定性判定评测
docs/               产品、架构、交付、验证与历史
```

当前有已确认的判定、清理和授权缺口。代码存在及测试数量不作为学习效果或发布准备程度的证明。
