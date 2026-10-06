r"""测试审计：按**断言对象**给 tests/ 下的用例分类，输出可复核的明细报告。

用法（在 App_landing 目录下）：
    .\.venv\Scripts\python.exe tests\audit.py                 # 打印摘要
    .\.venv\Scripts\python.exe tests\audit.py --list          # 打印逐条明细
    .\.venv\Scripts\python.exe tests\audit.py --out docs\test-audit.md

为什么要做这件事
----------------
测试**数量**是个坏指标。本脚本改为回答结构性问题：
- 这些用例到底在断言什么？（纯函数 / 状态流转 / 持久化 IO / 契约钉桩 / 真实模型）
- 有多少条**根本不会执行**（缺 API Key 时被"跳过"，但报表上表现为通过）？
- 一个真实缺陷（如 X-16 抢答判定）暴露在哪一层？那层有没有测试？

分类是**启发式**的，依据是静态 AST 信号，规则写在报告里；逐条明细一并输出，便于人工推翻。
"""

import argparse
import ast
import json
from collections import Counter, defaultdict
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent

# 层名 -> 中文
LAYER_LABEL = {
    "domain": "domain 纯逻辑",
    "storage": "storage 持久化",
    "services": "services 用例",
    "orchestration": "orchestration 编排",
    "llm": "llm 模型访问",
    "prompts": "prompts 提示词",
    "metrics": "metrics 指标",
    "config": "config 配置",
    "rag": "rag 检索",
}

TIER_LABEL = {
    "live": "live 真实模型（默认跳过）",
    "io": "持久化 / IO",
    "integration": "跨层 / 编排",
    "contract": "契约 / 规格钉桩",
    "pure": "纯函数",
    "behavior": "行为（跨 domain 之外）",
}

# 视为"静态定义"的导入名（全大写常量，或来自 prompts 包的文本常量）
STATIC_SUFFIXES = ("_PROMPT", "_PROMPTS", "DEFAULT_PROMPT")
FS_CALLS = {
    "write_text", "read_text", "mkdir", "rmtree", "copy2", "unlink",
    "exists", "glob", "open", "chmod", "rename", "replace",
}
LLM_TOUCHING = {
    "extract_profile", "ensure_plan", "record_answer", "confirm_plan",
    "generate_plan", "detect_submission", "evaluate", "chat", "json_call", "get_client",
}


def dotted(node) -> str | None:
    """把 Name/Attribute 链还原成点号名字。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def layer_of(dotted_name: str, imports: dict) -> str | None:
    """把被调用名解析到所属层。"""
    if not dotted_name:
        return None
    head = dotted_name.split(".")[0]
    origin = imports.get(head)
    if origin is None:
        return None
    for prefix, layer in (
        ("coach.orchestration", "orchestration"),
        ("coach.services", "services"),
        ("coach.storage", "storage"),
        ("coach.domain", "domain"),
        ("coach.metrics", "metrics"),
        ("coach.llm", "llm"),
        ("coach.prompts", "prompts"),
        ("coach.config", "config"),
        ("rag", "rag"),
    ):
        if origin.startswith(prefix):
            return layer
    return None


def collect_imports(tree) -> tuple[dict, set]:
    """返回 (局部名 -> 完整来源, 静态名集合)。"""
    imports: dict[str, str] = {}
    statics: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local = alias.asname or alias.name
                imports[local] = f"{node.module}.{alias.name}"
                if alias.name.isupper() or alias.name.endswith(STATIC_SUFFIXES):
                    statics.add(local)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                imports[local] = alias.name

    # 从 state_schema / 其他模块导入的常量（在测试里另外赋值给局部名的，靠名字识别）
    return imports, statics


def _env_guard_kind(func) -> tuple[bool, bool, bool]:
    """返回 (live 守卫, 反向守卫, 显式 SkipTest)。

    - **live**：`if not os.getenv("DEEPSEEK_API_KEY"): raise SkipTest(...)`
      —— 缺 Key 就跳过（runner 会单列 SKIP，不计入通过）。
    - **inverse**：`if os.getenv("DEEPSEEK_API_KEY"): ... return`
      —— **只有缺 Key 时才校验**；有 Key 反而什么都不验。（历史上的写法，现已改掉。）
    - **skip_raise**：函数体里出现 `raise SkipTest(...)`。
    """
    live = inverse = skip_raise = False
    for node in ast.walk(func):
        if isinstance(node, ast.Raise) and node.exc is not None:
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            name = dotted(target)
            if name and name.split(".")[-1] == "SkipTest":
                skip_raise = True

        if not isinstance(node, ast.If):
            continue
        names = {
            sub.value for sub in ast.walk(node.test)
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
        }
        if "DEEPSEEK_API_KEY" not in names:
            continue
        negated = isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not)
        if negated:
            live = True
        else:
            inverse = True
    return live, inverse, skip_raise


def analyze_test(func, imports: dict, statics: set) -> dict:
    calls: list[str] = []
    assert_nodes: list[ast.AST] = []
    raise_asserts = 0
    static_refs: set[str] = set()
    touches_fs = False

    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            assert_nodes.append(node)
        # 有些人用 `try/except/else: raise AssertionError(...)` 代替 assert，同样算断言
        if isinstance(node, ast.Raise) and node.exc is not None:
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            name = dotted(target)
            if name and name.split(".")[-1] == "AssertionError":
                raise_asserts += 1
        if isinstance(node, ast.Call):
            name = dotted(node.func)
            if name:
                calls.append(name)
                if name.split(".")[-1] in FS_CALLS:
                    touches_fs = True

    live_guard, inverse_guard, skip_raise = _env_guard_kind(func)
    live_guard = live_guard or skip_raise       # 新约定：raise SkipTest 也是跳过

    # 断言表达式里引用到的静态名
    for node in assert_nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in statics:
                static_refs.add(sub.id)

    coach_calls = [c for c in calls if layer_of(c, imports) is not None]
    layers = {layer_of(c, imports) for c in coach_calls}
    layers.discard(None)

    if live_guard:
        tier = "live"
    elif touches_fs:
        tier = "io"
    elif "orchestration" in layers or any(c.endswith("run_turn") for c in calls):
        tier = "integration"
    elif not coach_calls and static_refs:
        tier = "contract"
    elif layers <= {"domain", "config"}:
        tier = "pure"
    else:
        tier = "behavior"

    return {
        "name": func.name,
        "line": func.lineno,
        "tier": tier,
        "asserts": len(assert_nodes) + raise_asserts,
        "assert_stmts": len(assert_nodes),
        "raise_assertion": raise_asserts,
        "stmts": len(func.body),
        "layers": sorted(layers),
        "coach_calls": len(coach_calls),
        "static_refs": sorted(static_refs),
        "live_guard": live_guard,
        "inverse_guard": inverse_guard,
        "skip_raise": skip_raise,
        "touches_fs": touches_fs,
    }


def analyze_file(path: Path) -> list[dict]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports, statics = collect_imports(tree)
    rows = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            rows.append(analyze_test(node, imports, statics))
    return rows


def build_report(rows_by_file: dict) -> dict:
    all_rows = [r for rows in rows_by_file.values() for r in rows]
    tiers = Counter(r["tier"] for r in all_rows)
    live = [r for r in all_rows if r["live_guard"]]
    inverse = [r for r in all_rows if r["inverse_guard"]]
    executed = [r for r in all_rows if not r["live_guard"]]
    return {
        "total": len(all_rows),
        "live_guard": len(live),
        "inverse_guard": len(inverse),
        "executed_without_key": len(executed),
        "skipped_without_key": len(live),
        "inert_with_key": len(inverse),
        "verify_no_key": len(executed),
        "verify_with_key": len(all_rows) - len(inverse),
        "assert_total": sum(r["asserts"] for r in all_rows),
        "zero_assert": [r["name"] for r in all_rows if r["asserts"] == 0],
        # 「没有显式 assert」不等于「没有验证」：只调用了被测函数、靠"不抛异常"判定
        # 的用例是**隐式断言**（有效）。只有既无断言、又没碰任何被测函数的才是真空用例。
        "zero_assert_vacuous": [
            r["name"] for r in all_rows if r["asserts"] == 0 and r["coach_calls"] == 0
        ],
        "single_assert": sum(1 for r in all_rows if r["asserts"] == 1),
        "tiers": dict(tiers),
        "shallow": [r["name"] for r in executed if r["asserts"] <= 1],
        "live_names": [r["name"] for r in live],
        "inverse_names": [r["name"] for r in inverse],
    }


def render(rows_by_file: dict, report: dict, show_list: bool) -> str:
    lines = []
    total = report["total"]

    lines.append("# 测试审计报告")
    lines.append("")
    lines.append(f"- 用例总数：**{total}**")
    lines.append(f"- **无 Key 时跳过**：**{report['skipped_without_key']}**"
                 f"（live 用例，有 Key 才会真正跑；runner 单列 SKIP，**不计入通过数**）")
    if report["inert_with_key"]:
        lines.append(f"- **有 Key 时反而不做校验**（反向守卫）：**{report['inert_with_key']}**")
    lines.append(f"- → 无 Key 时实际校验 **{report['verify_no_key']}** 条；"
                 f"有 Key 时实际校验 **{report['verify_with_key']}** 条")
    lines.append(f"- assert 语句总数：{report['assert_total']}"
                 f"（平均每用例 {report['assert_total'] / total:.1f} 条）")
    lines.append("")

    lines.append("## 一、按断言对象分层")
    lines.append("")
    lines.append("| 分层 | 用例数 | 占比 |")
    lines.append("|---|---|---|")
    for tier, count in sorted(report["tiers"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {TIER_LABEL[tier]} | {count} | {count / total * 100:.0f}% |")
    lines.append("")

    lines.append("## 二、按文件分层")
    lines.append("")
    header = "| 文件 | 用例 | " + " | ".join(
        TIER_LABEL[t].split(" ")[0] for t in
        ["pure", "behavior", "integration", "io", "contract", "live"]
    ) + " |"
    lines.append(header)
    lines.append("|---|---|" + "---|" * 6)
    for name in sorted(rows_by_file):
        rows = rows_by_file[name]
        counts = Counter(r["tier"] for r in rows)
        cells = " | ".join(str(counts.get(t, 0)) for t in
                           ["pure", "behavior", "integration", "io", "contract", "live"])
        lines.append(f"| `{name}` | {len(rows)} | {cells} |")
    lines.append("")

    lines.append("## 三、发现的问题")
    lines.append("")
    findings = []
    if report["skipped_without_key"]:
        if report.get("runner_supports_skip"):
            findings.append(
                f"✅ **已修复**：{report['skipped_without_key']} 条 live 用例在无 Key 时显式 "
                f"`raise SkipTest`，runner（`tests/_runner.py`，已接入 "
                f"{report.get('files_using_skip')} 个测试文件）单列 SKIP 并**不计入通过数**——"
                f"「{report['verify_no_key']} 通过 / {report['skipped_without_key']} 跳过」"
                f"是诚实读数（数字由本脚本按当前用例数算出，不写死）。"
            )
        else:
            findings.append(
                f"**{report['skipped_without_key']} 条 live 用例在无 Key 时提前 return，"
                f"但 runner 记为 [PASS]** —— 报表上的「全绿」会掩盖它们从未运行。"
            )
    if report["inert_with_key"]:
        findings.append(
            f"**另有 {report['inert_with_key']} 条是反向守卫**（`if os.getenv(...)` 直接 return）："
            f"它们**只在缺 Key 时校验失败兜底**，一旦配了 Key 就什么都不验。"
            f"名单：{'、'.join(report['inverse_names'])}"
        )
    vacuous = report["zero_assert_vacuous"]
    implicit = [name for name in report["zero_assert"] if name not in vacuous]
    if vacuous:
        findings.append(
            f"**{len(vacuous)} 条是真空用例**（既无显式断言、也没有调用任何被测函数）：{vacuous}"
        )
    if implicit:
        findings.append(
            f"（信息性）**{len(implicit)} 条没有显式 `assert`**：{implicit} —— "
            "属「调用后不抛异常」型**隐式断言**（被测函数一旦抛错，用例即失败），"
            "仍然有效，此处仅作提示。"
        )
    if report["shallow"]:
        findings.append(
            f"（信息性）**{len(report['shallow'])} 条断言 ≤ 1 处**——不一定有问题，"
            "但薄断言容易在重构后失去意义，值得抽查（含上面那些没有显式断言的用例）。"
        )
    contract = [r for rows in rows_by_file.values() for r in rows if r["tier"] == "contract"]
    if contract:
        findings.append(
            f"**{len(contract)} 条是契约钉桩**（只断言常量/提示词文本，不调用任何被测函数）："
            "它们能防误删，但**不证明任何行为**——X-16 的第一次修复正是"
            "「提示词写对了、测试也过了」却仍然翻车。"
        )
    for item in findings:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## 四、分类规则（启发式，可按明细推翻）")
    lines.append("")
    lines.append("按顺序判定，先命中先归类：")
    lines.append("")
    lines.append("1. `live` —— 函数体内出现 `DEEPSEEK_API_KEY` 判空（真调模型，无 Key 时跳过）")
    lines.append("2. `io` —— 调用文件系统（`write_text`/`read_text`/`mkdir`/`rmtree`/`copy2`/`unlink`/`open`…）")
    lines.append("3. `integration` —— 触及 `coach.orchestration` 或调用 `run_turn`")
    lines.append("4. `contract` —— **没有调用任何被测函数**，但断言里引用了导入的静态名（常量 / 提示词文本）")
    lines.append("5. `pure` —— 所有被测调用都落在 `coach.domain` / `coach.config`")
    lines.append("6. `behavior` —— 其余（跨 domain 之外的服务调用）")
    lines.append("")

    if show_list:
        lines.append("## 五、逐条明细")
        lines.append("")
        lines.append("| 文件 | 用例 | 分层 | assert | 触及层 | 静态引用 |")
        lines.append("|---|---|---|---|---|---|")
        for name in sorted(rows_by_file):
            for r in rows_by_file[name]:
                layers = "/".join(r["layers"]) or "—"
                statics = "/".join(r["static_refs"]) or "—"
                lines.append(
                    f"| {name.replace('test_', '').replace('.py', '')} | {r['name']} "
                    f"| {TIER_LABEL[r['tier']].split(' ')[0]} | {r['asserts']} "
                    f"| {layers} | {statics} |"
                )
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="测试审计（按断言对象分类）")
    parser.add_argument("--list", action="store_true", help="打印逐条明细")
    parser.add_argument("--out", help="把报告写入 Markdown 文件")
    parser.add_argument("--json", help="把结构化结果写入 JSON 文件")
    args = parser.parse_args()

    rows_by_file = {
        path.name: analyze_file(path)
        for path in sorted(TESTS_DIR.glob("test_*.py"))
    }
    rows_by_file = {k: v for k, v in rows_by_file.items() if v}
    report = build_report(rows_by_file)
    report["runner_supports_skip"] = (TESTS_DIR / "_runner.py").exists()
    report["files_using_skip"] = sum(
        1 for path in TESTS_DIR.glob("test_*.py")
        if "SkipTest" in path.read_text(encoding="utf-8")
    )
    text = render(rows_by_file, report, show_list=args.list)

    print(text)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"\n报告已写入：{out}")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"report": report, "rows": rows_by_file}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"结构化结果已写入：{out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
