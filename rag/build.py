"""build.py —— 一键管道：爬取 → 切块 → 向量化入库。

把 crawl / chunk / embed_store 三步串成一个命令，日常重建语料库时
不用手动逐个跑。每一步实际复用对应模块的 main()（子进程方式调用），
保证与单独运行行为完全一致、输出实时可见、出错即停。

用法（在 App_landing 目录下）：
  python -m rag.build               # 全流程：crawl(跳过已有) → chunk → store
  python -m rag.build --rebuild     # 强制重建向量库（清空旧 collection 后重嵌入）
  python -m rag.build --step crawl --limit 3    # 只跑某一阶段，配合爬虫限数试跑
"""

import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _run_module(module: str, *args: str) -> None:
    """以子进程运行 python -m <module>，保证与手动运行行为一致。"""
    cmd = [sys.executable, "-m", module, *args]
    print(f"\n===== 执行: {' '.join(cmd)} =====")
    proc = subprocess.run(cmd, cwd=str(BASE_DIR))
    if proc.returncode != 0:
        raise SystemExit(f"✗ 步骤 {module} 失败（exit {proc.returncode}），已终止管道")


def _collection_count() -> int:
    """只读检查当前 collection 已有多少向量（不加载模型，很快）。"""
    from qdrant_client import QdrantClient

    try:
        client = QdrantClient(path=str(BASE_DIR / "data" / "rag" / "qdrant"))
        info = client.get_collection("runoob_python3")
        client.close()
        return info.points_count
    except Exception:                       # 库不存在等
        return 0


# ---------------------------------------------------------------------------
# 管道
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="一键构建 runoob Python3 向量库")
    parser.add_argument("--step", choices=["all", "crawl", "chunk", "store"],
                        default="all", help="要执行的阶段（默认全部）")
    parser.add_argument("--rebuild", action="store_true",
                        help="store 阶段强制删除旧 collection 重建")
    parser.add_argument("--limit", type=int, default=0,
                        help="crawl 阶段最多抓取前 N 章（0 = 全部）")
    args = parser.parse_args()

    step = args.step

    if step in ("all", "crawl"):
        crawl_args = [f"--limit {args.limit}"] if args.limit > 0 else []
        _run_module("rag.crawl", *crawl_args)

    if step in ("all", "chunk"):
        _run_module("rag.chunk")

    if step in ("all", "store"):
        if args.rebuild:
            _run_module("rag.embed_store", "--force")
        else:
            count = _collection_count()
            if count > 0:
                print(f"\n向量库已有 {count} 个点，跳过 store 阶段（重建请加 --rebuild）")
            else:
                _run_module("rag.embed_store")

    print("\n===== 管道完成 =====")
    print("检索示例:   python -m rag.retrieve \"Python 列表\"")
    print("质量自检:   python -m rag.retrieve --selfcheck")


if __name__ == "__main__":
    main()
