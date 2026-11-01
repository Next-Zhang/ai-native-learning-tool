"""Three full-run acceptance protocol. Offline by default; never labels samples reviewed."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_eval import INPUT_KEYS, load_cases, run_case, compare


def readiness(cases):
    errors = []
    if len(cases) < 30:
        errors.append("at least 30 distinct cases required")
    if len({c.get("id") for c in cases}) != len(cases):
        errors.append("duplicate IDs")
    inputs = [json.dumps(c.get("input"), sort_keys=True, ensure_ascii=False) for c in cases]
    if len(set(inputs)) != len(inputs):
        errors.append("duplicate inputs do not count as independent samples")
    for judge in INPUT_KEYS:
        group = [c for c in cases if c.get("judge") == judge]
        if len(group) < 6:
            errors.append(judge + ": fewer than six cases")
        if {c.get("risk") for c in group} != {"normal", "boundary", "adversarial"}:
            errors.append(judge + ": risk coverage incomplete")
        if not any(c.get("critical") is True for c in group):
            errors.append(judge + ": critical case list missing")
    for c in cases:
        if c.get("review_status") != "reviewed" or not str(c.get("reviewer") or "").strip():
            errors.append(str(c.get("id")) + ": human review pending")
        if not isinstance(c.get("critical"), bool):
            errors.append(str(c.get("id")) + ": critical must be boolean")
    return errors


def snapshot():
    paths = sorted([*ROOT.glob("coach/**/*.py"), *ROOT.glob("evals/*.py")])
    digest = sha256()
    for p in paths:
        digest.update(p.relative_to(ROOT).as_posix().encode())
        digest.update(p.read_bytes())
    return {"code_sha256": digest.hexdigest(),
            "prompt_manifest_sha256": sha256((ROOT / "coach/prompts/manifest.json").read_bytes()).hexdigest()}


def summarize(cases, details):
    reports = []
    for run_index in sorted({d["run_index"] for d in details}):
        rows = [d for d in details if d["run_index"] == run_index]
        matched = sum(r["status"] == "match" for r in rows)
        errors = sum(r["status"] == "error" for r in rows)
        compared = len(rows) - errors
        groups = {}
        for field in ("judge", "domain", "risk"):
            bucket = defaultdict(lambda: dict(matched=0, compared=0, errors=0, attempted=0))
            for row in rows:
                stat = bucket[row[field]]
                stat["attempted"] += 1
                stat["errors"] += row["status"] == "error"
                stat["compared"] += row["status"] != "error"
                stat["matched"] += row["status"] == "match"
            groups[field] = dict(bucket)
        critical_failed = [r["id"] for r in rows if r["critical"] and r["status"] != "match"]
        rate = matched / compared if compared else None
        reports.append(dict(run_index=run_index, attempted=len(rows), compared=compared,
                            matched=matched, errors=errors, agreement=rate,
                            critical_failed=critical_failed, groups=groups,
                            passed=len(rows) == len(cases) and errors == 0 and
                            rate is not None and rate >= .9 and not critical_failed))
    return reports


def evaluate(cases, invoke=run_case, comparison=compare, rounds=3):
    if rounds != 3:
        raise ValueError("acceptance requires exactly three complete runs")
    details = []
    for index in range(1, rounds + 1):
        for case in cases:
            row = {k: case[k] for k in ("id", "judge", "domain", "risk")}
            row.update(run_index=index, critical=case.get("critical") is True)
            try:
                actual = invoke(case)
                ok, reason = comparison(case, actual)
                row.update(status="match" if ok else "mismatch", actual=actual, detail=reason)
            except Exception as exc:
                row.update(status="error", actual=None, detail=type(exc).__name__)
            details.append(row)
    runs = summarize(cases, details)
    blockers = readiness(cases)
    return dict(schema_version=1, readiness_errors=blockers, runs=runs, details=details,
                passed=not blockers and len(runs) == 3 and all(r["passed"] for r in runs))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(ROOT / "evals/dataset/acceptance-candidate.jsonl"))
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--allow-holdout", action="store_true")
    parser.add_argument("--freeze-manifest")
    parser.add_argument("--out")
    args = parser.parse_args()
    path = Path(args.dataset)
    cases, errors = load_cases(path)
    if errors:
        print(json.dumps({"schema_errors": errors}, ensure_ascii=False, indent=2))
        return 2
    from coach.config import get_settings
    settings = get_settings()
    config = snapshot()
    config.update(temperature=settings.temperature, protocol_rounds=3,
                  dataset_sha256=sha256(path.read_bytes()).hexdigest(),
                  model=settings.model,
                  base_url=settings.base_url)
    from coach.prompts.catalog import validate_manifest
    blockers = readiness(cases) + validate_manifest()
    print(json.dumps({"cases": len(cases), "judges": dict(Counter(c["judge"] for c in cases)),
                      "readiness_errors": blockers, "configuration": config,
                      "executed": False}, ensure_ascii=False, indent=2))
    if not args.live:
        return 0  # valid candidate inventory is not an acceptance pass
    if blockers or not args.allow_holdout or not args.freeze_manifest or not args.out:
        print("Blocked: reviewed/frozen dataset, --allow-holdout, --freeze-manifest and --out required.")
        return 4
    frozen = json.loads(Path(args.freeze_manifest).read_text(encoding="utf-8"))
    if frozen.get("status") != "frozen" or frozen.get("configuration") != config:
        print("Blocked: freeze configuration mismatch.")
        return 4
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("API key missing")
        return 3
    if Path(args.out).resolve() in {path.resolve(), Path(args.freeze_manifest).resolve()}:
        print("Blocked: output cannot overwrite dataset or freeze manifest.")
        return 4
    result = evaluate(cases)
    result["configuration"] = config
    after = snapshot()
    result["configuration_unchanged"] = (
        after == {k: config[k] for k in after} and
        sha256(path.read_bytes()).hexdigest() == config["dataset_sha256"] and
        get_settings() == settings)

    result["passed"] = result["passed"] and result["configuration_unchanged"]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
