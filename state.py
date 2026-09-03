import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
STATE_FILE = DATA_DIR / "user_state.json"


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