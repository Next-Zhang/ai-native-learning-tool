"""retrieve.py —— 向量检索：给定问题，返回最相关的知识块。

流程：
1. 用与入库相同的 BGE-M3 引擎把查询向量化（query embedding）
2. 到 Qdrant 按余弦相似度找 top-k 个块
3. 返回每个块的分数和元数据（来源章节 / 小节 / 原文）

内置自检 --selfcheck：
- 准备一组"明知答案在某章"的查询
- 检查该章是否出现在检索结果 top-k 里（recall@k）
- 这是衡量切块 + embedding 质量的可量化指标

用法（在 App_landing 目录下）：
  python -m rag.retrieve "字典的 get 方法有什么作用"      # 普通检索
  python -m rag.retrieve "列表" -k 3                      # 指定返回条数
  python -m rag.retrieve --selfcheck                      # 检索质量自检
"""

import argparse
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
QDRANT_DIR = BASE_DIR / "data" / "rag" / "qdrant"
COLLECTION_NAME = "runoob_python3"

# 自检查询集：每一条 (问题, 应该命中的章节文件名)
SELFCHECK_QUERIES = [
    ("Python 列表如何通过下标访问元素", "python3-list"),
    ("字典的 get 方法默认返回什么", "python3-dictionary"),
    ("元组和列表有什么区别", "python3-tuple"),
    ("lambda 匿名函数怎么写", "python-lambda"),
    ("装饰器是什么，怎么用", "python-decorators"),
    ("Python 类怎么定义，怎么继承", "python3-class"),
    ("try except 怎么处理异常", "python3-errors-execptions"),
    ("列表推导式的语法", "python-comprehensions"),
    ("json.dumps 和 json.loads 的用法", "python3-json"),
    ("怎么用 threading 创建线程", "python3-multithreading"),
    ("字符串格式化 %s 和 format", "python3-string"),
    ("for 循环怎么遍历字典", "python3-loop"),
]


# ---------------------------------------------------------------------------
# 检索核心
# ---------------------------------------------------------------------------

def search(query: str, top_k: int = 5) -> list[dict]:
    """向量化查询并在 Qdrant 里检索，返回按相似度降序的结果列表。"""
    from qdrant_client import QdrantClient
    from rag import embeddings

    # 用与入库完全相同的引擎向量化查询 —— 保证向量空间一致
    model = embeddings.get_embedder()
    query_vector = next(model.embed([query]))       # (1024,)

    client = QdrantClient(path=str(QDRANT_DIR))
    resp = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector.tolist(),
        limit=top_k,
        with_payload=True,
    )
    client.close()

    results = []
    for point in resp.points:
        p = point.payload or {}
        results.append(
            {
                "score": round(point.score, 4),
                "chunk_id": p.get("chunk_id", ""),
                "source_url": p.get("source_url", ""),
                "title": p.get("title", ""),
                "section": p.get("section", ""),
                "text": p.get("text", ""),
            }
        )
    return results


def print_results(results: list[dict]) -> None:
    """以可读格式打印检索结果。"""
    for i, r in enumerate(results, start=1):
        source = r["source_url"].rstrip("/").rsplit("/", 1)[-1]
        print(f"\n[{i}] score={r['score']}  {r['title']} / {r['section']}")
        print(f"    来源: {source}")
        # 只打印前 120 个字符，方便一眼判断相关性
        snippet = r["text"].replace("\n", " ")[:120]
        print(f"    片段: {snippet}...")


# ---------------------------------------------------------------------------
# 检索质量自检（recall@k）
# ---------------------------------------------------------------------------

def _src_slug(url: str) -> str:
    """从 source_url 取文件名（去掉 .html），用于与期望章节名比较。"""
    return url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".html")


def selfcheck(top_k: int = 5) -> None:
    """对内置查询集跑检索，统计“正确答案所在章出现在 top-k”的比例。"""
    print(f"开始检索自检（{len(SELFCHECK_QUERIES)} 条查询, top_k={top_k}）...\n")
    hits = 0
    for query, expect_slug in SELFCHECK_QUERIES:
        results = search(query, top_k=top_k)
        # 记录每个目标命中在第几位（1 表示第一命中就是目标章）
        slugs = [_src_slug(r["source_url"]) for r in results]
        rank = (slugs.index(expect_slug) + 1) if expect_slug in slugs else None
        if rank is not None:
            hits += 1
        top = results[0] if results else {}
        status = "PASS" if rank else "FAIL"
        detail = f"命中第 {rank} 位" if rank else "未命中"
        print(f"[{status}] 「{query}」 -> 期望 {expect_slug}（{detail}）| 第一命中 {top.get('title', '')}")
        if rank is None:
            # 展示实际命中的来源，便于分析为什么没召回
            for r in results[:3]:
                print(f"      实际: {_src_slug(r['source_url'])} (score={r['score']})")

    recall = hits / len(SELFCHECK_QUERIES)
    print(f"\nrecall@{top_k} = {hits}/{len(SELFCHECK_QUERIES)} = {recall:.0%}")


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="从 Qdrant 向量库检索相关知识块")
    parser.add_argument("query", nargs="?", help="检索的问题文本")
    parser.add_argument("-k", "--top-k", type=int, default=5, help="返回条数")
    parser.add_argument("--selfcheck", action="store_true", help="运行检索质量自检")
    args = parser.parse_args()

    if args.selfcheck:
        selfcheck(top_k=args.top_k)
    elif args.query:
        print(f"查询: {args.query}\n")
        print_results(search(args.query, top_k=args.top_k))
    else:
        parser.error("需要提供 query，或使用 --selfcheck")


if __name__ == "__main__":
    main()
