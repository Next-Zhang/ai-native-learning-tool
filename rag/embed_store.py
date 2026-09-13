"""embed_store.py —— 把切好的块向量化，写入 Qdrant 本地向量库。

输入：data/rag/chunks.jsonl（chunk.py 的输出）
输出：data/rag/qdrant/（Qdrant 本地嵌入式模式，磁盘持久化，无需 Docker）

流程：
1. 用 rag.embeddings 加载 BGE-M3（首次运行会下载约 2GB 模型到 data/rag/models/bge-m3）
2. 把每一块的 text 向量化为 1024 维
3. 批量 upsert 进 Qdrant collection "runoob_python3"
   - 向量配置：size=1024, distance=Cosine（余弦相似度）
   - payload（元数据）：chunk_id / source_url / title / section / token_count / text
     text 也放进 payload，检索时直接返回原文，无需再回查磁盘

用法（在 App_landing 目录下）：
  python -m rag.embed_store            # 增量/首次入库
  python -m rag.embed_store --force    # 删掉旧 collection 重建（模型已缓存，较快）
"""

import argparse
import json
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
CHUNKS_FILE = BASE_DIR / "data" / "rag" / "chunks.jsonl"
QDRANT_DIR = BASE_DIR / "data" / "rag" / "qdrant"

COLLECTION_NAME = "runoob_python3"
EMBED_MODEL = "BAAI/bge-m3（本地 ONNX）"   # 具体加载逻辑见 rag/embeddings.py
EMBED_DIM = 1024                           # BGE-M3 的输出维度
BATCH_SIZE = 64                            # 每批 embed + upsert 的块数


# ---------------------------------------------------------------------------
# Qdrant 客户端与 collection 管理
# ---------------------------------------------------------------------------

def _client():
    """创建 Qdrant 本地客户端（path= 即本地嵌入式模式，数据落在该目录）。"""
    from qdrant_client import QdrantClient
    return QdrantClient(path=str(QDRANT_DIR))


def ensure_collection(client, force: bool = False) -> None:
    """确保 collection 存在（且维度/距离正确）；force=True 时先删除重建。

    注意：旧 API recreate_collection 已被废弃，官方建议
    collection_exists + delete/create 组合，这里采用新写法。
    """
    from qdrant_client.models import Distance, VectorParams

    exists = client.collection_exists(COLLECTION_NAME)
    if exists and force:
        client.delete_collection(COLLECTION_NAME)
        exists = False

    if not exists:
        client.create_collection(
            COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )
        print(f"已创建 collection: {COLLECTION_NAME} (size={EMBED_DIM}, distance=COSINE)")
    else:
        info = client.get_collection(COLLECTION_NAME)
        print(f"collection 已存在: {COLLECTION_NAME} (现有 {info.points_count} 点)")


# ---------------------------------------------------------------------------
# 主流程：embed + upsert
# ---------------------------------------------------------------------------

def load_chunks(chunks_file: Path = CHUNKS_FILE) -> list[dict]:
    """读取 jsonl 切块文件。"""
    if not chunks_file.exists():
        raise SystemExit(f"未找到 {chunks_file}，请先运行 python -m rag.chunk")
    with chunks_file.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def embed_and_store(force: bool = False, batch_size: int = BATCH_SIZE) -> None:
    """向量化全部块并写入 Qdrant；返回时打印最终点数。"""
    from qdrant_client.models import PointStruct
    from rag import embeddings

    chunks = load_chunks()
    if not chunks:
        raise SystemExit("chunks.jsonl 为空")

    # embeddings.get_embedder() 首次调用会下载约 2GB 模型文件
    print(f"加载 embedding 模型 {EMBED_MODEL}（首次运行会下载约 2GB，请耐心等待）...")
    model = embeddings.get_embedder()
    print("模型加载完成，开始向量化...")

    client = _client()
    ensure_collection(client, force=force)

    texts = [c["text"] for c in chunks]
    total = len(texts)
    start_time = time.time()
    upserted = 0

    for i in range(0, total, batch_size):
        batch_texts = texts[i : i + batch_size]

        # fastembed 的 embed() 返回生成器，产出 numpy 向量
        vectors = [v.tolist() for v in model.embed(batch_texts)]

        points = []
        for j, (chunk, vec) in enumerate(zip(chunks[i : i + batch_size], vectors)):
            points.append(
                PointStruct(
                    id=i + j,                       # 用行号做整数 id，重建可复现
                    vector=vec,
                    payload={
                        "chunk_id": chunk["id"],
                        "source_url": chunk["source_url"],
                        "title": chunk["title"],
                        "section": chunk["section"],
                        "token_count": chunk["token_count"],
                        "text": chunk["text"],
                    },
                )
            )
        client.upsert(COLLECTION_NAME, points=points)
        upserted += len(points)

        elapsed = time.time() - start_time
        speed = upserted / elapsed if elapsed else 0
        remain = (total - upserted) / speed if speed else 0
        print(f"  已写入 {upserted}/{total}  "
              f"({speed:.0f} 块/秒，预计剩余 {remain:.0f}s)")

    count = client.count(COLLECTION_NAME).count
    client.close()
    print(f"\n完成：collection 现有 {count} 个向量")
    print(f"Qdrant 数据目录: {QDRANT_DIR}")


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="向量化 chunks 并写入 Qdrant 本地库")
    parser.add_argument("--force", action="store_true", help="删除旧 collection 后重建")
    parser.add_argument("--batch", type=int, default=BATCH_SIZE, help="每批处理的块数")
    args = parser.parse_args()
    embed_and_store(force=args.force, batch_size=args.batch)


if __name__ == "__main__":
    main()
