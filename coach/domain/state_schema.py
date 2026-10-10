"""状态 schema 与向后兼容迁移（原 `state.py` 的 schema 部分）。

本模块只定义"状态长什么样"与"旧状态如何升级"，**不做落盘**（落盘见 `coach.storage.state_store`）。
"""

import json

from coach.domain.plan_rules import plan_unit
from coach.domain.stages import STAGE_GOAL_CLARIFICATION

DEFAULT_STATE = {
    "learning_goal": None,
    "current_level": None,
    "session_minutes": None,       # **单次**可投入分钟数（v0.13 起替代 daily_minutes）
    "sessions_per_week": None,     # 每周大约几次（可选；None = 不作承诺）
    "target_date": None,

    "current_stage": STAGE_GOAL_CLARIFICATION,

    # v0.16：学习偏好（画像维度 d）。默认**空**——由澄清阶段问 1 个关键问题、
    # 同一次抽取顺带获得、以及行为推断三者共同填充（PRD §2.5.2）。
    "preferences": {},

    "skill_profile": {},
    "weak_points": [],

    # 双层计划（v0.14 / S-12）：
    #   roadmap        = 长期**路线图**（目标 → 里程碑），**不滚动**
    #   current_window = 短期**执行窗口**（可执行单元列表），**滚动**
    "roadmap": None,
    "current_window": None,
    "plan_confirmed": False,       # 路线图是否已被用户确认（确认后才进入学习）
    "plan_progress": {             # 窗口游标（第几个单元 / 单元内第几个任务 / 已完成 / 完成 / 尝试次数）
        "day": 1,
        "task": 1,
        "completed": [],
        "finished": False,
        "attempts": 0,             # v0.14：验收判定次数（**含重做**）—— "滚动=重估"的速度信号
        "session_day": 0,          # v0.18：已开过学习的那一天（0=还没开过）；跨天即跨次学习
    },
    "today_task": None,

    # V0.3 新增字段（V0.3b–e 使用；旧状态文件由 ensure_keys 自动补齐）
    "assessment_progress": None,   # 测评进度：题目、作答、当前题号
    "pending_submission": None,    # 用户提交、待验收的学习结果
    "latest_result": None,         # 最近一次验收结论
    "latest_result_applied": False,  # V0.3e：该结论是否已应用到画像

    "conversation_history": [],

    # v0.16（S-09）：移出对话窗口的明细进这里 —— **不丢信息，但不注入模型**。
    # 目的：压制"每轮注入全量 history"带来的成本与暴露面（PRD X-09 / X-11）。
    "conversation_archive": [],

    # v0.18：长期记忆的**事实层**（见 docs/memory-design.md §5 / I-12）
    #   session_seq      **单调递增**的单次学习序号
    #                    （`plan_progress.day` 每个计划块会重置，不能当序号用）
    #   evidence         知识点 -> [{at, session_seq, source, verdict, score,
    #                                error_type, task_id}]（每个知识点保留最近 K 条）
    #   session_records  每次单次学习的记录（L2 定稿摘要的落点）
    "session_seq": 0,
    "evidence": {},
    "session_records": [],

    # v0.18：记忆的**叙事层**（有损、可压缩；见 docs/memory-design.md §6）
    #   rolling_summary   本次单次学习内的滚动摘要（**单槽：替换而不是追加**）
    #   session_summaries 每次单次学习定稿一条（上界由 memory 裁剪）
    "rolling_summary": None,
    "session_summaries": [],
    # 已定稿摘要到第几次学习（幂等标记）。**放在顶层而不是 plan_progress** ——
    # 窗口滚动会整体重置游标（`fresh_progress()`），放里面会被清零并导致重复压缩。
    "condensed_through_seq": 0,
}

#: 旧字段 → 新字段。
#:
#: - v0.13：时间预算由"**每天总量**"改为"**单次时长**"。
#:   **迁移假设**：旧的 `daily_minutes` 被当作"一次坐下来的时长"。
#:   这对原用户（20~30 分钟/天）是合理的近似，但**语义确实变了** ——
#:   迁移后教练会按 `session_minutes` 排任务，用户若实际只有 10 分钟需自行纠正。
#:   之所以选择迁移而非"重新追问"：后者会把用户打回澄清阶段，代价更大。
#: - v0.14：`current_plan` 改名为 `current_window`（它本来就是"执行窗口"，
#:   不是完整计划；完整计划现在是 `roadmap`）。**纯改名，语义不变**。
LEGACY_FIELD_MAP = {
    "daily_minutes": "session_minutes",
    "current_plan": "current_window",
}


def migrate_legacy_fields(state) -> list[str]:
    """把旧字段搬到新字段，返回迁移记录（形如 `daily_minutes->session_minutes`）。

    只在新字段为空时搬；**不覆盖**新值，也**不删除**旧键 —— 迁移应当信息保全，
    删掉旧键会让"迁移出错"变成不可逆事件。
    """
    moved: list[str] = []
    for old, new in LEGACY_FIELD_MAP.items():
        if old not in state:
            continue
        if state.get(new) in (None, "", []):
            state[new] = state[old]
            if state[old] is not None:
                moved.append(f"{old}->{new}")
    return moved


def upgrade_window_shape(state) -> list[str]:
    """把旧的"计划"结构补齐成**执行窗口**结构（v0.14）。

    旧结构只有 `horizon_days`；新结构需要 `length`（窗口长度）+ `unit`（单位）
    + `milestone_id`（所属里程碑）。**只补缺失的键，不覆盖已有值。**
    """
    window = state.get("current_window")
    if not isinstance(window, dict):
        return []

    changed: list[str] = []
    if "length" not in window:
        window["length"] = int(
            window.get("horizon_days") or len(window.get("days") or []) or 1
        )
        changed.append("current_window.length")
    if "unit" not in window:
        window["unit"] = plan_unit(state)
        changed.append("current_window.unit")
    if "milestone_id" not in window:
        window["milestone_id"] = (state.get("roadmap") or {}).get("current_milestone")
        changed.append("current_window.milestone_id")
    return changed


def upgrade_plan_progress(state) -> list[str]:
    """给 `plan_progress` 补 v0.14 新增的 `attempts`（验收尝试次数）。

    **`ensure_keys` 只补顶层键**，嵌套结构必须单独升级 —— 漏了它，
    旧状态文件里的 `plan_progress` 就永远没有 `attempts`，
    "滚动=重估"会退化成中性（ratio = 1），静默失效。
    """
    progress = state.get("plan_progress")
    if not isinstance(progress, dict) or "attempts" in progress:
        return []
    progress["attempts"] = 0
    return ["plan_progress.attempts"]


def upgrade_evidence_shape(state) -> list[str]:
    """把旧状态的 `skill_profile` **补种**成一条条 evidence（v0.18）。

    只在"**有画像、却没有任何证据**"时补种 —— 否则会重复补种、或覆盖真实证据。

    补种的来源如实标记为 `migrated_v0.17`：**不伪装成测评或验收**。
    I-12 要求来源可信；"编一个来源"比标注"这是迁移来的"更糟。

    不补种的后果很严重：画像改为由证据派生后，旧用户的 `skill_profile`
    会因为"没有证据"而**在第一次运行时就变空** —— 等于抹掉他全部的掌握度。
    """
    profile = state.get("skill_profile")
    if not isinstance(profile, dict) or not profile:
        return []
    evidence = state.get("evidence")
    if isinstance(evidence, dict) and evidence:
        return []

    # 局部导入：避免 domain 内部循环导入（memory 依赖 assessment_rules）。
    from coach.domain.memory import SOURCE_MIGRATED, record_evidence

    seeded = 0
    for topic, score in profile.items():
        if record_evidence(state, topic, source=SOURCE_MIGRATED,
                           verdict="migrated", score=score):
            seeded += 1
    return [f"evidence(seeded {seeded})"] if seeded else []


def upgrade_archive_shape(state) -> list[str]:
    """把**扁平**的 `conversation_archive`（v0.17：一个消息列表）升级为**分段**结构（v0.18）。

    为什么要分段：归档要按"**保留最近 N 次单次学习**"裁剪
    （见 docs/memory-design.md §8.2），而扁平列表无法知道哪条消息属于哪一次学习。

    旧数据统一并入一个 `session_seq=0` 的分段 —— **不删、不猜**（猜错比不猜更糟）。
    """
    archive = state.get("conversation_archive")
    if not isinstance(archive, list) or not archive:
        return []
    if all(isinstance(seg, dict) and "messages" in seg for seg in archive):
        return []                          # 已经是分段结构
    messages = [m for m in archive if isinstance(m, dict)]
    state["conversation_archive"] = [{"session_seq": 0, "messages": messages}]
    return ["conversation_archive(segmented)"]


def ensure_keys(state, defaults=None) -> list[str]:
    """升级 state：迁移旧字段 → 升级嵌套结构 → 补齐缺失顶层键；返回**全部变更**。

    **返回值必须包含迁移结果**：调用方（`storage.state_store.load_state`）只在
    返回非空时才落盘。旧实现丢弃迁移记录 → 迁移只在内存生效，**文件里始终留着旧字段**，
    看起来"迁移没生效"。

    顺序很重要：先迁移（否则 `session_minutes` 会被默认值 `None` 占位，
    后续迁移因"新值非空"被跳过）。
    """
    changed: list[str] = []
    changed.extend(migrate_legacy_fields(state))
    changed.extend(upgrade_window_shape(state))
    changed.extend(upgrade_plan_progress(state))
    changed.extend(upgrade_archive_shape(state))

    if defaults is None:
        defaults = DEFAULT_STATE
    for key, value in defaults.items():
        if key not in state:
            # 可变默认值要深拷贝，避免多个 state 共享同一个 list/dict
            state[key] = json.loads(json.dumps(value))
            changed.append(key)

    # v0.18：**补种必须在补默认键之后** —— 它要能看到补出来的空 evidence。
    changed.extend(upgrade_evidence_shape(state))
    return changed
