"""tool.py —— 给 Agent 用的检索工具（V0.6/V0.7 的 Retrieval Tool）。

职责：
1. should_retrieve()：判断用户这句话要不要查知识库（避免每句话都检索，
   尤其不要在"目标澄清"阶段用教程资料干扰对话）
2. build_context()：检索 top-k 个块，拼成给 LLM 看的【参考资料】文本 + 来源列表
3. format_sources()：把来源列表格式化成一行用于终端展示

设计要点：
- 上下文以“参考资料”形式注入，而不是写进对话历史（历史要保持干净、可控大小）
- 每个块截断到 max_chars_per_chunk，控制注入的 token 量
"""

from rag.retrieve import search

# 问句特征词：出现这些词基本可判定用户在问知识问题
QUESTION_HINTS = (
    "怎么", "如何", "什么", "为什么", "区别", "用法", "是什么", "怎样",
    "哪", "多少", "报错", "错误", "不对", "作用", "含义",
)

# Python 知识关键词：出现这些词说明问题与教程内容相关
# 注意：故意不包含裸的 "python"——"我想学 Python" 属于目标澄清，不该触发检索；
# 真正的知识问题通常会带上具体概念（列表/字典/函数…）或问句特征。
PYTHON_HINTS = (
    "列表", "字典", "元组", "集合", "字符串", "数字", "函数", "类",
    "对象", "异常", "错误", "模块", "文件", "循环", "条件", "装饰器", "lambda",
    "推导式", "迭代", "生成器", "正则", "json", "线程", "进程", "asyncio", "pip",
    "venv", "虚拟环境", "类型注解", "with", "继承", "多态", "封装", "递归",
    "切片", "排序", "格式化", "输入输出", "编码", "运算符", "变量", "注释",
)


def should_retrieve(text: str) -> bool:
    """判断该用户消息是否需要检索知识库。"""
    t = (text or "").strip().lower()
    if len(t) < 4:
        return False
    has_question = ("?" in t or "？" in t) or any(h in t for h in QUESTION_HINTS)
    has_python = any(h in t for h in PYTHON_HINTS)
    return has_question or has_python


def build_context(
    question: str, top_k: int = 5, max_chars_per_chunk: int = 500
) -> tuple[str, list[dict]]:
    """检索并构造参考资料。

    返回 (context_text, sources)：
    - context_text：给 LLM 的参考资料正文（带 [1][2] 编号）
    - sources：编号对应的来源元数据，用于终端展示与引用标注
    """
    results = search(question, top_k=top_k)

    # 同一章节同一小节可能命中多块，只保留分数最高的那一块，避免上下文重复
    picked: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for r in results:
        key = (r["source_url"], r["section"])
        if key in seen:
            continue
        seen.add(key)
        picked.append(r)

    lines: list[str] = []
    sources: list[dict] = []
    for i, r in enumerate(picked, start=1):
        snippet = r["text"][:max_chars_per_chunk].strip()
        lines.append(f"[{i}] 《{r['title']}》/ {r['section']}\n{snippet}")
        sources.append(
            {
                "index": i,
                "title": r["title"],
                "section": r["section"],
                "source_url": r["source_url"],
                "score": r["score"],
            }
        )
    return "\n\n".join(lines), sources


def format_sources(sources: list[dict]) -> str:
    """把来源列表格式化成一行，便于终端打印。"""
    return "；".join(f"[{s['index']}] {s['title']} / {s['section']}" for s in sources)
