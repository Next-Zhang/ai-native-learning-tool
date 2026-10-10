"""能力测评相关的确定性规则（原 `assessor.py` 的纯函数部分）。

设计要点：
- LLM 只负责"出题"与"判这一题"；**分数聚合与薄弱点阈值由代码决定**（可解释、可测试、换模型不漂移）。
- 汇总不需要额外 LLM 调用：判定只有三档，聚合是确定性计算。
- 三档分数：mastered=1.0 / partial=0.5 / missing=0.0；薄弱点阈值 score < 0.6。
"""

# 参数（要调就改这里）
MIN_QUESTIONS = 3
MAX_QUESTIONS = 5
WEAK_THRESHOLD = 0.6

VERDICT_SCORES = {
    "mastered": 1.0,
    "partial": 0.5,
    "missing": 0.0,
}

# 模型可能回中文/其它写法，统一归一到三个规范值
VERDICT_ALIASES = {
    "mastered": "mastered", "掌握": "mastered", "完全掌握": "mastered",
    "correct": "mastered", "正确": "mastered", "会": "mastered",
    "partial": "partial", "部分": "partial", "部分掌握": "partial",
    "partially": "partial", "部分正确": "partial",
    "missing": "missing", "未掌握": "missing", "不会": "missing",
    "wrong": "missing", "错误": "missing", "no": "missing", "没回答": "missing",
}


def normalize_plan(questions, goal: str = "") -> list[dict]:
    """清洗测评大纲：去空题、重新编号、截断到 MAX_QUESTIONS；为空时给出兜底题。

    返回 [{"index":1,"topic":"...","difficulty":1}, ...]
    """
    cleaned: list[dict] = []
    for item in questions or []:
        topic = (item.get("topic") or "").strip() if isinstance(item, dict) else str(item).strip()
        if not topic:
            continue
        difficulty = item.get("difficulty", 1) if isinstance(item, dict) else 1
        try:
            difficulty = int(difficulty)
        except (TypeError, ValueError):
            difficulty = 1
        cleaned.append({"topic": topic, "difficulty": max(1, min(5, difficulty))})

    cleaned = cleaned[:MAX_QUESTIONS]

    if not cleaned:
        # 兜底：模型没给出可用题目时，用目标生成三道通用递进题，保证流程能继续
        label = goal or "该技能"
        cleaned = [
            {"topic": f"{label} 基础概念", "difficulty": 1},
            {"topic": f"{label} 常用操作", "difficulty": 2},
            {"topic": f"{label} 综合应用", "difficulty": 3},
        ]

    for position, item in enumerate(cleaned, start=1):
        item["index"] = position
    return cleaned


def verdict_score(verdict: str) -> float:
    """三档判定 -> 分数。"""
    return VERDICT_SCORES.get(verdict, 0.0)


def aggregate_scores(records) -> dict[str, float]:
    """按知识点聚合：同一 topic 的多题取平均分（确定性计算）。"""
    buckets: dict[str, list[float]] = {}
    for record in records or []:
        topic = (record.get("topic") or "").strip()
        if not topic:
            continue
        buckets.setdefault(topic, []).append(verdict_score(record.get("verdict", "missing")))

    scores: dict[str, float] = {}
    for topic, values in buckets.items():
        scores[topic] = round(sum(values) / len(values), 2)
    return scores


def derive_weak_points(scores: dict[str, float], threshold: float = WEAK_THRESHOLD) -> list[str]:
    """薄弱点 = 低于阈值的知识点（按分数升序，便于优先补强）。"""
    weak = [(topic, score) for topic, score in scores.items() if score < threshold]
    weak.sort(key=lambda item: (item[1], item[0]))
    return [topic for topic, _score in weak]


def current_index(progress) -> int:
    """当前该作答的题号（1-based）；已结束返回 0。"""
    if not progress or progress.get("finished"):
        return 0
    return len(progress.get("records", [])) + 1


def is_finished(state) -> bool:
    """是否已答满题量。"""
    progress = state.get("assessment_progress") or {}
    if progress.get("finished"):
        return True
    plan = progress.get("plan") or []
    records = progress.get("records") or []
    return bool(plan) and len(records) >= len(plan)


def finalize(state) -> dict:
    """聚合产出 skill_profile 与 weak_points（纯代码计算，不再调 LLM）。

    v0.18：先把本次测评的分数写成 **evidence**（带来源与序号），再由证据**派生**画像。
    长期记忆只有 evidence 是直接写的（见 @@docs/memory-design.md@@ §5 / I-12）。
    """
    # 局部导入：`memory` 依赖本模块的阈值与薄弱点规则，模块级导入会成环。
    from coach.domain.memory import SOURCE_ASSESSMENT, derive_profile, record_evidence

    progress = state.get("assessment_progress") or {}
    records = progress.get("records") or []

    scores = aggregate_scores(records)
    for topic, score in scores.items():
        record_evidence(state, topic, source=SOURCE_ASSESSMENT,
                        verdict="assessment", score=score)

    profile = derive_profile(state)
    weak_points = derive_weak_points(profile)

    state["skill_profile"] = profile
    state["weak_points"] = weak_points
    progress["finished"] = True
    state["assessment_progress"] = progress

    return {"skill_profile": profile, "weak_points": weak_points}
