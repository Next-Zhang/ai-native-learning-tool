r"""S-08 不可逆动作的人工确认门（PRD §3.4 人工介入 / 测试矩阵 **T-10**）。

运行（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\test_confirmation.py

覆盖：
- 四个受保护动作全部登记：重建计划 / 修改长期目标 / 删除历史 / 标记已掌握
- **放行**：明确确认后才允许执行
- **拦截**：拒绝、超时（无应答）、确认过程抛异常 —— 一律不执行（fail-closed）
- **不可绕过**：未登记的动作直接抛 UnknownActionError
- 被拒 / 超时后 **state 与状态文件完全不变**
- 确认通过后才真正清理；`/reset all` **不与 DEFAULT_STATE 共享可变对象**

不依赖 API Key，全部为确定性用例。
"""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.domain.confirmations import (
    GATED_ACTIONS,
    ConfirmationOutcome,
    UnknownActionError,
    build_prompt,
    require_human_confirmation,
    ActionId,
)
from coach.domain.state_schema import DEFAULT_STATE
from coach.services.maintenance import SCOPE_ALL, SCOPE_HISTORY, perform_reset

TMP_ROOT = Path(__file__).resolve().parent / ".tmp" / "confirmation"


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _workspace(name: str):
    """隔离的临时工作区，返回 (state_file, backup_dir)。"""
    base = TMP_ROOT / name
    if base.exists():
        shutil.rmtree(base)
    backup_dir = base / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return base / "user_state.json", backup_dir


def _state_with_history(n: int = 2) -> dict:
    state = json.loads(json.dumps(DEFAULT_STATE))
    state["learning_goal"] = "Python 数据分析"
    state["skill_profile"] = {"列表切片": 0.5}
    state["conversation_history"] = [
        {"role": "user", "content": f"第 {i} 条"} for i in range(n)
    ]
    return state


def _yes(_prompt: str):
    return True


def _no(_prompt: str):
    return False


def _silent(_prompt: str):
    return None                     # 超时 / 无应答


def _boom(_prompt: str):
    raise RuntimeError("输入通道故障")


# ---------------------------------------------------------------------------
# 1) 动作登记
# ---------------------------------------------------------------------------

def test_all_gated_actions_are_registered():
    """PRD 点名的四类动作必须全部登记，且都有可展示的说明。

    契约钉桩：断言的是 `GATED_ACTIONS` 的**内容**，不调用被测函数 ——
    **只防误删、不证明行为**（确认门是否真的拦住，由本文件其余用例覆盖）。
    """
    expected = {
        ActionId.REBUILD_PLAN.value,
        ActionId.CHANGE_LEARNING_GOAL.value,
        ActionId.DELETE_HISTORY.value,
        ActionId.MARK_SKILL_MASTERED.value,
    }
    assert expected <= set(GATED_ACTIONS), sorted(set(GATED_ACTIONS))

    for action_id in expected:
        action = GATED_ACTIONS[action_id]
        assert action.label and action.description and action.consequence, action_id


def test_unknown_action_raises():
    """未登记的动作不能静默放行 —— 必须在调用点炸掉。"""
    try:
        require_human_confirmation("delete_everything", _yes)
    except UnknownActionError:
        pass
    else:
        raise AssertionError("未登记的动作不应被放行")


# ---------------------------------------------------------------------------
# 2) 三种结果：放行 / 拒绝 / 超时
# ---------------------------------------------------------------------------

def test_approved_allows():
    decision = require_human_confirmation(ActionId.DELETE_HISTORY.value, _yes)
    assert decision.allowed is True
    assert bool(decision) is True
    assert decision.outcome is ConfirmationOutcome.APPROVED


def test_denied_blocks():
    decision = require_human_confirmation(ActionId.DELETE_HISTORY.value, _no)
    assert decision.allowed is False
    assert bool(decision) is False
    assert decision.outcome is ConfirmationOutcome.DENIED
    assert "拒绝" in decision.reason


def test_timeout_blocks():
    """无应答（返回 None）必须按"不执行"处理。"""
    decision = require_human_confirmation(ActionId.DELETE_HISTORY.value, _silent)
    assert decision.allowed is False
    assert decision.outcome is ConfirmationOutcome.TIMEOUT


def test_confirm_fn_exception_is_fail_closed():
    """确认通道本身出错时，绝不能默认放行。"""
    decision = require_human_confirmation(ActionId.DELETE_HISTORY.value, _boom)
    assert decision.allowed is False
    assert decision.outcome is ConfirmationOutcome.TIMEOUT
    assert "RuntimeError" in decision.reason


def test_confirm_fn_must_be_callable():
    try:
        require_human_confirmation(ActionId.DELETE_HISTORY.value, "yes")
    except TypeError:
        pass
    else:
        raise AssertionError("非可调用对象应当报错")


def test_cli_module_not_shadowed_by_function():
    """`coach.cli.main` 必须仍是**模块**。

    回归守卫：`coach/cli/__init__.py` 曾写 `from coach.cli.main import main`，
    导致函数 `main` 遮蔽同名子模块，`coach.cli.main.ask_confirmation` 无法访问。
    """
    import importlib

    module = importlib.import_module("coach.cli.main")
    assert callable(module.ask_confirmation), "CLI 确认提示器不可达"
    assert callable(module.main)

    import coach.cli

    # 子模块导入后，属性 `coach.cli.main` 必须是模块，而不是同名函数
    assert "main" in vars(coach.cli), "子模块未被登记"
    assert not callable(coach.cli.main), "coach.cli.main 被同名函数遮蔽了"


def test_prompt_explains_action_and_consequence():
    prompt = build_prompt(ActionId.MARK_SKILL_MASTERED.value, detail="范围：Python 数据分析")
    assert "需要你确认" in prompt
    assert GATED_ACTIONS[ActionId.MARK_SKILL_MASTERED.value].label in prompt
    assert "不可逆后果" in prompt
    assert "范围：Python 数据分析" in prompt


# ---------------------------------------------------------------------------
# 3) 与真实操作接线：被拦时不改 state、不落盘
# ---------------------------------------------------------------------------

def test_reset_history_denied_leaves_state_untouched():
    state_file, backup_dir = _workspace("denied_history")
    state = _state_with_history(3)
    state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    before = state_file.read_text(encoding="utf-8")

    outcome = perform_reset(
        state, SCOPE_HISTORY, _no, state_file=state_file, backup_dir=backup_dir
    )

    assert outcome.executed is False
    assert "已取消" in outcome.message
    assert len(state["conversation_history"]) == 3          # state 未变
    assert state_file.read_text(encoding="utf-8") == before  # 文件未变


def test_reset_history_timeout_leaves_state_untouched():
    state_file, backup_dir = _workspace("timeout_history")
    state = _state_with_history(2)

    outcome = perform_reset(
        state, SCOPE_HISTORY, _silent, state_file=state_file, backup_dir=backup_dir
    )

    assert outcome.executed is False
    assert len(state["conversation_history"]) == 2
    assert not state_file.exists()                           # 全程没落盘


def test_reset_all_denied_keeps_profile_and_plan():
    state_file, backup_dir = _workspace("denied_all")
    state = _state_with_history(1)
    state["plan_confirmed"] = True
    state["current_stage"] = "learning"

    outcome = perform_reset(
        state, SCOPE_ALL, _no, state_file=state_file, backup_dir=backup_dir
    )

    assert outcome.executed is False
    assert state["current_stage"] == "learning"
    assert state["plan_confirmed"] is True
    assert state["learning_goal"] == "Python 数据分析"


# ---------------------------------------------------------------------------
# 4) 确认通过后才真正执行
# ---------------------------------------------------------------------------

def test_reset_history_approved_clears_and_saves():
    state_file, backup_dir = _workspace("approved_history")
    state = _state_with_history(3)

    outcome = perform_reset(
        state, SCOPE_HISTORY, _yes, state_file=state_file, backup_dir=backup_dir
    )

    assert outcome.executed is True
    assert outcome.cleared == 3
    assert state["conversation_history"] == []
    assert state["learning_goal"] == "Python 数据分析"        # 画像保留
    assert state["skill_profile"] == {"列表切片": 0.5}         # 计划/画像保留

    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["conversation_history"] == []


def test_reset_all_approved_restores_defaults_and_backs_up():
    state_file, backup_dir = _workspace("approved_all")
    state = _state_with_history(2)
    state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    outcome = perform_reset(
        state, SCOPE_ALL, _yes, state_file=state_file, backup_dir=backup_dir
    )

    assert outcome.executed is True
    assert outcome.backup_path is not None and outcome.backup_path.exists()
    assert state["current_stage"] == DEFAULT_STATE["current_stage"]
    assert state["conversation_history"] == []
    assert state["learning_goal"] is None


def test_reset_all_does_not_share_mutable_defaults():
    """深拷贝守卫：state 不能与 DEFAULT_STATE 共享同一批可变对象。

    旧 CLI 的 `/reset all` 直接 `state.update(DEFAULT_STATE)`，会把默认值里的
    list/dict 共享给 state，后续写入就会污染默认状态。
    """
    state_file, backup_dir = _workspace("deep_copy")
    state = _state_with_history(1)
    state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    perform_reset(state, SCOPE_ALL, _yes, state_file=state_file, backup_dir=backup_dir)

    for key in ("skill_profile", "weak_points", "plan_progress", "conversation_history"):
        assert state[key] is not DEFAULT_STATE[key], f"{key} 与默认值共享同一对象"

    # 写 state 不得污染默认状态
    state["skill_profile"]["污染检查"] = 1
    state["plan_progress"]["completed"].append("9-9")
    assert "污染检查" not in DEFAULT_STATE["skill_profile"]
    assert DEFAULT_STATE["plan_progress"]["completed"] == []


def test_unknown_scope_raises():
    state = _state_with_history(0)
    try:
        perform_reset(state, "everything", _yes)
    except ValueError:
        pass
    else:
        raise AssertionError("未知范围应当报错")


# ---------------------------------------------------------------------------
# 极简 runner（共用实现见 tests/_runner.py）
# ---------------------------------------------------------------------------

from _runner import SkipTest, run_tests        # noqa: E402


def main() -> int:
    return run_tests(globals())


if __name__ == "__main__":
    raise SystemExit(main())
