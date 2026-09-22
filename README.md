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
├── rag/            # RAG / 知识库（详见下方章节）
│   ├── crawl.py        # 爬虫：抓 runoob Python3 教程 → data/rag/raw/*.json
│   ├── chunk.py        # 切块：raw → data/rag/chunks.jsonl（按 token，≤350）
│   ├── embeddings.py   # 本地 BGE-M3 向量化引擎（onnxruntime，无 torch）
│   ├── embed_store.py  # 向量化并写入 Qdrant 本地库
│   ├── retrieve.py     # 检索：query → top-k（含 recall@k 自检）
│   └── build.py        # 一键管道：crawl → chunk → store
├── data/           # 用户状态 + RAG 产物（均不提交）
│   ├── user_state.json
│   └── rag/        # raw/ chunks.jsonl qdrant/ models/
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
| V0.6 | Tools（代码执行/检索/进度） | 🔸 Retrieval Tool 已实现（rag/tool.py） |
| V0.7 | RAG / 知识库 | ✅ 本地向量库 + Agent 接入完成（recall@5=100%，回答带来源引用） |
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

## 验收测试

- **V0.1**：聊几轮 → `exit` → 重启程序 → 对话历史仍在（`data/user_state.json` 持久化）。

## 许可证

[MIT](./LICENSE)
