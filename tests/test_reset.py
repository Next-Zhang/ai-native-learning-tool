r"""状态清理工具验收测试（纯 Python 断言脚本）。

运行（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\test_reset.py

覆盖：
- clear_history：清空历史并返回条数（纯内存）
- reset_all：写回默认状态，且默认会先生成备份
- reset_history：清历史但保留画像 / 计划 / 阶段 / 进度
- reset_to_stage：重置并跳阶段；非法阶段抛错
- 备份策略：备份文件生成、只保留最近 N 份
- state 文件不存在时也能安全重置

注意：临时文件建在 tests/.tmp 下（工作区内），因为运行环境不允许写系统临时目录；
所有用例都不碰真实的 data/user_state.json。
"""

import copy
import json
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.domain.state_schema import DEFAULT_STATE
from coach.storage.reset import (
    KEEP_BACKUPS,
    backup_state,
    clear_history,
    reset_all,
    reset_history,
    reset_to_stage,
)

TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


@contextmanager
def _workspace():
    """在工作区内提供一次性临时目录（用后即删）。"""
    if TMP_ROOT.exists():
        shutil.rmtree(TMP_ROOT, ignore_errors=True)
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        yield TMP_ROOT
    finally:
        shutil.rmtree(TMP_ROOT, ignore_errors=True)


def _write_state(path: Path, **overrides) -> dict:
    state = copy.deepcopy(DEFAULT_STATE)
    state.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


# ---------------------------------------------------------------------------
# 1) 纯函数
# ---------------------------------------------------------------------------

def test_clear_history_counts_and_clears():
    state = {"conversation_history": [{"role": "user"}, {"role": "assistant"}]}
    assert clear_history(state) == 2
    assert state["conversation_history"] == []

    # 没有历史 -> 返回 0，不报错
    assert clear_history({}) == 0


# ---------------------------------------------------------------------------
# 2) 三种清理动作
# ---------------------------------------------------------------------------

def test_reset_all_restores_defaults_and_backs_up():
    with _workspace() as tmp:
        state_file = tmp / "data" / "user_state.json"
        backup_dir = tmp / "data" / "backups"
        _write_state(state_file, learning_goal="Python", current_stage="assessment",
                     conversation_history=[{"role": "user", "content": "hi"}])

        state = reset_all(state_file=state_file, backup_dir=backup_dir)

        assert state["current_stage"] == "goal_clarification"
        assert state["learning_goal"] is None
        assert state["conversation_history"] == []
        # 落盘内容与返回值一致
        on_disk = json.loads(state_file.read_text(encoding="utf-8"))
        assert on_disk == state
        # 备份已生成，且保留的是重置前的内容
        backups = list(backup_dir.glob("user_state_*.json"))
        assert len(backups) == 1
        assert json.loads(backups[0].read_text(encoding="utf-8"))["learning_goal"] == "Python"


def test_reset_history_keeps_profile_plan_and_stage():
    with _workspace() as tmp:
        state_file = tmp / "data" / "user_state.json"
        backup_dir = tmp / "data" / "backups"
        _write_state(
            state_file,
            learning_goal="Python 数据分析",
            session_minutes=30,
            current_stage="learning",
            skill_profile={"读取数据": 0.75},
            current_window={
                "length": 2,                       # 当前窗口字段（旧名 horizon_days 已由 upgrade_window_shape 迁移）
                "unit": "session",
                "start_date": "2026-01-01",
                "days": [
                    {"day": 1, "theme": "读取数据", "tasks": [{"goal": "读 CSV"}]},
                    {"day": 2, "theme": "分组聚合", "tasks": [{"goal": "groupby"}]},
                ],
            },
            plan_confirmed=True,
            plan_progress={"day": 2, "task": 1, "completed": ["1-1"], "finished": False},
            conversation_history=[{"role": "user", "content": "a"}] * 5,
        )

        state = reset_history(state_file=state_file, backup_dir=backup_dir)

        assert state["conversation_history"] == []                 # 历史清空
        assert state["learning_goal"] == "Python 数据分析"          # 画像保留
        assert state["session_minutes"] == 30
        assert state["current_stage"] == "learning"                # 阶段保留
        assert state["skill_profile"] == {"读取数据": 0.75}
        # 执行窗口原样保留（长度与单位都没被清掉/改写）
        assert (state["current_window"]["length"],
                state["current_window"]["unit"]) == (2, "session")
        assert state["plan_progress"]["completed"] == ["1-1"]


def test_reset_to_stage():
    with _workspace() as tmp:
        state_file = tmp / "data" / "user_state.json"
        backup_dir = tmp / "data" / "backups"
        _write_state(state_file, learning_goal="Python")

        state = reset_to_stage("assessment", state_file=state_file, backup_dir=backup_dir)
        assert state["current_stage"] == "assessment"
        assert state["learning_goal"] is None                      # 重置为默认（画像不保留）

        # 非法阶段 -> 抛错，且不修改文件
        before = state_file.read_text(encoding="utf-8")
        try:
            reset_to_stage("no_such_stage", state_file=state_file, backup_dir=backup_dir)
        except ValueError as exc:
            assert "未知阶段" in str(exc)
        else:
            raise AssertionError("非法阶段应当抛 ValueError")
        assert state_file.read_text(encoding="utf-8") == before


def test_reset_works_when_state_file_missing():
    with _workspace() as tmp:
        state_file = tmp / "data" / "user_state.json"     # 故意不存在
        backup_dir = tmp / "data" / "backups"

        state = reset_all(state_file=state_file, backup_dir=backup_dir)

        assert state["current_stage"] == "goal_clarification"
        assert state_file.exists()
        assert backup_state(state_file, backup_dir) is not None   # 现在有文件了，能备份


def test_backup_prunes_to_keep_limit():
    with _workspace() as tmp:
        state_file = tmp / "data" / "user_state.json"
        backup_dir = tmp / "data" / "backups"
        _write_state(state_file, learning_goal="Python")

        # 造出比上限更多的备份
        for _ in range(KEEP_BACKUPS + 3):
            backup_state(state_file, backup_dir, keep=KEEP_BACKUPS)
            time.sleep(0.01)          # 让 mtime 有区分度

        backups = sorted(backup_dir.glob("user_state_*.json"))
        assert len(backups) == KEEP_BACKUPS, f"应只保留 {KEEP_BACKUPS} 份，实际 {len(backups)}"


def test_no_backup_flag():
    with _workspace() as tmp:
        state_file = tmp / "data" / "user_state.json"
        backup_dir = tmp / "data" / "backups"
        _write_state(state_file, learning_goal="Python")

        reset_all(state_file=state_file, backup=False, backup_dir=backup_dir)

        assert not backup_dir.exists() or not list(backup_dir.glob("*.json"))


# ---------------------------------------------------------------------------
# 6) 状态文件的数据安全（v0.14 审计修复）
# ---------------------------------------------------------------------------

@contextmanager
def _isolated_store():
    """把 `state_store` 的路径临时指向一次性目录，退出时还原。"""
    from coach.storage import state_store

    original = (state_store.STATE_FILE, state_store.DATA_DIR, state_store.BACKUP_DIR)
    with _workspace() as tmp:
        state_store.STATE_FILE = tmp / "user_state.json"
        state_store.DATA_DIR = tmp
        state_store.BACKUP_DIR = tmp / "backups"
        try:
            yield tmp
        finally:
            (state_store.STATE_FILE,
             state_store.DATA_DIR,
             state_store.BACKUP_DIR) = original


def test_save_state_is_atomic():
    """**写入必须原子**（先写 .tmp 再 `os.replace`）。

    旧实现直接 `open(path, "w")`：写到一半崩溃会留下半截 JSON，
    下次加载判定损坏并**重建默认值** —— 等于静默丢掉全部学习数据。
    """
    from coach.storage import state_store

    with _isolated_store() as tmp:
        state_store.save_state({"learning_goal": "Python"})

        assert state_store.STATE_FILE.exists()
        assert not (tmp / "user_state.json.tmp").exists(), "不得留下临时文件"
        written = json.loads(state_store.STATE_FILE.read_text(encoding="utf-8"))
        assert written["learning_goal"] == "Python"


def test_load_state_keeps_a_copy_of_broken_file():
    """**损坏文件必须先留底再重建** —— 直接覆盖会让"写坏了"变成不可逆的数据丢失。"""
    from coach.storage import state_store

    with _isolated_store() as tmp:
        state_store.STATE_FILE.write_text("{ 半截 JSON", encoding="utf-8")

        state = state_store.load_state()

        assert state["learning_goal"] is None, "应重建为默认状态"
        kept = list((tmp / "backups").glob("user_state_broken_*.json"))
        assert kept, "损坏的原文件必须留底"
        assert "半截 JSON" in kept[0].read_text(encoding="utf-8")


def test_load_state_rebuilds_non_object_json_without_crashing():
    """合法 JSON 但**不是对象**（`[]` / `null` / `"text"`）同样是损坏，不能崩。"""
    from coach.storage import state_store

    for bad in ("[]", "null", '"text"'):
        with _isolated_store() as tmp:
            state_store.STATE_FILE.write_text(bad, encoding="utf-8")

            state = state_store.load_state()

            assert isinstance(state, dict), bad
            assert state["current_stage"], bad
            assert list((tmp / "backups").glob("user_state_broken_*.json")), bad


def test_load_state_upgrades_nested_plan_progress_attempts():
    """v0.14：`ensure_keys` 只补**顶层**键，嵌套的 `plan_progress.attempts` 要单独升级。"""
    from coach.storage import state_store

    with _isolated_store():
        old = copy.deepcopy(DEFAULT_STATE)
        old["plan_progress"] = {"day": 1, "task": 1, "completed": [], "finished": False}
        state_store.STATE_FILE.write_text(
            json.dumps(old, ensure_ascii=False), encoding="utf-8"
        )

        state = state_store.load_state()

        assert state["plan_progress"]["attempts"] == 0, "嵌套键必须被补上"


# ---------------------------------------------------------------------------
# 极简 runner（共用实现见 tests/_runner.py）
# ---------------------------------------------------------------------------

from _runner import SkipTest, run_tests        # noqa: E402


def main() -> int:
    return run_tests(globals())


if __name__ == "__main__":
    raise SystemExit(main())
