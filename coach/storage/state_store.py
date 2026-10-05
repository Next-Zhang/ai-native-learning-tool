"""用户状态的读写（原 `state.py` 的持久化部分）。

路径常量统一来自 `coach.config`，不再各模块自行推导。
"""

import json

from coach.config import DATA_DIR
from coach.domain.state_schema import DEFAULT_STATE, ensure_keys

STATE_FILE = DATA_DIR / "user_state.json"

__all__ = [
    "DATA_DIR",
    "DEFAULT_STATE",
    "STATE_FILE",
    "ensure_keys",
    "load_state",
    "save_state",
]


def load_state():
    """读取状态；不存在则落盘一份默认状态并返回。损坏时重建并告警。"""
    DATA_DIR.mkdir(exist_ok=True)

    if not STATE_FILE.exists():
        state = json.loads(json.dumps(DEFAULT_STATE))
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

        state = json.loads(json.dumps(DEFAULT_STATE))
        save_state(state)

        return state


def save_state(state):
    """把状态写入本机 JSON（UTF-8、缩进 2）。"""
    DATA_DIR.mkdir(exist_ok=True)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )
