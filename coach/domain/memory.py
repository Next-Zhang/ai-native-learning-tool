"""长期记忆：事实层与派生视图（见 `docs/memory-design.md` §5）。

三条不变量在此落地
------------------
- **I-12 记忆必有来源与时间**：每条 evidence 都带 `at`（时间）与 `session_seq`
  （单次学习序号）。没有它们，"遗忘"与"记住"都无从定义。
- **只有 evidence 是直接写的**：`skill_profile` / `weak_points` / 待复验
  都是**派生视图**，由事实算出。
- **I-14 压缩不得承载判定**：本模块只处理结构化事实；摘要（叙事层）不在此落地。

为什么"派生"而不是"就地改"
--------------------------
改造前同一份画像有**两条写入路径，语义还不一致**：

| 路径 | 写法 | 位置 |
|---|---|---|
| 测评 | `state["skill_profile"] = scores`（**整体覆盖**） | `domain/assessment_rules.py` |
| 验收 | `profile[topic] = (old + score) / 2`（**平滑平均**） | `services/evaluation.py` |

本模块把两者收敛成**一次回放**（`derive_profile`）：回放规则与改造前逐字一致，
因此对既有状态是**行为等价**的（`tests/test_memory.py` 有对拍断言）。
"""

from datetime import datetime

from coach.domain.assessment_rules import WEAK_THRESHOLD, derive_weak_points

__all__ = [
    "ARCHIVE_KEEP_SESSIONS",
    "EVIDENCE_KEEP_PER_TOPIC",
    "L1_MIN_DROPPED",
    "L1_TARGET_RATIO",
    "SESSION_SUMMARIES_KEEP",
    "HISTORY_MAX_MESSAGES",
    "INJECT_CHAR_BUDGET",
    "INJECT_SESSION_SUMMARIES",
    "MIN_RAW_MESSAGES",
    "REVIEW_UNCOVERED_SESSIONS",
    "SOURCE_ASSESSMENT",
    "SOURCE_EVALUATION",
    "SOURCE_MIGRATED",
    "SOURCE_SUMMARY",
    "append_to_archive",
    "archive_message_count",
    "archive_segments",
    "current_session",
    "current_cycle_skeleton",
    "derive_due_for_review",
    "derive_profile",
    "derive_weak_points_from_state",
    "evidence_for",
    "new_session",
    "pending_cycle_seq",
    "prune_archive",
    "record_cycle_summary",
    "render_cycle_skeleton",
    "record_evidence",
    "select_history",
    "session_records",
    "upsert_session_record",
]

#: 证据来源。`summary` 是**降采样锚点**（见 `record_evidence`），不是真实来源。
SOURCE_ASSESSMENT = "assessment"
SOURCE_EVALUATION = "evaluation"
SOURCE_MIGRATED = "migrated_v0.17"
SOURCE_SUMMARY = "summary"

#: 每个知识点保留的 evidence 明细条数（上界；更早的被降采样，见 memory-design.md §8.2）
EVIDENCE_KEEP_PER_TOPIC = 5

#: 连续多少次单次学习未覆盖该知识点 → 标记待复验（§7）
REVIEW_UNCOVERED_SESSIONS = 8

#: 归档保留最近多少次单次学习的**原文**（§8.2）；被丢掉的必须留痕（I-13）
ARCHIVE_KEEP_SESSIONS = 30

#: 原始对话日志的条数上限 —— 约两次单次学习的量。
#: **它不决定注入多少**：注入另按字符预算截取（见 @@select_history@@），
#: 这样"注入量"与对话轮数无关（O(1)），而日志本身也不会无限长。
HISTORY_MAX_MESSAGES = 160

#: 注入预算（**字符数**，不是条数）与"无论如何都保留"的最近原文条数（§6.1 / §9）
INJECT_CHAR_BUDGET = 8000
MIN_RAW_MESSAGES = 6

#: 定稿摘要保留条数（§9 的 M=20）；更早的做**确定性汇总**（不再调模型，避免二级失真）
SESSION_SUMMARIES_KEEP = 20

#: L1 的触发门槛与回压比例（§9）：
#:   - 至少攒够这么多条"装不下"的原文才值得花一次模型调用；
#:   - 压缩后回压到预算的这个比例，留出余量，避免**每轮都触发**（那是成本灾难）。
L1_MIN_DROPPED = 4
L1_TARGET_RATIO = 0.7

#: 注入模型的**历史学习摘要条数**（保留上界是 20，注入不必那么多）
INJECT_SESSION_SUMMARIES = 3

#: 这些来源是**基准测量**：直接设定画像分数，而不是平滑合并
_SET_SOURCES = (SOURCE_ASSESSMENT, SOURCE_MIGRATED, SOURCE_SUMMARY)


def _now() -> str:
    """本地时间戳（与 `coach/metrics/recorder.py` 同口径）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _clean_topic(raw) -> str:
    return str(raw or "").strip()


def current_session(state) -> int:
    """当前单次学习序号（0 = 还没有开始过任何一次学习）。"""
    try:
        return max(0, int(state.get("session_seq") or 0))
    except (TypeError, ValueError):
        return 0


def new_session(state) -> int:
    """开始新的一次学习：序号 +1 并返回。

    只在**真的跨过一次学习边界**时调用（见 `cursor.mark_task_done` 的进位）。
    """
    seq = current_session(state) + 1
    state["session_seq"] = seq
    return seq


def evidence_for(state, topic) -> list:
    """取某知识点的证据明细（**独立副本**，改它不影响 state）。"""
    bucket = state.get("evidence")
    if not isinstance(bucket, dict):
        return []
    entries = bucket.get(_clean_topic(topic))
    return [dict(e) for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def _replay(entries, topic: str):
    """按**时间顺序**回放某知识点的证据，返回累计分数（无有效条目返回 None）。

    这是画像的**唯一定义**：新增一条证据后重放，就得到新的画像。
    """
    acc = None
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        try:
            score = round(float(entry.get("score") or 0.0), 2)
        except (TypeError, ValueError):
            continue
        source = str(entry.get("source") or "")
        if source in _SET_SOURCES or acc is None:
            acc = score
        else:
            acc = round((acc + score) / 2, 2)
    return acc


def record_evidence(state, topic, *, source, verdict="", score=None,
                    error_type="", task_id=""):
    """追加一条证据 —— **长期记忆唯一直接写的入口**。

    返回写入的条目；`topic` 为空时**不写**并返回 None（空知识点不得污染画像）。

    `error_type` 落进证据是关键：改造前 `latest_result` 是单槽，
    一旦重做成功，上一次的错误类型就被覆盖，"这个知识点上犯过什么错"永久丢失。
    """
    topic = _clean_topic(topic)
    if not topic:
        return None

    try:
        value = round(float(score), 2) if score is not None else 0.0
    except (TypeError, ValueError):
        value = 0.0

    entry = {
        "at": _now(),
        "session_seq": current_session(state),
        "source": str(source or ""),
        "verdict": str(verdict or ""),
        "score": value,
        "error_type": str(error_type or ""),
        "task_id": str(task_id or ""),
    }

    bucket = state.get("evidence")
    if not isinstance(bucket, dict):
        bucket = {}
    entries = [e for e in (bucket.get(topic) or []) if isinstance(e, dict)]
    entries.append(entry)

    # 上界：只留最近 K 条明细；被丢掉的**降采样成一个锚点**。
    # 不做锚点的话，画像（由证据回放得出）会随截断而漂移 —— 那是静默的画像污染。
    if len(entries) > EVIDENCE_KEEP_PER_TOPIC:
        cut = EVIDENCE_KEEP_PER_TOPIC - 1
        dropped, keep = entries[:-cut], entries[-cut:]
        anchor_score = _replay(dropped, topic)
        if anchor_score is not None:
            last = dropped[-1]
            keep = [{
                "at": last.get("at", ""),
                "session_seq": last.get("session_seq", 0),
                "source": SOURCE_SUMMARY,
                "verdict": "",
                "score": anchor_score,
                "error_type": "",
                "task_id": "",
            }] + keep
        entries = keep

    bucket[topic] = entries
    state["evidence"] = bucket
    return entry


def derive_profile(state) -> dict:
    """由证据**派生**能力画像（**派生视图，不直接写**）。

    等价于改造前的"测评覆盖 + 验收平滑"，只是合并规则收敛到了这一处。
    """
    bucket = state.get("evidence")
    profile: dict = {}
    if not isinstance(bucket, dict):
        return profile
    for raw_topic, entries in bucket.items():
        topic = _clean_topic(raw_topic)
        if not topic:
            continue
        value = _replay(entries, topic)
        if value is not None:
            profile[topic] = value
    return profile


def derive_weak_points_from_state(state) -> list:
    """薄弱点 = 画像低于阈值（与测评阶段同一套规则）。"""
    return derive_weak_points(derive_profile(state))


def derive_due_for_review(state, threshold: int = REVIEW_UNCOVERED_SESSIONS) -> list:
    """**待复验**：连续 `threshold` 次单次学习未覆盖的知识点（最久没碰的排前面）。

    "覆盖" = 该知识点出现过任意一条证据（**无论验收是否通过**）——
    没通过的知识点已经进了 `weak_points` 并被优先安排，不需要再叠一个待复验。

    为什么不用自然日：本项目以"**次**"为基本单位，"连续 8 次单次学习没碰过"
    比"14 天"更贴近真实的遗忘（见 docs/memory-design.md §7）。
    """
    seq = current_session(state)
    bucket = state.get("evidence")
    if not isinstance(bucket, dict) or seq <= 0:
        return []

    due: list = []
    for raw_topic, entries in bucket.items():
        topic = _clean_topic(raw_topic)
        if not topic:
            continue
        last = 0
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            try:
                last = max(last, int(entry.get("session_seq") or 0))
            except (TypeError, ValueError):
                continue
        if seq - last >= threshold:
            due.append((topic, last))

    due.sort(key=lambda item: (item[1], item[0]))
    return [topic for topic, _last in due]


def session_records(state) -> list:
    """取单次学习记录（**独立副本**）。"""
    records = state.get("session_records")
    return [dict(r) for r in records if isinstance(r, dict)] if isinstance(records, list) else []


def upsert_session_record(state, seq=None, **fields) -> dict:
    """写入/更新某次单次学习的记录（L2 定稿摘要的落点，见 memory-design.md §6.2）。

    按 `seq` 唯一：同一序号重复写入是**更新**，不是追加（幂等）。
    """
    try:
        target = int(seq) if seq is not None else current_session(state)
    except (TypeError, ValueError):
        target = current_session(state)

    records = state.get("session_records")
    if not isinstance(records, list):
        records = []

    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            same = int(record.get("seq") or 0) == target
        except (TypeError, ValueError):
            same = False
        if same:
            record.update(fields)
            record["seq"] = target
            state["session_records"] = records
            return record

    record = {"seq": target, "at": _now()}
    record.update(fields)
    records.append(record)
    state["session_records"] = records
    return record


# ---------------------------------------------------------------------------
# 原文层：按**单次学习**分段的归档（§8.2 / I-13）
# ---------------------------------------------------------------------------

def archive_segments(state) -> list:
    """取归档分段（**独立副本**）。"""
    archive = state.get("conversation_archive")
    if not isinstance(archive, list):
        return []
    segments = []
    for segment in archive:
        if not isinstance(segment, dict):
            continue
        messages = segment.get("messages")
        segments.append({
            "session_seq": segment.get("session_seq", 0),
            "messages": [dict(m) for m in messages if isinstance(m, dict)]
            if isinstance(messages, list) else [],
        })
    return segments


def archive_message_count(state) -> int:
    """归档里一共多少条消息（**兼容 v0.17 的扁平结构**）。"""
    archive = state.get("conversation_archive")
    if not isinstance(archive, list):
        return 0
    total = 0
    for segment in archive:
        if not isinstance(segment, dict):
            continue
        messages = segment.get("messages")
        if isinstance(messages, list):
            total += len([m for m in messages if isinstance(m, dict)])
        else:
            total += 1                      # 扁平结构：元素本身就是一条消息
    return total


def append_to_archive(state, messages, seq=None):
    """把消息追加进**当前次学习**的归档分段（没有就新建一个）。返回该分段。"""
    batch = [dict(m) for m in (messages or []) if isinstance(m, dict)]
    if not batch:
        return None

    try:
        target = current_session(state) if seq is None else int(seq)
    except (TypeError, ValueError):
        target = current_session(state)

    archive = state.get("conversation_archive")
    if not isinstance(archive, list):
        archive = []

    segment = None
    if archive:
        last = archive[-1]
        if isinstance(last, dict) and isinstance(last.get("messages"), list):
            try:
                if int(last.get("session_seq") or 0) == target:
                    segment = last
            except (TypeError, ValueError):
                segment = None

    if segment is None:
        segment = {"session_seq": target, "messages": []}
        archive.append(segment)

    segment["messages"].extend(batch)
    state["conversation_archive"] = archive
    return segment


def prune_archive(state, keep: int = ARCHIVE_KEEP_SESSIONS) -> int:
    """只保留最近 @@keep@@ 次单次学习的原文；返回**被丢弃的消息条数**。

    丢弃必须**留痕**（I-13）：调用方拿到返回值后要记一条指标事件。
    改造前这里是 @@del archive[:-500]@@ —— 静默丢弃，用户永远不知道少了什么。
    """
    archive = state.get("conversation_archive")
    if not isinstance(archive, list) or len(archive) <= keep:
        return 0

    dropped, state["conversation_archive"] = archive[:-keep], archive[-keep:]
    total = 0
    for segment in dropped:
        if not isinstance(segment, dict):
            total += 1
            continue
        messages = segment.get("messages")
        total += len(messages) if isinstance(messages, list) else 1
    return total


def select_history(history, budget: int = INJECT_CHAR_BUDGET,
                   min_messages: int = MIN_RAW_MESSAGES) -> list:
    """按**字符预算**从最近往前取对话原文（§6.1）。

    为什么不用固定条数：条数无法适配不同长度的对话 —— 8 条对一次 2 小时的学习太小
    （模型只看得到最近十几分钟），而固定放大又会在短对话里浪费预算。

    **最近 @@min_messages@@ 条无论如何都保留**（少于 3 轮，模型接不上话），
    所以实际长度可能略超预算 —— 这是有意的取舍，不是缺陷。
    """
    items = [m for m in (history or []) if isinstance(m, dict)]
    if not items:
        return []

    used = 0
    picked = []
    for message in reversed(items):
        size = len(str(message.get("content") or ""))
        if picked and used + size > budget:
            break
        picked.append(message)
        used += size
    picked.reverse()

    if len(picked) < min_messages:
        picked = items[-min_messages:]
    return picked


# ---------------------------------------------------------------------------
# 叙事层：确定性骨架 + 定稿摘要（docs/memory-design.md §6.2 / §6.3）
# ---------------------------------------------------------------------------

def current_cycle_skeleton(state, seq=None) -> dict:
    """某一次单次学习的**确定性骨架**（纯代码，不调模型）。

    这是 **I-14 的结构保障**：事实与知识点名**来自代码**，模型只负责"润色"，
    因此摘要既不可能凭空引入一个画像里不存在的知识点，也不可能篡改判定。
    """
    target = current_session(state) if seq is None else int(seq)
    evidence = state.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}

    tasks: list = []
    topics: list = []
    verdicts: dict = {}
    errors: list = []
    for raw_topic, entries in evidence.items():
        topic = _clean_topic(raw_topic)
        if not topic:
            continue
        touched = False
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            try:
                same = int(entry.get("session_seq") or 0) == target
            except (TypeError, ValueError):
                same = False
            if not same:
                continue
            touched = True
            task_id = str(entry.get("task_id") or "")
            if task_id and task_id not in tasks:
                tasks.append(task_id)
            verdict = str(entry.get("verdict") or "")
            if verdict:
                verdicts[task_id or topic] = verdict
            error = str(entry.get("error_type") or "")
            if error and error not in errors:
                errors.append(error)
        if touched:
            topics.append(topic)

    progress = state.get("plan_progress")
    progress = progress if isinstance(progress, dict) else {}
    try:
        attempts = max(0, int(progress.get("attempts") or 0))
    except (TypeError, ValueError):
        attempts = 0

    return {
        "seq": target,
        "tasks": sorted(tasks),
        "topics": topics,
        "verdicts": verdicts,
        "errors": errors,
        "attempts": attempts,
    }


def render_cycle_skeleton(skeleton) -> str:
    """骨架 → 一段**确定性文本**。它同时是模型失败时的兜底摘要（§6.4）。"""
    skeleton = skeleton or {}
    tasks = skeleton.get("tasks") or []
    topics = skeleton.get("topics") or []
    verdicts = skeleton.get("verdicts") or {}
    errors = skeleton.get("errors") or []

    lines = [f"[单次学习 {skeleton.get('seq', 0)}]"]
    if tasks:
        shown = "；".join(f"{t}（{verdicts.get(t, '未记录')}）" for t in tasks)
        lines.append(f"完成任务：{shown}")
    else:
        lines.append("完成任务：（无验收记录）")
    if topics:
        lines.append(f"涉及知识点：{'、'.join(topics)}")
    if errors:
        lines.append(f"卡点/错误：{'、'.join(errors)}")
    if skeleton.get("attempts"):
        lines.append(f"累计验收尝试：{skeleton['attempts']} 次")
    return "\n".join(lines)


def pending_cycle_seq(state):
    """**已结束、但还没定稿摘要**的那一次学习序号；没有则返回 None。

    用 `session_seq`（全局单调）而不是 `day`（每个计划块都会重置）——
    否则第二个计划块的第 1 天会被第一个计划块的标记错误地压掉。

    判定：当前这一次仍在进行中，所以"已结束的"是 `current_session - 1`；
    它大于 `condensed_through_seq` 就说明刚跨过一次边界（因此天然幂等）。
    """
    try:
        condensed = max(0, int(state.get("condensed_through_seq") or 0))
    except (TypeError, ValueError):
        condensed = 0
    finished = current_session(state) - 1
    return finished if finished > condensed else None


def mark_cycle_condensed(state, seq) -> None:
    """记下"已定稿到第几次学习"（幂等标记，防止同一次被反复压缩）。"""
    try:
        state["condensed_through_seq"] = max(0, int(seq))
    except (TypeError, ValueError):
        return


def session_summaries(state) -> list:
    """取定稿摘要（**独立副本**）；最近的在最后。"""
    summaries = state.get("session_summaries")
    return [dict(s) for s in summaries if isinstance(s, dict)] if isinstance(summaries, list) else []


def record_cycle_summary(state, seq, text, topics=None) -> dict:
    """追加一条**定稿摘要**，并把条数裁到上界（§8.2 的 M）。"""
    summaries = state.get("session_summaries")
    if not isinstance(summaries, list):
        summaries = []
    entry = {
        "seq": int(seq),
        "at": _now(),
        "text": str(text or ""),
        "topics": list(topics or []),
    }
    summaries.append(entry)
    if len(summaries) > SESSION_SUMMARIES_KEEP:
        summaries = summaries[-SESSION_SUMMARIES_KEEP:]
    state["session_summaries"] = summaries
    return entry
