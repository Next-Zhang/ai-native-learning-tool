import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
STATE_FILE = DATA_DIR / "user_state.json"


# 四项必须齐全才能进入能力测评（状态机的第一道守卫）
PROFILE_FIELDS = ("learning_goal", "current_level", "daily_minutes", "target_date")

# 阶段名常量（状态机本体在 stages.py，这里只保存“名字”，避免循环依赖）
STAGE_GOAL_CLARIFICATION = "goal_clarification"
STAGE_ASSESSMENT = "assessment"
STAGE_PLANNING = "planning"
STAGE_LEARNING = "learning"
STAGE_EVALUATION = "evaluation"
STAGE_PROFILE_UPDATE = "profile_update"
STAGE_REVIEW = "review"
STAGE_COMPLETED = "completed"


DEFAULT_STATE = {
    "learning_goal": None,
    "current_level": None,
    "daily_minutes": None,
    "target_date": None,

    "current_stage": STAGE_GOAL_CLARIFICATION,

    "skill_profile": {},
    "weak_points": [],

    "current_plan": None,
    "plan_confirmed": False,       # V0.3c：计划是否已被用户确认（确认后才进入每日任务）
    "plan_progress": {             # V0.3d：计划游标（第几天 / 当天第几个任务 / 已完成列表）
        "day": 1,
        "task": 1,
        "completed": [],
        "finished": False,
    },
    "today_task": None,

    # V0.3 新增字段（V0.3b–e 使用；旧状态文件由 ensure_keys 自动补齐）
    "assessment_progress": None,   # 测评进度：题目、作答、当前题号
    "pending_submission": None,    # 用户提交、待验收的学习结果
    "latest_result": None,         # 最近一次验收结论
    "latest_result_applied": False,  # V0.3e：该结论是否已应用到画像

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
            state = json.load(f)

        # 向后兼容：旧状态文件缺少 V0.3 新字段时自动补齐（不覆盖已有值）
        added = ensure_keys(state)
        if added:
            print(f"已为状态文件补齐新字段：{'、'.join(added)}")
            save_state(state)

        return state

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


def ensure_keys(state, defaults=None) -> list[str]:
    """为 state 补齐 defaults 中缺失的顶层键（不覆盖已有值），返回补齐的键名。

    用途：版本升级新增 state 字段时，让旧的状态文件平滑迁移而不是报错。
    """
    if defaults is None:
        defaults = DEFAULT_STATE
    added: list[str] = []
    for key, value in defaults.items():
        if key not in state:
            # 可变默认值要深拷贝，避免多个 state 共享同一个 list/dict
            state[key] = json.loads(json.dumps(value))
            added.append(key)
    return added


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


# 阶段推进（状态机）已移至 stages.py —— 那里是转换规则与守卫的唯一来源。
# 本模块只负责：状态读写、画像合并、字段完备性判断。