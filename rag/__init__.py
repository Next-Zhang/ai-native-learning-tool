"""rag: 从 runoob Python3 教程构建本地向量库（V0.7 RAG 基础设施）。

模块划分：
- crawl.py       爬取教程网页 -> data/rag/raw/*.json（结构化文本）
- chunk.py       文本切块（按 token 计数，保留小节上下文）
- embed_store.py 向量化并写入 Qdrant 本地库
- retrieve.py    相似度检索
- build.py       一键执行完整流程
"""
