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
├── app.py          # CLI 主循环
├── agent.py        # LLM 调用 + 教练 System Prompt
├── config.py       # DeepSeek 配置（API Key 从环境变量读取）
├── state.py        # 状态持久化（JSON）
├── data/           # 用户状态数据（不提交）
│   └── .gitkeep
└── .gitignore
```

## 路线图

| 版本 | 内容 | 状态 |
|---|---|---|
| V0.01 | DeepSeek 基础聊天（API/SDK/CLI） | ✅ 已完成 |
| V0.1 | 持久化 Agent State（重启可续） | ✅ 已完成 |
| V0.2 | 结构化用户画像（LLM 抽取 → 状态） | 进行中 |
| V0.3 | Agent 状态机（含能力测评） | 待开始 |
| V0.4 | Human-in-the-loop | 待开始 |
| V0.5 | Evaluation（学习效果评估） | 待开始 |
| V0.6 | Tools（代码执行/检索/进度） | 后续 |
| V0.7 | RAG / 知识库 | 后续 |
| V1.0 | Web MVP | 后续 |

## 验收测试

- **V0.1**：聊几轮 → `exit` → 重启程序 → 对话历史仍在（`data/user_state.json` 持久化）。

## 许可证

[MIT](./LICENSE)
