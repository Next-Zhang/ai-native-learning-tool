"""assessor.py —— V0.3b 能力测评（出题 → 跨轮作答 → 判定 → 产出画像）。

流程：
1. ensure_plan()      进入测评阶段时生成 3~5 道由易到难的大纲，写入 state["assessment_progress"]
2. record_answer()    每轮把「上一轮教练的问题 + 本轮用户回答」交给 LLM 判定
                      （mastered / partial / missing），追加到 progress["records"]
3. is_finished()      答满题量即结束
4. finalize()         在**代码里**按知识点聚合平均分 -> skill_profile，并按阈值产出 weak_points

设计要点（对应用户确认的方案）：
- LLM 只负责"出题"和"判这一题"，**分数聚合与薄弱点阈值由代码决定**（可解释、可测试、换模型不漂移）
- 汇总不需要额外的 LLM 调用：判定只有三档，聚合是确定性计算
- 三档分数：mastered=1.0 / partial=0.5 / missing=0.0
- 薄弱点阈值：score < 0.6

用法：
    from assessor import ensure_plan, record_answer, is_finished, finalize
"""

import copy
import json
import re

from pydantic import BaseModel, field_validator

# ---------------------------------------------------------------------------
# 参数（以后要调就改这里）
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

class AssessmentQuestion(BaseModel):
    index: int = 0
    topic: str = ""
    difficulty: int = 1


class AssessmentPlan(BaseModel):
    questions: list[AssessmentQuestion] = []


class AnswerRecord(BaseModel):
    index: int
    topic: str = ""
    answer: str = ""
    verdict: str = "missing"
    note: str = ""

    @field_validator("verdict", mode="before")
    @classmethod
    def _normalize_verdict(cls, value):
        key = str(value or "").strip().lower()
        return VERDICT_ALIASES.get(key, "missing")

    @field_validator("answer", "note", mode="before")
    @classmethod
    def _clean_text(cls, value):
        if isinstance(value, str):
            return value.strip()
        return "" if value is None else str(value)


# ---------------------------------------------------------------------------
# 纯函数：归一化、聚合、阈值（这些是测试重点）
# ---------------------------------------------------------------------------

def normalize_plan(questions, goal: str = "") -> list[dict]:
    """清洗大纲：去空题、重新编号、截断到 MAX_QUESTIONS；为空时给出兜底题。

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


def describe_progress(state) -> str:
    """给教练看的测评进度（用于注入对话，确保问对题）。"""
    progress = state.get("assessment_progress") or {}
    plan = progress.get("plan") or []
    if not plan:
        return ""
    records = progress.get("records") or []
    lines = [f"- 测评进度：第 {len(records) + 1}/{len(plan)} 题"]
    index = current_index(progress)
    if index and index <= len(plan):
        question = plan[index - 1]
        lines.append(f"- 本题目知识点：{question.get('topic', '')}")
    if records:
        done = "、".join(
            f"第{r.get('index')}题({r.get('topic')})={r.get('verdict')}" for r in records
        )
        lines.append(f"- 已记录判定：{done}")
    lines.append("- 请只针对当前这道题提问或简短反馈，不要跳到后面题目或给完整计划")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM 调用（惰性客户端，便于无 Key 时跑纯函数测试）
# ---------------------------------------------------------------------------

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

        _client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    return _client


PLAN_SYSTEM_PROMPT = """
你是能力测评设计者。根据用户的学习目标与当前水平，设计 3~5 道**由易到难的实际任务**，
用于测量真实掌握程度（不依赖用户自评）。

只输出 JSON：
{"questions":[{"topic":"知识点（要具体，如'列表切片'、'函数参数'）","difficulty":1},...]}

规则：
- 题目数量 3~5 道；用户水平越高，题目越少。
- difficulty 为 1~5 的整数，按题目顺序递增。
- topic 必须具体到可判定的知识点，不要写“Python”这种大颗粒。
- 覆盖该目标最关键的知识点，不要偏题。
- 只输出 JSON，不要解释。
""".strip()

JUDGE_SYSTEM_PROMPT = """
你是严格的测评判卷人。根据【本次题目】和【用户的回答】给出判定。

只输出 JSON：
{"verdict":"mastered|partial|missing","answer":"用户回答的要点摘录","note":"一句话判定理由"}

判定标准：
- mastered：完全正确，或思路完整、结论正确。
- partial：部分正确、有小错、思路不完整。
- missing：没有作答、答非所问、明确表示不会。
- 用户只说“我会了 / 我懂了”但没有实际作答，判 missing。
- 只输出 JSON，不要解释。
""".strip()


def _json_call(system_prompt: str, user_content: str) -> dict:
    """一次 JSON 模式调用，返回解析后的 dict；失败抛异常由调用方兜底。"""
    response = _get_client().chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(response.choices[0].message.content or "{}")


# ---------------------------------------------------------------------------
# 对外流程函数
# ---------------------------------------------------------------------------

def ensure_plan(state) -> bool:
    """还没有大纲就生成一份并写入 state。返回是否新生成。"""
    progress = state.get("assessment_progress") or {}
    if progress.get("plan"):
        return False

    goal = state.get("learning_goal") or "Python"
    level = state.get("current_level") or "未知"
    minutes = state.get("daily_minutes")
    deadline = state.get("target_date")

    user_content = (
        f"学习目标：{goal}\n当前水平：{level}\n"
        f"每天可投入：{minutes} 分钟\n期望期限：{deadline}\n"
        f"请设计 {MIN_QUESTIONS}~{MAX_QUESTIONS} 道测评题。"
    )

    try:
        data = _json_call(PLAN_SYSTEM_PROMPT, user_content)
        questions = normalize_plan(data.get("questions"), goal=goal)
    except Exception as exc:                      # noqa: BLE001 —— 出题失败必须有兜底
        print(f"[测评出题失败，已使用兜底大纲] {type(exc).__name__}: {exc}")
        questions = normalize_plan([], goal=goal)

    state["assessment_progress"] = {
        "plan": questions,
        "records": [],
        "finished": False,
    }
    return True


def record_answer(state, user_input: str, coach_reply: str) -> AnswerRecord | None:
    """记录当前这道题的作答与判定。没有进行中的题目时返回 None。

    注意：调用方应在“题目是上一轮提出的”情况下调用（首次生成大纲那一轮不记录）。
    """
    progress = state.get("assessment_progress") or {}
    plan = progress.get("plan") or []
    records = progress.get("records") or []
    index = current_index(progress)
    if not index or index > len(plan):
        return None

    question = plan[index - 1]
    user_content = (
        f"【本次题目】知识点：{question.get('topic', '')}\n"
        f"教练的原话：\n{coach_reply}\n\n"
        f"【用户的回答】\n{user_input}"
    )

    try:
        data = _json_call(JUDGE_SYSTEM_PROMPT, user_content)
    except Exception as exc:                      # noqa: BLE001 —— 判定失败保守记为 missing
        print(f"[测评判定失败，按 missing 记录] {type(exc).__name__}: {exc}")
        data = {"verdict": "missing", "answer": "", "note": "判定调用失败"}

    record = AnswerRecord(
        index=index,
        topic=question.get("topic", ""),
        answer=data.get("answer", ""),
        verdict=data.get("verdict", "missing"),
        note=data.get("note", ""),
    )
    records.append(record.model_dump())
    progress["records"] = records
    if len(records) >= len(plan):
        progress["finished"] = True
    state["assessment_progress"] = progress
    return record


def finalize(state) -> dict:
    """聚合产出 skill_profile 与 weak_points（纯代码计算，不再调 LLM）。"""
    progress = state.get("assessment_progress") or {}
    records = progress.get("records") or []

    scores = aggregate_scores(records)
    weak_points = derive_weak_points(scores)

    state["skill_profile"] = scores
    state["weak_points"] = weak_points
    progress["finished"] = True
    state["assessment_progress"] = progress

    return {"skill_profile": scores, "weak_points": weak_points}
