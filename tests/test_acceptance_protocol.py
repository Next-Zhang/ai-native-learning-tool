"""Offline protocol tests; no dataset labels promoted or API calls."""
import copy
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
from acceptance_protocol import evaluate, readiness
from run_eval import load_cases
from _runner import run_tests


def cases():
    data, errors = load_cases(Path(__file__).resolve().parents[1] / "evals/dataset/acceptance-candidate.jsonl")
    assert not errors
    return data


def reviewed_fixture():
    data = copy.deepcopy(cases())
    for c in data:
        c.update(review_status="reviewed", reviewer="fixture-only")
    return data


def test_candidates_cannot_pass_even_with_perfect_model():
    data = cases()
    result = evaluate(data, lambda c: c["expected"], lambda c, a: (a == c["expected"], "fixture"))
    assert result["readiness_errors"] and not result["passed"]


def test_three_complete_runs_and_visible_errors():
    data = reviewed_fixture()
    seen = []
    def invoke(c):
        seen.append(c["id"])
        if len(seen) == 31:
            raise RuntimeError("simulated")
        return c["expected"]
    result = evaluate(data, invoke, lambda c, a: (a == c["expected"], "fixture"))
    assert seen == [c["id"] for c in data] * 3
    assert [r["attempted"] for r in result["runs"]] == [30, 30, 30]
    assert result["runs"][1]["errors"] == 1 and not result["passed"]


def test_critical_failure_not_hidden_by_ninety_percent():
    data = reviewed_fixture()
    target = next(c["id"] for c in data if c["critical"])
    result = evaluate(data, lambda c: {}, lambda c, _: (c["id"] != target, "fixture"))
    assert all(r["agreement"] > .9 for r in result["runs"])
    assert not result["passed"]


def test_all_runs_pass_only_with_reviewed_complete_fixture():
    data = reviewed_fixture()
    assert not readiness(data)
    assert evaluate(data, lambda c: c["expected"], lambda c, a: (a == c["expected"], "fixture"))["passed"]
    data[1]["input"] = data[0]["input"]
    assert readiness(data)


def test_invalid_dataset_shapes_return_errors_without_crashing():
    import json
    from unittest.mock import patch
    body = "[]\n" + json.dumps({"id": ["wrong"]}) + "\n"
    with patch.object(Path, "exists", return_value=True), patch.object(Path, "read_text", return_value=body):
        data, errors = load_cases(Path("virtual.jsonl"))
    assert not data and len(errors) == 2


def test_boolean_labels_are_not_integer_aliases():
    import json
    from unittest.mock import patch
    case = next(c for c in cases() if c["judge"] == "submission_detect")
    case["expected"]["is_submission"] = 1
    with patch.object(Path, "exists", return_value=True), patch.object(Path, "read_text", return_value=json.dumps(case)):
        _, errors = load_cases(Path("virtual.jsonl"))
    assert errors


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
