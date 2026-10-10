"""状态分区视图（`docs/memory-design.md` §8.3 / **I-8 的载体**）。

**本模块不改变 state 的物理结构** —— 它仍是一个扁平的 dict。
它只回答三个问题：

1. 每个键属于哪个**区**（`ZONE_OF`）
2. 每个区怎么**保留**（`RETENTION`）
3. 有没有键**没有归属**（`unknown_keys`）—— 由契约测试断言

这样将来真要按区拆成多个文件时，**只改落盘层**，业务代码不感知。
分区口径与 `docs/architecture.md` §12.2 的 4 区一致。
"""

__all__ = [
    "LEGACY_TOLERATED",
    "RETENTION",
    "ZONE_HISTORY",
    "ZONE_OF",
    "ZONE_PROFILE",
    "ZONE_PROGRESS",
    "ZONE_RUNTIME",
    "ZONES",
    "keys_in",
    "unknown_keys",
    "zone_of",
]

ZONE_PROFILE = "profile"
ZONE_PROGRESS = "progress"
ZONE_RUNTIME = "runtime"
ZONE_HISTORY = "history"

ZONES = (ZONE_PROFILE, ZONE_PROGRESS, ZONE_RUNTIME, ZONE_HISTORY)

#: 每个区的**保留策略**（将来拆文件时直接照这张表做）
RETENTION = {
    ZONE_PROFILE: "long",        # 关于人的稳定事实：长期
    ZONE_PROGRESS: "rolling",    # 方案与表现：随计划块滚动
    ZONE_RUNTIME: "per_turn",    # 当前状态：每轮可重置
    ZONE_HISTORY: "windowed",    # 对话：窗口 + 归档
}

#: 键 -> 区。**每个 `DEFAULT_STATE` 的键都必须在这里**（`tests/test_memory.py` 把关）。
ZONE_OF = {
    # ── 关于人的稳定事实 ──
    "learning_goal": ZONE_PROFILE,
    "current_level": ZONE_PROFILE,
    "session_minutes": ZONE_PROFILE,
    "sessions_per_week": ZONE_PROFILE,
    "target_date": ZONE_PROFILE,
    "preferences": ZONE_PROFILE,
    "skill_profile": ZONE_PROFILE,      # 派生视图
    "weak_points": ZONE_PROFILE,        # 派生视图

    # ── 方案与表现 ──
    "roadmap": ZONE_PROGRESS,
    "current_window": ZONE_PROGRESS,
    "plan_confirmed": ZONE_PROGRESS,
    "plan_progress": ZONE_PROGRESS,
    "session_seq": ZONE_PROGRESS,
    # ⚠️ `evidence` 在同区里是个例外：它**不随计划块滚掉**，
    #    而是按"每个知识点保留最近 K 条"封顶（见 memory.record_evidence）。
    "evidence": ZONE_PROGRESS,
    "session_records": ZONE_PROGRESS,
    "condensed_through_seq": ZONE_PROGRESS,
    "rolling_summary": ZONE_PROGRESS,
    "session_summaries": ZONE_PROGRESS,

    # ── 当前状态（每轮）──
    "current_stage": ZONE_RUNTIME,
    "today_task": ZONE_RUNTIME,
    "assessment_progress": ZONE_RUNTIME,
    "pending_submission": ZONE_RUNTIME,
    "latest_result": ZONE_RUNTIME,
    "latest_result_applied": ZONE_RUNTIME,

    # ── 对话流水 ──
    "conversation_history": ZONE_HISTORY,
    "conversation_archive": ZONE_HISTORY,
}

#: 迁移遗留的旧键（`LEGACY_FIELD_MAP` 只搬不删，旧文件里会一直留着它们）。
LEGACY_TOLERATED = ("daily_minutes", "current_plan")


def zone_of(key: str):
    """该键属于哪个区；未登记返回 None。"""
    return ZONE_OF.get(key)


def keys_in(zone: str) -> tuple:
    """某区包含的全部键（已排序）。"""
    return tuple(sorted(key for key, value in ZONE_OF.items() if value == zone))


def unknown_keys(keys) -> tuple:
    """**没有归区**的键（忽略迁移遗留的旧键）—— 契约测试断言它为空。"""
    return tuple(sorted(k for k in keys if k not in ZONE_OF and k not in LEGACY_TOLERATED))
