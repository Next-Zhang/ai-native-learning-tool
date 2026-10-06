"""用户状态的读写（原 `state.py` 的持久化部分）。

路径常量统一来自 `coach.config`，不再各模块自行推导。

**两条数据安全约定**（审计发现旧实现违反，已修）：

1. **写入必须原子**：先写同目录临时文件再 `os.replace`。
   旧实现直接 `open(STATE_FILE, "w")` —— 写到一半崩溃会留下半截 JSON，
   下次 `load_state` 判定为损坏并**重建默认值**，等于静默丢掉全部学习数据。
2. **绝不清空覆盖**：状态文件损坏时，先把它**挪到备份目录留存**再重建。
   旧实现直接覆盖，"文件写坏了"就变成不可逆的数据丢失。
"""

import json
import os
import shutil
from datetime import datetime

from coach.config import BACKUP_DIR, DATA_DIR
from coach.domain.state_schema import DEFAULT_STATE, ensure_keys

STATE_FILE = DATA_DIR / "user_state.json"

__all__ = [
    "BACKUP_DIR",
    "DATA_DIR",
    "DEFAULT_STATE",
    "STATE_FILE",
    "ensure_keys",
    "load_state",
    "save_state",
]


def _default_state() -> dict:
    """默认状态的**深拷贝** —— 可变默认值（list/dict）不能被多个 state 共享。"""
    return json.loads(json.dumps(DEFAULT_STATE))


def _quarantine_broken_file() -> str:
    """把损坏的状态文件复制到备份目录留存；返回留存文件名（失败返回空串）。

    **不删原文件**（`load_state` 随后会原子覆盖它），只做一份留底 ——
    这样"文件写坏了"仍然可人工抢救，而不是永久丢失。
    """
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target = BACKUP_DIR / f"user_state_broken_{stamp}.json"
        shutil.copy2(STATE_FILE, target)
        return target.name
    except OSError:
        return ""


def load_state():
    """读取状态；不存在则落盘一份默认状态并返回。损坏时**先留底再重建**并告警。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not STATE_FILE.exists():
        state = _default_state()
        save_state(state)
        return state

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        state = _rebuild("检测到状态文件为空或损坏，已重新初始化。")
        return state

    # 合法 JSON 但**不是对象**（`[]` / `null` / `"..."`）同样是损坏。
    # 旧实现会让 `ensure_keys()` 以 TypeError 崩掉，而不是按本函数的契约"重建并告警"。
    if not isinstance(state, dict):
        state = _rebuild("检测到状态文件格式不正确（不是 JSON 对象），已重新初始化。")
        return state

    # 向后兼容：旧状态文件缺少 V0.3 新字段时自动补齐（不覆盖已有值）
    added = ensure_keys(state)
    if added:
        print(f"已为状态文件补齐新字段：{'、'.join(added)}")
        save_state(state)

    return state


def _rebuild(message: str) -> dict:
    """留存损坏文件 → 重建默认状态并落盘。"""
    kept = _quarantine_broken_file()
    suffix = f"（原文件已留存到备份目录：{kept}）" if kept else ""
    print(message + suffix)
    state = _default_state()
    save_state(state)
    return state


def save_state(state) -> None:
    """把状态**原子地**写入本机 JSON（UTF-8、缩进 2）。

    临时文件与目标文件**同目录**，`os.replace` 在同一文件系统内才是原子的。
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    tmp = STATE_FILE.with_name(STATE_FILE.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())          # 先落盘，再替换，避免替换到的是空文件
    os.replace(tmp, STATE_FILE)
