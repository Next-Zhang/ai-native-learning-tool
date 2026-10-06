r"""评测集 runner —— 度量 M-01「判分一致率」（PRD §3.3.2）。

用法（在 App_landing 目录下）：

    # 1) 默认 dry-run：只校验数据集格式与分布，不调用模型、不花钱
    .\.venv\Scripts\python.exe evals\run_eval.py
    .\.venv\Scripts\python.exe evals\run_eval.py --dataset holdout

    # 2) 真实评测（需要 DEEPSEEK_API_KEY）
    .\.venv\Scripts\python.exe evals\run_eval.py --live
    .\.venv\Scripts\python.exe evals\run_eval.py --live --repeat 3

    # 3) 导出结果
    .\.venv\Scripts\python.exe evals\run_eval.py --live --format csv --out evals\results\m01.csv

    # 4) 查看评测集（只读渲染，不调模型）
    .\.venv\Scripts\python.exe evals\run_eval.py --show
    .\.venv\Scripts\python.exe evals\run_eval.py --show --filter evaluation
    .\.venv\Scripts\python.exe evals\run_eval.py --export-md evals\dataset_overview.md

设计要点：
- **dry-run 是默认**：避免误跑真实 API。只有显式 --live 才会调模型。
- **分层报告**：总体一致率 + 按 judge + 按 domain（PRD §3.3.4：关键分层不得被总体均值掩盖）。
- **error 单列不计入分母**：模型调用失败必须醒目，否则会把"接口挂了"误读成"判得准"。
- **holdout 保护**：对 holdout 跑 --live 需额外 --allow-holdout，落实 PRD §3.3.1 防泄漏规则。
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

EVALS_DIR = Path(__file__).resolve().parent
DATASET_DIR = EVALS_DIR / "dataset"

REQUIRED_FIELDS = ("id", "domain", "judge", "risk", "input", "expected", "rubric")
VALID_DOMAINS = {"programming", "psychology"}
VALID_RISKS = {"normal", "boundary", "adversarial"}

INPUT_KEYS = {
    "assessment_verdict": {"topic", "coach_reply", "user_answer"},
    "evaluation_completion": {"task", "submission"},
    "submission_detect": {"task", "user_input"},
    "plan_confirm": {"plan", "user_input"},
    "profile_extract": {"text"},
}

EXPECTED_KEYS = {
    "assessment_verdict": {"verdict"},
    "evaluation_completion": {"completion", "next_action"},
    "submission_detect": {"is_submission"},
    "plan_confirm": {"confirmed"},
    "profile_extract": {
        "learning_goal_keywords",
        "current_level_keywords",
        "session_minutes",
        "target_date",
    },
}

VALID_VERDICTS = {"mastered", "partial", "missing"}
VALID_COMPLETIONS = {"completed", "partial", "not_completed"}
VALID_ACTIONS = {"pass", "retry", "supplement"}


# ---------------------------------------------------------------------------
# 数据集加载与校验
# ---------------------------------------------------------------------------

def resolve_dataset(name: str) -> Path:
    """把 dev / holdout / 路径 解析成实际文件路径。"""
    candidate = Path(name)
    if candidate.exists():
        return candidate
    return DATASET_DIR / f"{name}.jsonl"


def load_cases(path: Path):
    """读取 JSONL，返回 (cases, errors)。"""
    errors: list[str] = []
    cases: list[dict] = []

    if not path.exists():
        return [], [f"数据集不存在：{path}"]

    seen_ids: set[str] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"第 {lineno} 行 JSON 解析失败：{exc}")
            continue

        case_id = case.get("id") or f"<第 {lineno} 行>"
        if case_id in seen_ids:
            errors.append(f"[{case_id}] id 重复")
        seen_ids.add(case_id)

        for field in REQUIRED_FIELDS:
            if field not in case:
                errors.append(f"[{case_id}] 缺少必填字段：{field}")

        judge = case.get("judge")
        if judge not in INPUT_KEYS:
            errors.append(f"[{case_id}] 未知 judge：{judge!r}")
            cases.append(case)
            continue

        if case.get("domain") not in VALID_DOMAINS:
            errors.append(f"[{case_id}] domain 非法：{case.get('domain')!r}")
        if case.get("risk") not in VALID_RISKS:
            errors.append(f"[{case_id}] risk 非法：{case.get('risk')!r}")

        missing_in = INPUT_KEYS[judge] - set((case.get("input") or {}).keys())
        if missing_in:
            errors.append(f"[{case_id}] input 缺少字段：{sorted(missing_in)}")

        got_exp = set((case.get("expected") or {}).keys())
        missing_exp = EXPECTED_KEYS[judge] - got_exp
        extra_exp = got_exp - EXPECTED_KEYS[judge]
        if missing_exp:
            errors.append(f"[{case_id}] expected 缺少字段：{sorted(missing_exp)}")
        if extra_exp:
            errors.append(f"[{case_id}] expected 存在多余字段：{sorted(extra_exp)}")

        exp = case.get("expected") or {}
        if judge == "assessment_verdict" and exp.get("verdict") not in VALID_VERDICTS:
            errors.append(f"[{case_id}] verdict 非法：{exp.get('verdict')!r}")
        if judge == "evaluation_completion":
            if exp.get("completion") not in VALID_COMPLETIONS:
                errors.append(f"[{case_id}] completion 非法：{exp.get('completion')!r}")
            if exp.get("next_action") not in VALID_ACTIONS:
                errors.append(f"[{case_id}] next_action 非法：{exp.get('next_action')!r}")

        if not (case.get("rubric") or "").strip():
            errors.append(f"[{case_id}] rubric 为空——期望必须有可复核依据")

        cases.append(case)

    return cases, errors


def describe_distribution(cases) -> str:
    """输出 judge × domain 与 risk 分布，便于人工确认覆盖度。"""
    grid: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    risk_grid: dict[str, int] = defaultdict(int)
    for case in cases:
        grid[case.get("judge", "?")][case.get("domain", "?")] += 1
        risk_grid[case.get("risk", "?")] += 1

    domains = sorted(VALID_DOMAINS)
    lines = ["分布（judge × domain）：", f"{'judge':<24}{'编程':>8}{'心理学':>10}{'小计':>8}"]
    for judge in sorted(grid):
        per = grid[judge]
        prog = per.get("programming", 0)
        psy = per.get("psychology", 0)
        lines.append(f"{judge:<24}{prog:>8}{psy:>10}{prog + psy:>8}")
    lines.append("")
    lines.append("风险分层：" + "、".join(f"{k}={risk_grid[k]}" for k in sorted(risk_grid)))
    total_prog = sum(1 for c in cases if c.get("domain") == "programming")
    total_psy = sum(1 for c in cases if c.get("domain") == "psychology")
    lines.append(f"合计：{len(cases)} 条（编程 {total_prog} / 心理学 {total_psy}）")
    lines.append("（domain 取值：" + "、".join(domains) + "）")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 查看器：把 JSONL 渲染成可读形式 / Markdown 总览
# ---------------------------------------------------------------------------

def filter_cases(cases, keyword: str | None) -> list[dict]:
    """按 id / judge / domain / risk 做大小写不敏感的子串过滤。"""
    if not keyword:
        return cases
    needle = keyword.lower()
    return [
        case for case in cases
        if needle in str(case.get("id", "")).lower()
        or needle in str(case.get("judge", "")).lower()
        or needle in str(case.get("domain", "")).lower()
        or needle in str(case.get("risk", "")).lower()
    ]


def _render_value(value, indent: int = 4) -> str:
    """把嵌套的 dict / list 渲染成缩进文本，便于终端阅读。"""
    pad = " " * indent
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(_render_value(item, indent + 2))
            elif isinstance(item, str) and "\n" in item:
                # 多行值（如用户提交的代码）另起一块，续行统一缩进
                lines.append(f"{pad}{key}:")
                lines.append(_render_value(item, indent + 2))
            else:
                lines.append(f"{pad}{key}: {item}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return f"{pad}[]"
        lines = []
        for item in value:
            if isinstance(item, dict):
                lines.append(_render_value(item, indent))
            else:
                lines.append(f"{pad}- {item}")
        return "\n".join(lines)
    text = str(value)
    if "\n" in text:
        # 多行文本（如用户提交的代码）续行也要缩进，否则读起来会跑出层级
        return "\n".join(f"{pad}{line}" for line in text.splitlines())
    return f"{pad}{text}"


def print_case(case) -> None:
    """单条用例的可读输出。"""
    print(f"\n[{case['id']}] {case['domain']} · {case['judge']} · {case['risk']}")
    print("  输入：")
    print(_render_value(case["input"], 4))
    print("  期望：")
    print(_render_value(case["expected"], 4))
    print(f"  判定依据：{case['rubric']}")
    # `notes` 是 schema.md §2 声明的可选字段（补充说明 / 已知争议点），
    # 必须在查看器里显示出来 —— 否则标注者写进 notes 的争议点在复核时看不见。
    if case.get("notes"):
        print(f"  备注：{case['notes']}")


def write_markdown(cases, path: Path, title: str = "评测集总览") -> None:
    """导出 Markdown 总览，便于在编辑器里逐条评审标签。"""
    lines = [
        f"# {title}",
        "",
        f"共 {len(cases)} 条用例。由 `evals/run_eval.py --export-md` 自动生成，**请勿手工编辑**。",
        "",
        "| ID | 领域 | 判定点 | 风险 |",
        "|---|---|---|---|",
    ]
    for case in cases:
        lines.append(
            f"| {case['id']} | {case['domain']} | {case['judge']} | {case['risk']} |"
        )
    lines.append("")

    for case in cases:
        lines.append(f"## {case['id']}")
        lines.append("")
        lines.append(f"- 领域：`{case['domain']}`　判定点：`{case['judge']}`　风险：`{case['risk']}`")
        lines.append("")
        lines.append("**输入**")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(case["input"], ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
        lines.append("**期望**")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(case["expected"], ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
        lines.append(f"**判定依据**：{case['rubric']}")
        lines.append("")
        if case.get("notes"):
            lines.append(f"**备注**：{case['notes']}")
            lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")



# ---------------------------------------------------------------------------
# 被测判定点的调用与比对
# ---------------------------------------------------------------------------

class CaseError(Exception):
    """模型调用失败 —— 计为 error，不计入一致率分母。"""


def _task_of(case) -> dict:
    task = dict(case["input"].get("task") or {})
    task.setdefault("day", 1)
    task.setdefault("task", 1)
    task.setdefault("theme", task.get("goal", ""))
    return task


def run_case(case) -> dict:
    """调用被测判定点，返回实际输出字典；失败抛 CaseError。"""
    judge = case["judge"]

    if judge == "assessment_verdict":
        from coach.services import assessment

        state = {
            "assessment_progress": {
                "plan": [
                    {
                        "index": 1,
                        "topic": case["input"]["topic"],
                        "difficulty": 1,
                    }
                ],
                "records": [],
                "finished": False,
            }
        }
        record = assessment.record_answer(
            state, case["input"]["user_answer"], case["input"]["coach_reply"]
        )
        if record is None:
            raise CaseError("record_answer 返回 None")
        if record.note == "判定调用失败":
            raise CaseError("判定调用失败（已按 missing 兜底，不计入一致率）")
        return {"verdict": record.verdict}

    if judge == "evaluation_completion":
        from coach.services import evaluation

        state = {
            "today_task": _task_of(case),
            "pending_submission": {"content": case["input"]["submission"].get("content", "")},
        }
        result = evaluation.evaluate(state)
        if result is None:
            raise CaseError("evaluate 返回 None（判定失败）")
        return {"completion": result.completion, "next_action": result.next_action}

    if judge == "submission_detect":
        from coach.services import daily_task

        state = {"today_task": _task_of(case)}
        verdict = daily_task.detect_submission(state, case["input"]["user_input"])
        if verdict is None:
            raise CaseError("detect_submission 返回 None（判定失败）")
        return {"is_submission": verdict.is_submission}

    if judge == "plan_confirm":
        from coach.services import planning

        state = {"current_window": case["input"]["plan"], "plan_confirmed": False}
        verdict = planning.confirm_plan(state, case["input"]["user_input"])
        if verdict is None:
            raise CaseError("confirm_plan 返回 None（判定失败）")
        return {"confirmed": verdict.confirmed}

    if judge == "profile_extract":
        from coach.services import profile as profile_service

        profile = profile_service.extract_profile(case["input"]["text"])
        return {
            "learning_goal": profile.learning_goal,
            "current_level": profile.current_level,
            "session_minutes": profile.session_minutes,
            "target_date": profile.target_date,
        }

    raise CaseError(f"未实现的 judge：{judge}")


def _keywords_ok(value, keywords) -> bool:
    """空关键字列表表示"该字段必须为空"；否则要求全部关键字出现（大小写不敏感）。"""
    if not keywords:
        return value in (None, "", [])
    if not isinstance(value, str):
        return False
    low = value.lower()
    return all(str(k).lower() in low for k in keywords)


def compare(case, actual) -> tuple[bool, str]:
    """比对实际输出与期望，返回 (是否一致, 说明)。"""
    judge = case["judge"]
    exp = case["expected"]

    if judge in ("assessment_verdict", "submission_detect", "plan_confirm"):
        # 这三类各只有**一个**期望字段，直接按 schema 解包取键 ——
        # 不用 next(iter(exp))：那会把"expected 只有一键"这个前提藏进字典的迭代顺序里。
        (key,) = EXPECTED_KEYS[judge]
        ok = actual.get(key) == exp.get(key)
        return ok, f"{key} 期望={exp.get(key)!r} 实际={actual.get(key)!r}"

    if judge == "evaluation_completion":
        bad = [k for k in exp if actual.get(k) != exp[k]]
        if not bad:
            return True, "completion/next_action 均一致"
        detail = "；".join(f"{k} 期望={exp[k]!r} 实际={actual.get(k)!r}" for k in bad)
        return False, detail

    if judge == "profile_extract":
        bad: list[str] = []
        if not _keywords_ok(
            actual.get("learning_goal"), exp.get("learning_goal_keywords") or []
        ):
            bad.append(f"learning_goal 期望含{exp.get('learning_goal_keywords')} 实际={actual.get('learning_goal')!r}")
        if not _keywords_ok(
            actual.get("current_level"), exp.get("current_level_keywords") or []
        ):
            bad.append(f"current_level 期望含{exp.get('current_level_keywords')} 实际={actual.get('current_level')!r}")
        if actual.get("session_minutes") != exp.get("session_minutes"):
            bad.append(f"session_minutes 期望={exp.get('session_minutes')!r} 实际={actual.get('session_minutes')!r}")
        actual_td = actual.get("target_date")
        if isinstance(actual_td, str):
            actual_td = actual_td.strip() or None
        if (actual_td or None) != (exp.get("target_date") or None):
            bad.append(f"target_date 期望={exp.get('target_date')!r} 实际={actual.get('target_date')!r}")
        if not bad:
            return True, "四字段均一致"
        return False, "；".join(bad)

    return False, f"未知 judge：{judge}"


# ---------------------------------------------------------------------------
# 报告与导出
# ---------------------------------------------------------------------------

def print_layered(title: str, buckets: dict) -> None:
    """打印分层一致率。buckets: key -> [matched, total, error]"""
    print(f"\n{title}")
    print(f"{'分层':<26}{'一致':>6}{'比对':>6}{'错误':>6}{'一致率':>9}")
    for key in sorted(buckets):
        matched, total, error = buckets[key]
        rate = f"{matched / total * 100:.1f}%" if total else "n/a"
        print(f"{key:<26}{matched:>6}{total:>6}{error:>6}{rate:>9}")


def main() -> int:
    parser = argparse.ArgumentParser(description="M-01 判分一致率评测")
    parser.add_argument("--dataset", default="dev", help="dev | holdout | 自定义 jsonl 路径")
    parser.add_argument("--live", action="store_true", help="真正调用模型（默认 dry-run）")
    parser.add_argument("--repeat", type=int, default=1, help="每条用例重复运行次数")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0=全部；用于快速自检）")
    parser.add_argument("--show", action="store_true", help="以可读形式列出用例（不调模型）")
    parser.add_argument("--export-md", metavar="PATH", help="把用例导出为 Markdown 总览（便于逐条评审标签）")
    parser.add_argument("--filter", help="按 id/judge/domain/risk 子串过滤（配合 --show / --export-md）")
    parser.add_argument("--format", choices=["jsonl", "csv"], default="jsonl")
    parser.add_argument("--out", help="结果导出路径（默认 evals/results/ 下带时间戳）")
    parser.add_argument(
        "--allow-holdout",
        action="store_true",
        help="允许对 holdout 跑 --live（防泄漏：holdout 只用于发布判断）",
    )
    args = parser.parse_args()

    dataset_path = resolve_dataset(args.dataset)
    cases, errors = load_cases(dataset_path)

    print(f"数据集：{dataset_path}")
    print(f"用例数：{len(cases)}")

    if errors:
        print(f"\n[数据集校验失败] 共 {len(errors)} 处问题：")
        for item in errors[:50]:
            print(f"  - {item}")
        return 2

    print("\n[数据集校验通过]")
    print(describe_distribution(cases))

    if args.filter:
        cases = filter_cases(cases, args.filter)
        print(f"\n[--filter {args.filter}] 命中 {len(cases)} 条")

    if args.limit and args.limit > 0:
        cases = cases[: args.limit]
        print(f"\n[--limit {args.limit}] 本次只处理前 {len(cases)} 条")

    # 查看模式：只读渲染，不调模型
    if args.show:
        for case in cases:
            print_case(case)
        print(f"\n共 {len(cases)} 条用例。")
        return 0

    if args.export_md:
        out_md = Path(args.export_md)
        write_markdown(cases, out_md, title=f"评测集总览（{dataset_path.stem}）")
        print(f"\n已导出 Markdown 总览：{out_md}")
        return 0

    is_holdout = dataset_path.name.startswith("holdout")

    if not args.live:
        print("\n" + "=" * 64)
        print("DRY-RUN：未调用模型。加 --live 才会真正评测（需要 DEEPSEEK_API_KEY）。")
        if is_holdout:
            print("注：holdout 用于发布判断，跑 --live 需额外加 --allow-holdout。")
        print("=" * 64)
        return 0

    if not os.getenv("DEEPSEEK_API_KEY"):
        print("\n[错误] --live 需要环境变量 DEEPSEEK_API_KEY，当前未设置。")
        return 3

    if is_holdout and not args.allow_holdout:
        print(
            "\n[已阻止] holdout 是独立验收集，只用于发布判断。\n"
            "若确为发布决策，请显式加 --allow-holdout；调提示词请改用 --dataset dev。"
        )
        return 4

    repeat = max(1, args.repeat)
    if repeat > 1:
        print(f"\n重复运行：每条 {repeat} 次")

    by_judge: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    by_domain: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    by_risk: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    overall = [0, 0, 0]                      # matched, compared, error
    case_all_match: dict[str, bool] = {}
    details: list[dict] = []

    for case in cases:
        runs = []
        for _ in range(repeat):
            try:
                actual = run_case(case)
            except CaseError as exc:
                runs.append({"status": "error", "detail": str(exc), "actual": None})
                continue
            ok, detail = compare(case, actual)
            runs.append(
                {"status": "match" if ok else "mismatch", "detail": detail, "actual": actual}
            )

        matched = sum(1 for r in runs if r["status"] == "match")
        errored = sum(1 for r in runs if r["status"] == "error")
        compared = repeat - errored

        overall[0] += matched
        overall[1] += compared
        overall[2] += errored
        by_judge[case["judge"]][0] += matched
        by_judge[case["judge"]][1] += compared
        by_judge[case["judge"]][2] += errored
        by_domain[case["domain"]][0] += matched
        by_domain[case["domain"]][1] += compared
        by_domain[case["domain"]][2] += errored
        by_risk[case["risk"]][0] += matched
        by_risk[case["risk"]][1] += compared
        by_risk[case["risk"]][2] += errored

        case_all_match[case["id"]] = bool(runs) and all(
            r["status"] == "match" for r in runs
        )

        flag = "OK  " if case_all_match[case["id"]] else ("ERR " if errored else "FAIL")
        print(f"[{flag}] {case['id']} ({case['judge']}/{case['domain']})")
        for r in runs:
            if r["status"] != "match":
                print(f"        {r['status']}: {r['detail']}")

        details.append(
            {
                "id": case["id"],
                "judge": case["judge"],
                "domain": case["domain"],
                "risk": case["risk"],
                "runs": runs,
                "all_match": case_all_match[case["id"]],
            }
        )

    matched, compared, errored = overall
    rate = f"{matched / compared * 100:.1f}%" if compared else "n/a"
    print("\n" + "=" * 64)
    print(f"总体一致率（M-01）：{rate}  （一致 {matched} / 比对 {compared}，错误 {errored}）")
    print_layered("按 judge 分层：", by_judge)
    print_layered("按 domain 分层：", by_domain)
    print_layered("按 risk 分层：", by_risk)

    stable = sum(1 for v in case_all_match.values() if v)
    print(f"\n全次一致的用例：{stable}/{len(cases)}")
    print("阈值：M-01 ≥90%，当前状态【待定】（PRD §3.7 O-02，先测基线再定）。")
    if errored:
        print(f"⚠ 有 {errored} 次调用失败计入 error，未参与一致率——请先排查接口再解读结果。")
    print("=" * 64)

    out_path = Path(args.out) if args.out else (
        EVALS_DIR / "results" / f"m01_{dataset_path.stem}_{datetime.now():%Y%m%d_%H%M%S}.{args.format}"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.format == "csv":
        with out_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["id", "judge", "domain", "risk", "run", "status", "detail"])
            for item in details:
                for index, run in enumerate(item["runs"], start=1):
                    writer.writerow(
                        [item["id"], item["judge"], item["domain"], item["risk"],
                         index, run["status"], run["detail"]]
                    )
    else:
        with out_path.open("w", encoding="utf-8") as fh:
            for item in details:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"\n结果已导出：{out_path}")
    return 0 if not errored else 1


if __name__ == "__main__":
    raise SystemExit(main())
