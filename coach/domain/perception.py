"""感知契约（**F1**）：把每个"模型判定点"的返回统一成一个类型。

要解决的问题
------------
改造前 5+1 个判定点各有各的返回形状，而且**失败与"没什么可判"常常不可区分**：

| 判定点 | 改造前返回 | 不可区分之处 |
|---|---|---|
| `perception.profile_extract` | `UserProfile` | 失败返回空画像，与"用户没说"**完全一致** |
| `perception.plan_confirm` | `ConfirmationVerdict | None` | None 兼表"没有窗口"与"判定失败" |
| `perception.submission_detect` | `SubmissionVerdict | None` | None 兼表"没有任务"/"已有待验收"/"判定失败" |
| `perception.assessment_verdict` | `AnswerRecord | None` | None 兼表"没有进行中的题"与"判定失败" |
| `evaluation.judge` | `EvaluationResult | None` | 同上的两义 None |
| 记忆压缩 L1/L2（v0.18） | `str` | 分不清"模型润色"与"兜底骨架" |

契约（见 `docs/architecture.md` §7.1）
--------------------------------------
::

    PerceptionResult(kind, payload, ok, needs_confirm, raw, error)

不变量（**P-1…P-4**）
--------------------
- **P-1** `ok=False` 时**不得把 payload 当判定结果用**。payload 里允许放**兜底值**
  （"保守记 missing"这类），但调用方不得据此推进阶段或当成真判定。
- **P-2** `payload` 必须经 Pydantic 校验 —— 用 `PerceptionResult.validated()` 构造。
- **P-3** `raw`（原始模型输出）**只进日志与 trace**，不进 state。
- **P-4** 判定失败**保持当前阶段、不推进**（由状态机守卫保证）。

`error` 是 v0.18 在文档 5 个字段之外**新增**的：只有 `ok=False` 不够排查 ——
"为什么失败"与"什么类型的失败"是两件事（如 `no_task` 与 `RuntimeError: network down`）。
"""

from dataclasses import dataclass, field

__all__ = [
    "PERCEPTION_KINDS",
    "PerceptionResult",
    "is_perception_result",
]

#: 全部判定点的 `kind`（注册在这里，新增判定点必须同时登记 —— 有测试把关）。
KIND_PROFILE = "profile"
KIND_PLAN_CONFIRMATION = "plan_confirmation"
KIND_SUBMISSION = "submission"
KIND_ASSESSMENT_VERDICT = "assessment_verdict"
KIND_EVALUATION_VERDICT = "evaluation_verdict"
KIND_CYCLE_SUMMARY = "cycle_summary"
KIND_PROGRESS_SUMMARY = "progress_summary"

PERCEPTION_KINDS = (
    KIND_PROFILE,
    KIND_PLAN_CONFIRMATION,
    KIND_SUBMISSION,
    KIND_ASSESSMENT_VERDICT,
    KIND_EVALUATION_VERDICT,
    KIND_CYCLE_SUMMARY,
    KIND_PROGRESS_SUMMARY,
)


@dataclass(frozen=True)
class PerceptionResult:
    """一个判定点的统一返回。

    `payload` 是**面向 state / 调用方的形式**（dict）：可直接合并进 state、可序列化。
    """

    kind: str
    payload: dict = field(default_factory=dict)
    ok: bool = False
    needs_confirm: bool = False
    raw: str | None = None
    error: str = ""

    # -- 构造 ---------------------------------------------------------------

    @classmethod
    def success(cls, kind: str, payload=None, *, needs_confirm: bool = False,
                raw: str | None = None) -> "PerceptionResult":
        """判定成功。`needs_confirm` 目前恒为 False（留给未来的工具/危险动作判定点）。"""
        return cls(kind=kind, payload=dict(payload or {}), ok=True,
                   needs_confirm=needs_confirm, raw=raw)

    @classmethod
    def validated(cls, kind: str, model, *, needs_confirm: bool = False,
                  raw: str | None = None) -> "PerceptionResult":
        """从 **Pydantic 模型**构造（**P-2**：payload 必须经校验才能进 state）。"""
        if not hasattr(model, "model_dump"):
            raise TypeError("validated() 需要 Pydantic 模型；普通 dict 请用 success()")
        return cls.success(kind, model.model_dump(), needs_confirm=needs_confirm, raw=raw)

    @classmethod
    def failure(cls, kind: str, *, payload=None, error: str = "",
                raw: str | None = None) -> "PerceptionResult":
        """判定失败 / 不适用。`payload` 可放**兜底值**，但调用方不得当判定结果用（P-1）。"""
        return cls(kind=kind, payload=dict(payload or {}), ok=False,
                   needs_confirm=False, raw=raw, error=str(error))

    # -- 读取 ---------------------------------------------------------------

    def get(self, key: str, default=None):
        return self.payload.get(key, default)

    def __bool__(self) -> bool:
        """`if result:` 等价于 `if result.ok:` —— 避免误用"对象非空即真"。

        这一条很重要：`PerceptionResult` 永远是非空对象，若沿用默认真值语义，
        `if result:` 会在**失败时也成立**，正是 P-1 要防的误用。
        """
        return self.ok


def is_perception_result(value) -> bool:
    return isinstance(value, PerceptionResult)
