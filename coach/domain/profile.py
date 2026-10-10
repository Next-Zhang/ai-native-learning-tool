"""用户画像：五维度的统一视图与**渲染出口**（PRD §2.5 / architecture.md §12）。

为什么需要它
------------
v0.15 里同一份画像被**手工拼了三遍**，而且三份不一致：

| 位置 | 拼了什么 | 漏了什么 |
|---|---|---|
| `generate_roadmap` | 目标 / 水平 / 时长 / 期限 / 薄弱点 / 画像 | — |
| `generate_plan` | 上述 + 每周次数 + 里程碑 | — |
| `describe_known_profile`（喂给教练对话） | 只有 5 个画像字段 | ❌ **`skill_profile` / `weak_points`** |

后果：**方案生成知道你的薄弱点，但跟你对话的教练不知道**（缺陷 **X-18**）。

本模块提供**唯一渲染出口** `render_profile()`，所有消费方共用 ——
新增维度会**自动进入所有消费点**，不会再出现"某个地方漏了一个字段"。

关于状态结构
------------
当前 state 仍是**扁平**的（4 区重构见 PRD §2.5.6，尚未落地）。本模块是**适配层**：
内部读扁平字段，对外只暴露五维度。将来 state 改成 4 区时，**只需改这里**。

维度与"用在哪"
--------------
| 维度 | 用在哪 |
|---|---|
| a 起点水平 | 跳过什么 + 先做什么 |
| b 目标用途 | 教什么 + 场景 + 深度 |
| c 时间节奏 | 任务切多大 + 窗口多长 |
| d 学习偏好 | 怎么讲 + 例子类型 + 语气 |
| e 表现进度 | 下一轮改什么 + 速度重估 |

**I-11（自评 ≠ 判定）**：`current_level` 只是**自评初值**，渲染时必须标明
"仅参考、非判定"；只有测评 / 验收的结果才写进能力画像。
"""

from coach.domain.assessment_rules import WEAK_THRESHOLD

__all__ = [
    "LEVEL_MASTERED",
    "level_bands",
    "render_profile",
]

#: 分档阈值。判定只来自**测评 / 验收**（I-11），自评不参与分档。
LEVEL_MASTERED = 0.8


def level_bands(state) -> dict:
    """把 `skill_profile` 的分数切成三档清单。

    - `mastered`：≥ 0.8 —— 已经会了
    - `learning`：0.6 ~ 0.8 —— 半懂，需要巩固
    - `gaps`：< 0.6 —— 缺失，**优先安排**（与 `weak_points` 同源）
    """
    scores = state.get("skill_profile") or {}
    mastered: list[str] = []
    learning: list[str] = []
    gaps: list[str] = []
    for topic, raw in scores.items():
        try:
            score = float(raw)
        except (TypeError, ValueError):
            continue
        if score >= LEVEL_MASTERED:
            mastered.append(str(topic))
        elif score >= WEAK_THRESHOLD:
            learning.append(str(topic))
        else:
            gaps.append(str(topic))
    return {
        "mastered": sorted(mastered),
        "learning": sorted(learning),
        "gaps": sorted(gaps),
        "scores": dict(scores),
    }


def render_profile(state) -> str:
    """五维度 → 一段权威状态文本。**所有消费方共用**。

    只陈述**已知事实**，不承诺系统尚未实现的行为（例如不写"已掌握的会被跳过"，
    因为当前还没有那个逻辑）。
    """
    if not state:
        return ""

    lines: list[str] = []

    # ── b 目标与用途 ──
    if state.get("learning_goal"):
        lines.append(f"- 学习目标：{state['learning_goal']}")
    # I-11：自评只是参考，必须显式标明，避免模型把它当判定
    if state.get("current_level"):
        lines.append(f"- 自评水平（**仅参考，非判定**）：{state['current_level']}")

    # ── c 时间与节奏 ──
    if state.get("session_minutes"):
        lines.append(f"- 单次可投入：{state['session_minutes']} 分钟")
    if state.get("target_date"):
        lines.append(f"- 期望期限：{state['target_date']}")
    if state.get("sessions_per_week"):
        lines.append(f"- 每周大约：约 {state['sessions_per_week']} 次/周")

    # ── a 起点水平（**判定**，来自测评 / 验收）──
    bands = level_bands(state)
    if bands["scores"]:
        lines.append(f"- 能力画像（判定）：{bands['scores']}")
    if state.get("weak_points"):
        weak = "、".join(str(t) for t in state["weak_points"] if t)
        if weak:
            lines.append(f"- 薄弱点（**优先安排**）：{weak}")
    if bands["mastered"]:
        lines.append(f"- 已掌握的知识点：{'、'.join(bands['mastered'])}")

    # ── d 学习偏好 ──
    prefs = state.get("preferences") or {}
    if isinstance(prefs, dict) and prefs:
        shown = "；".join(f"{k}={v}" for k, v in prefs.items() if k != "source")
        if shown:
            lines.append(f"- 学习偏好：{shown}")

    # ── e 表现与进度 ──
    progress = state.get("plan_progress") or {}
    if isinstance(progress, dict) and progress:
        done = len(progress.get("completed") or [])
        attempts = progress.get("attempts")
        if done or attempts:
            lines.append(f"- 本窗口进度：已完成 {done} 个任务，验收尝试 {attempts or 0} 次")

    return "\n".join(lines)
