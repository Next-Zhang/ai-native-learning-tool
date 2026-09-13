"""crawl.py —— 抓取 runoob Python3 教程并解析成结构化 JSON。

爬虫分三步：
1. 从教程目录页收集全部章节链接（/python3/*.html，去重保序）
2. 逐个下载章节页 HTML（带 UA、限速、失败重试，尊重对方站点）
3. 用 BeautifulSoup 定位正文容器 div.article-body，
   按顺序把 小节标题(h2/h3/h4) / 正文段落(p) / 代码块(pre) 等
   整理成 segments 列表，保存为 JSON。

输出文件：data/rag/raw/<章节名>.json，格式如下：
{
  "source_url": "https://www.runoob.com/python3/python3-list.html",
  "title": "Python3 列表",
  "segments": [
    {"section": "Python3 列表",      "type": "text", "content": "序列是 Python 中最基本的数据结构..."},
    {"section": "访问列表中的值",     "type": "code", "content": "list1 = ['red', 'green']..."},
    ...
  ]
}

"section" 记录该段所属的小节标题，供后续切块时作为上下文前缀，
保证向量片段自带章节归属。

用法（在 App_landing 目录下）：
  python -m rag.crawl            # 抓取全部章节（已存在的不重复抓）
  python -m rag.crawl --limit 3  # 只抓前 3 章，快速验证
  python -m rag.crawl --list-only   # 只看会抓哪些章节，不实际下载
  python -m rag.crawl --force    # 忽略已有文件，重新抓取
"""

import argparse
import json
import time
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------

# rag/ 的上一级就是 App_landing/（state.py 也用同样的写法，保证从任何目录启动都对）
BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "rag" / "raw"

# Python3 教程目录页：页面上列出了所有章节的链接
CATALOG_URL = "https://www.runoob.com/python3/python3-tutorial.html"
# 只收 /python3/ 目录下的页面，天然排除其他教程（/python/、/quiz/ 等）
CHAPTER_PATH_PREFIX = "/python3/"
CHAPTER_SUFFIX = ".html"

# 尊重对方站点：伪装成正常浏览器 + 每次请求之间限速
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    )
}

# 一个会话复用连接，比每次新建 requests.get 更快
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ---------------------------------------------------------------------------
# 1. 收集章节链接
# ---------------------------------------------------------------------------

def collect_chapter_urls(catalog_url: str = CATALOG_URL) -> list[str]:
    """打开目录页，收集所有 /python3/ 目录下的章节 URL（去重、保持顺序）。"""
    html = fetch_html(catalog_url)
    soup = BeautifulSoup(html, "lxml")

    urls: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        # href 可能是相对路径（如 python3-list.html），拼成完整 URL
        full = urllib.parse.urljoin(catalog_url, a["href"].strip())
        path = urllib.parse.urlparse(full).path
        if not (path.startswith(CHAPTER_PATH_PREFIX) and path.endswith(CHAPTER_SUFFIX)):
            continue
        if full not in seen:
            seen.add(full)
            urls.append(full)
    return urls


# ---------------------------------------------------------------------------
# 2. 下载页面
# ---------------------------------------------------------------------------

def fetch_html(url: str, retries: int = 3, timeout: int = 20) -> str:
    """下载一个页面并返回 HTML 文本；失败自动重试，重试耗尽则抛异常。"""
    for attempt in range(1, retries + 1):
        try:
            resp = SESSION.get(url, timeout=timeout)
            resp.raise_for_status()
            # runoob 页面是 UTF-8；用 apparent_encoding 兜底更稳
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except (requests.RequestException, ValueError) as exc:
            if attempt == retries:
                raise RuntimeError(f"下载失败（已重试 {retries} 次）: {url}\n  原因: {exc}") from exc
            time.sleep(attempt)  # 退避：第 1 次等 1s，第 2 次等 2s...


# ---------------------------------------------------------------------------
# 3. 解析页面为结构化 segments
# ---------------------------------------------------------------------------

def _normalize_text(raw: str) -> str:
    """去掉多余空行与首尾空白，保留内部换行。"""
    lines = [ln.strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln]          # 去掉空行
    return "\n".join(lines)


def parse_chapter(html: str, source_url: str) -> dict:
    """从一章的 HTML 解析出 {"source_url", "title", "segments"}。"""
    soup = BeautifulSoup(html, "lxml")
    container = soup.select_one("div.article-body")
    if container is None:
        raise ValueError(f"未找到正文容器 div.article-body: {source_url}")

    # 章节标题 = 正文容器里的第一个 <h1>；兜底用 <title>（去掉“| 菜鸟教程”尾巴）
    h1 = container.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
    else:
        page_title = soup.title.get_text(" ", strip=True) if soup.title else source_url
        title = page_title.split("|")[0].strip()

    # 逐个元素归类；section 记录“当前所属小节标题”
    capture_tags = ["h1", "h2", "h3", "h4", "p", "pre", "ul", "ol", "table"]
    segments: list[dict] = []
    section = title
    for tag in container.find_all(capture_tags):
        if tag.name == "h1":
            # 第一个 h1 就是章节标题，已记入 title，跳过
            continue
        if tag.name in ("h2", "h3", "h4"):
            heading = tag.get_text(" ", strip=True)
            if heading:
                section = heading          # 之后的内容都属于这个小节
            continue

        # 若外层元素内部还嵌套着我们同样会捕获的标签（如 <p> 里再套 <p>），
        # 跳过外层，只保留叶子内容，避免父子两级各存一次造成重复。
        if tag.find(capture_tags):
            continue

        if tag.name == "pre":
            # 代码块：保留原样（不折叠行内空白），get_text 即代码原文
            content = _normalize_text(tag.get_text())
            if content:
                segments.append({"section": section, "type": "code", "content": content})
            continue

        # p / ul / ol / table：正文类内容，压缩行内空白为普通文本
        text = tag.get_text("\n", strip=True)
        text = _normalize_text(text)
        if len(text) < 2:                    # 丢弃纯噪声（按钮、空内容等）
            continue
        segments.append({"section": section, "type": "text", "content": text})

    return {"source_url": source_url, "title": title, "segments": segments}


# ---------------------------------------------------------------------------
# 保存与文件名工具
# ---------------------------------------------------------------------------

def slug_from_url(url: str) -> str:
    """从 URL 取最后一段文件名作为存盘 slug，如 .../python3-list.html -> python3-list"""
    path = urllib.parse.urlparse(url).path
    name = path.rsplit("/", 1)[-1]
    return name.removesuffix(CHAPTER_SUFFIX)


def save_chapter(data: dict) -> Path:
    """把一章的解析结果写入 data/rag/raw/<slug>.json，返回文件路径。"""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = RAW_DIR / f"{slug_from_url(data['source_url'])}.json"
    out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="抓取 runoob Python3 教程并保存为结构化 JSON")
    parser.add_argument("--limit", type=int, default=0, help="最多抓取前 N 章（0 = 全部）")
    parser.add_argument("--delay", type=float, default=0.8, help="两次请求之间的间隔秒数")
    parser.add_argument("--force", action="store_true", help="忽略已存在的 JSON，重新抓取")
    parser.add_argument("--list-only", action="store_true", help="只打印章节清单，不下载")
    args = parser.parse_args()

    print("① 正在读取教程目录页，收集章节链接 ...")
    urls = collect_chapter_urls()
    print(f"   共发现 {len(urls)} 个章节")

    if args.list_only:
        for u in urls:
            print("   ", u)
        return

    if args.limit > 0:
        urls = urls[: args.limit]

    saved = skipped = failed = 0
    for i, url in enumerate(urls, start=1):
        slug = slug_from_url(url)
        out_file = RAW_DIR / f"{slug}.json"
        if out_file.exists() and not args.force:
            skipped += 1
            print(f"[{i}/{len(urls)}] 跳过（已存在）: {slug}")
            continue

        try:
            html = fetch_html(url)
            data = parse_chapter(html, url)
            save_chapter(data)
            saved += 1
            print(f"[{i}/{len(urls)}] 已保存: {data['title']} "
                  f"({len(data['segments'])} 段) -> {out_file.name}")
        except Exception as exc:            # noqa: BLE001 —— 单章失败不影响整体
            failed += 1
            print(f"[{i}/{len(urls)}] 失败: {url}\n   原因: {exc}")

        time.sleep(args.delay)              # 限速，避免给目标站点压力

    print(f"\n完成：保存 {saved}，跳过 {skipped}，失败 {failed}")
    print(f"文件目录: {RAW_DIR}")


if __name__ == "__main__":
    main()
