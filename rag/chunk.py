"""chunk.py —— 把抓取好的章节 JSON 切成适合 embedding 的文本块。

输入：data/rag/raw/*.json（crawl.py 的输出，见其 docstring）
输出：data/rag/chunks.jsonl，每行一个块：
{
  "id": "python3-list#0001",
  "source_url": "https://www.runoob.com/python3/python3-list.html",
  "title": "Python3 列表",
  "section": "访问列表中的值",
  "text": "<正文>",
  "token_count": 217
}

切块规则（与 embedding 模型容量对齐）：
- 先用 bge-large-zh-v1.5 自己的 tokenizer 统计 token 数（离线时按字符数保守估算）
- 每个小节先聚合为整段文本（小节标题在开头，块自带上下文）
- 单块目标 300 token；小节超过 300 token 时用滑动窗口切：
  窗口每次前进 = 300 - 50 = 250 token（相邻块重叠 50 token），
  因此任意一块的实际 token 数 ≤ 300 + 50 = 350 < 模型上限 512

用法（在 App_landing 目录下）：
  python -m rag.chunk                    # 全量切块，输出 data/rag/chunks.jsonl
  python -m rag.chunk --target 300 --overlap 50
"""

import argparse
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径与切块参数
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "rag" / "raw"
CHUNKS_FILE = BASE_DIR / "data" / "rag" / "chunks.jsonl"

# 与 embedding 模型同源的 tokenizer（切块计数必须和向量化用同一套 token 口径）
TOKENIZER_NAME = "BAAI/bge-large-zh-v1.5"

# 切块参数：目标块大小 / 相邻块重叠 / 窗口最大跨度 = target + overlap
TARGET_TOKENS = 300
OVERLAP_TOKENS = 50


# ---------------------------------------------------------------------------
# token 计数：优先 bge 同源 tokenizer，离线时退化为字符数保守估算
# ---------------------------------------------------------------------------

_tokenizer = None  # 惰性加载，只加载一次


def _load_tokenizer():
    """加载 bge-large-zh 的 tokenizer（从 HuggingFace 下载 tokenizer.json 并缓存）。"""
    try:
        from tokenizers import Tokenizer
        return Tokenizer.from_pretrained(TOKENIZER_NAME)
    except Exception:
        # 离线或下载失败：返回 None，走保守估算
        return None


def count_tokens(text: str) -> int:
    """统计一段文本的 token 数。

    在线时用 bge 同源 tokenizer，精确；离线时用 len(text) 估算——
    对中文而言真实 token 数 ≤ 字符数，因此估算只会偏大、不会超限（安全方向）。
    """
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = _load_tokenizer()
    if _tokenizer is not None:
        return len(_tokenizer.encode(text).ids)
    return len(text)


# ---------------------------------------------------------------------------
# 长文本切块：滑动窗口，按 token 预算找边界
# ---------------------------------------------------------------------------

def _prefix_cut(text: str, budget: int) -> int:
    """返回最大的位置 x，使 tokens(text[:x]) <= budget。

    原理：token 数随文本长度单调不减，因此可以用二分查找最后一个合法切点。
    """
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count_tokens(text[:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    # 兜底：即使 1 个字符都超预算（极端情况），也要推进，避免死循环
    return max(lo, min(1, len(text)))


def _tail_chars(text: str, budget: int) -> int:
    """返回 text 末尾最长后缀的字符数，使该后缀的 token 数 <= budget。

    实现：把 text 反转后做前缀二分，再把结果换算回原字符串的“尾部字符数”。
    """
    return _prefix_cut(text[::-1], budget)


def split_text(text: str, target: int = TARGET_TOKENS, overlap: int = OVERLAP_TOKENS) -> list[str]:
    """把一段超过预算的长文本切成重叠块列表。

    每个新窗口的起点会“回退”到上一块末尾，保留 overlap 个 token 的上下文，
    避免检索时跨块的内容被拦腰截断而找不到。
    """
    if count_tokens(text) <= target:
        return [text]

    chunks: list[str] = []
    n = len(text)
    start = 0
    while start < n:
        # 从 start 找能容纳 target 个 token 的最远切点 end
        end = start + _prefix_cut(text[start:], target)
        chunks.append(text[start:end])
        if end >= n:
            break
        # 下一块起点 = end - (上一块末尾 overlap 个 token 所占的字符数)
        tail = _tail_chars(text[start:end], overlap)
        next_start = end - tail
        if next_start <= start:            # 防止不前进导致死循环
            next_start = min(n, start + 1)
        start = next_start
    return chunks


# ---------------------------------------------------------------------------
# 章节 JSON -> 块列表
# ---------------------------------------------------------------------------

def chapter_to_chunks(chapter: dict) -> list[dict]:
    """把一章（crawl.py 的输出结构）切成一串带元数据的块。"""
    # 1) 按 section 连续聚合：同一小节的内容拼在一起（标题在最前）
    groups: list[dict] = []
    current: dict | None = None
    for seg in chapter["segments"]:
        sec = seg.get("section") or chapter["title"]
        if current is None or current["section"] != sec:
            current = {"section": sec, "parts": []}
            groups.append(current)
        current["parts"].append(seg["content"])

    # 2) 每个小节：标题 + 内容 -> 文本；超过预算的用滑动窗口切
    chunks: list[dict] = []
    idx = 0
    for g in groups:
        body = g["section"] + "\n" + "\n".join(p for p in g["parts"] if p)
        if not body:
            continue
        for piece in split_text(body):
            idx += 1
            chunks.append(
                {
                    "id": f"{_slug(chapter['source_url'])}#{idx:04d}",
                    "source_url": chapter["source_url"],
                    "title": chapter["title"],
                    "section": g["section"],
                    "text": piece,
                    "token_count": count_tokens(piece),
                }
            )
    return chunks


def _slug(url: str) -> str:
    """从 URL 取最后一段文件名（无扩展名），用于生成可读的块 id。"""
    return url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".html")


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="把 raw 章节 JSON 切成向量块")
    parser.add_argument("--target", type=int, default=TARGET_TOKENS, help="单块目标 token 数")
    parser.add_argument("--overlap", type=int, default=OVERLAP_TOKENS, help="相邻块重叠 token 数")
    parser.add_argument("--output", type=Path, default=CHUNKS_FILE, help="输出 jsonl 文件路径")
    args = parser.parse_args()

    if not RAW_DIR.exists():
        raise SystemExit(f"未找到 raw 目录 {RAW_DIR}，请先运行 python -m rag.crawl")

    files = sorted(RAW_DIR.glob("*.json"))
    if not files:
        raise SystemExit(f"{RAW_DIR} 下没有 JSON，请先运行 python -m rag.crawl")

    print(f"正在切块 {len(files)} 章 ...")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    total_chunks = 0
    with args.output.open("w", encoding="utf-8") as f:
        for i, file in enumerate(files, start=1):
            chapter = json.loads(file.read_text(encoding="utf-8"))
            chunks = chapter_to_chunks(chapter)
            total_chunks += len(chunks)
            for c in chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
            if i <= 5 or i % 20 == 0:
                print(f"[{i}/{len(files)}] {file.stem}: {len(chunks)} 块")

    print(f"\n完成：共 {total_chunks} 块 -> {args.output}")
    print(f"（参数：target={args.target} token，overlap={args.overlap} token）")


if __name__ == "__main__":
    main()
