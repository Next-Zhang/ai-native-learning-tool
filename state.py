import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
STATE_FILE = DATA_DIR / "user_state.json"


# 四项必须齐全才能进入能力测评（V0.3 状态机的守卫）
PROFILE_FIELDS = ("learning_goal", "current_level", "daily_minutes", "target_date")

STAGE_GOAL_CLARIFICATION = "goal_clarification"
STAGE_ASSESSMENT = "assessment"


DEFAULT_STATE = {
    "learning_goal": None,
    "current_level": None,
    "daily_minutes": None,
    "target_date": None,

    "current_stage": "goal_clarification",

    "skill_profile": {},
    "weak_points": [],

    "current_plan": None,
    "today_task": None,

    "conversation_history": []
}


def load_state():
    DATA_DIR.mkdir(exist_ok=True)

    if not STATE_FILE.exists():
        state = DEFAULT_STATE.copy()
        save_state(state)
        return state

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    except (json.JSONDecodeError, OSError):
        print("检测到状态文件为空或损坏，已重新初始化。")

        state = DEFAULT_STATE.copy()
        save_state(state)

        return state


def save_state(state):
    DATA_DIR.mkdir(exist_ok=True)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )


# ---------------------------------------------------------------------------
# V0.2：画像合并与阶段推进
# ---------------------------------------------------------------------------

def merge_profile(state, profile) -> list[str]:
    """把画像中的**非空**字段合并进 state，返回本轮被更新的字段名列表。

    关键规则：空值不覆盖 —— “这轮没提到”不等于“这个信息不存在”。
    profile 可以是 Pydantic 模型（UserProfile），也可以是普通 dict。
    """
    data = profile.model_dump() if hasattr(profile, "model_dump") else dict(profile)

    updated: list[str] = []
    for field in PROFILE_FIELDS:
        value = data.get(field)
        # 跳过没提到 / 空白的值，保留 state 里已有的信息
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if state.get(field) != value:
            state[field] = value
            updated.append(field)
    return updated


def profile_complete(state) -> bool:
    """四项（目标/水平/每日时间/期限）是否都已收集。"""
    for field in PROFILE_FIELDS:
        value = state.get(field)
        if value is None or value == "" or value == []:
            return False
    return True


def missing_profile_fields(state) -> list[str]:
    """返回还缺失的字段名，便于提示教练“还差什么”。"""
    return [
        field for field in PROFILE_FIELDS
        if state.get(field) in (None, "", [])
    ]


def maybe_advance_stage(state) -> bool:
    """四项齐全且仍处于目标澄清阶段时，推进到能力测评阶段。

    返回是否发生了推进。这是一道守卫：不齐全绝不推进。
    """
    if state.get("current_stage") == STAGE_GOAL_CLARIFICATION and profile_complete(state):
        state["current_stage"] = STAGE_ASSESSMENT
        return True
    return False