"""状态清理工具（原 `reset.py`，测试阶段用）。

只操作 `data/user_state.json`（以及 `data/backups/` 里的备份），
**绝不触碰** `.venv`、向量库、embedding 模型。

三种用法：
    python -m coach.storage.reset                  # 完全重置（回默认状态）
    python -m coach.storage.reset --history        # 只清空对话历史（保留画像 / 计划 / 阶段）
    python -m coach.storage.reset --stage assessment   # 重置并跳到指定阶段（分段测试）

默认每次清理前会自动备份到 `data/backups/user_state_<时间戳>.json`，
并只保留最近 5 份，避免备份越堆越多。
"""

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from coach.config import BACKUP_DIR, DATA_DIR
from coach.domain.memory import archive_message_count
from coach.domain.stages import ALL_STAGES
from coach.domain.state_schema import DEFAULT_STATE
from coach.storage.state_store import STATE_FILE

KEEP_BACKUPS = 5

__all__ = [
    "BACKUP_DIR",
    "KEEP_BACKUPS",
    "backup_state",
    "clear_history",
    "reset_all",
    "reset_history",
    "reset_to_stage",
    "save_to",
]


# ---------------------------------------------------------------------------
# 基础读写（都带路径参数，便于测试用临时文件）
# ---------------------------------------------------------------------------

def _default_state() -> dict:
    """默认状态的**深拷贝**（多处重置都要用；共享可变对象会污染 DEFAULT_STATE）。"""
    return json.loads(json.dumps(DEFAULT_STATE))


def _load(state_file: Path) -> dict:
    """读取状态文件；不存在、损坏或不是 JSON 对象时返回默认状态的深拷贝。"""
    try:
        state = json.loads(Path(state_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_state()
    # `[]` / `null` / `"..."` 都是合法 JSON 却不是状态对象；旧实现会让
    # `clear_history()` 以 AttributeError 崩掉，与本函数声明的"损坏 -> 默认值"不符。
    return state if isinstance(state, dict) else _default_state()


def _save(state: dict, state_file: Path) -> None:
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_to(state: dict, state_file: Path) -> None:
    """把状态写到指定路径（供用例层注入临时路径，便于测试）。"""
    _save(state, state_file)


def clear_history(state: dict) -> int:
    """清空对话历史**与归档**（纯内存操作），返回清掉的条数。

    v0.16：必须**连归档一起清** —— 否则"清空历史"只清掉窗口内的部分，
    归档里仍留着旧对话，用户在"删除我的数据"这件事上会被误导。
    """
    history = state.get("conversation_history") or []
    # v0.18：归档改成**按单次学习分段**，所以条数要由 memory 统一计数
    # （它同时兼容 v0.17 的扁平结构，旧状态文件不会算错）。
    count = len(history) + archive_message_count(state)
    state["conversation_history"] = []
    state["conversation_archive"] = []
    return count


# ---------------------------------------------------------------------------
# 备份
# ---------------------------------------------------------------------------

def backup_state(state_file: Path = STATE_FILE, backup_dir: Path = BACKUP_DIR,
                 keep: int = KEEP_BACKUPS) -> Path | None:
    """把当前状态文件备份到 backup_dir，并只保留最近 keep 份。"""
    source = Path(state_file)
    if not source.exists():
        return None

    target_dir = Path(backup_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    # 精确到微秒，避免同一秒内多次备份互相覆盖
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = target_dir / f"user_state_{stamp}.json"
    shutil.copy2(source, target)

    # 清理旧备份，只保留最近 keep 份
    backups = sorted(target_dir.glob("user_state_*.json"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        try:
            old.unlink()
        except OSError:
            pass
    return target


# ---------------------------------------------------------------------------
# 三种清理动作
# ---------------------------------------------------------------------------

def reset_all(state_file: Path = STATE_FILE, backup: bool = True,
              backup_dir: Path = BACKUP_DIR) -> dict:
    """完全重置为默认状态（回到目标澄清）。"""
    if backup:
        backup_state(state_file, backup_dir)
    state = _default_state()
    _save(state, state_file)
    return state


def reset_history(state_file: Path = STATE_FILE, backup: bool = True,
                  backup_dir: Path = BACKUP_DIR) -> dict:
    """只清空对话历史，保留画像 / 计划 / 阶段 / 进度。"""
    if backup:
        backup_state(state_file, backup_dir)
    state = _load(state_file)
    clear_history(state)
    _save(state, state_file)
    return state


def reset_to_stage(stage: str, state_file: Path = STATE_FILE, backup: bool = True,
                   backup_dir: Path = BACKUP_DIR) -> dict:
    """重置为默认状态，并把阶段设为指定值（分段测试用）。"""
    if stage not in ALL_STAGES:
        raise ValueError(f"未知阶段: {stage}（可选：{'、'.join(ALL_STAGES)}）")
    if backup:
        backup_state(state_file, backup_dir)
    state = _default_state()
    state["current_stage"] = stage
    _save(state, state_file)
    return state


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="清理 Agent 状态（测试用）")
    parser.add_argument("--history", action="store_true",
                        help="只清空对话历史，保留画像 / 计划 / 阶段")
    parser.add_argument("--stage", metavar="STAGE",
                        help=f"重置并跳到指定阶段（可选：{'、'.join(ALL_STAGES)}）")
    parser.add_argument("--no-backup", action="store_true", help="清理前不备份")
    args = parser.parse_args()

    backup = not args.no_backup

    if args.stage:
        try:
            reset_to_stage(args.stage, backup=backup)
        except ValueError as exc:
            raise SystemExit(str(exc))
        print(f"已重置并跳到阶段：{args.stage}")
    elif args.history:
        before = _load(STATE_FILE).get("conversation_history") or []
        reset_history(backup=backup)
        print(f"已清空对话历史（{len(before)} 条），画像/计划/阶段保留")
    else:
        reset_all(backup=backup)
        print("已完全重置（回到目标澄清）")

    if backup:
        print(f"备份目录：{BACKUP_DIR}（保留最近 {KEEP_BACKUPS} 份）")


if __name__ == "__main__":
    main()
