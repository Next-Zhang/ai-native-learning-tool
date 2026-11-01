"""Versioned inventory of shipped prompts; does not change their runtime text."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
import re

from coach.prompts import stages, tasks


@dataclass(frozen=True)
class PromptSpec:
    id: str
    version: str
    text: str
    purpose: str
    output: str
    contract: str
    acceptance: tuple[str, ...]
    status: str = "legacy_current"

    @property
    def digest(self):
        return sha256(self.text.encode("utf-8")).hexdigest()

    def metadata(self):
        return {"id": self.id, "version": self.version, "sha256": self.digest,
                "purpose": self.purpose, "output": self.output, "contract": self.contract,
                "acceptance": list(self.acceptance), "status": self.status}


_TASKS = {
    "EXTRACT_SYSTEM_PROMPT": ("profile.extract", "JSON", "UserProfile", ("AC-01", "AC-02")),
    "ASSESSMENT_PLAN_SYSTEM_PROMPT": ("assessment.plan", "JSON", "AssessmentPlan", ("AC-24",)),
    "ASSESSMENT_JUDGE_SYSTEM_PROMPT": ("assessment.judge", "JSON", "AnswerRecord", ("AC-05", "AC-07")),
    "ROADMAP_SYSTEM_PROMPT": ("planning.roadmap", "JSON", "roadmap", ("AC-03", "AC-25")),
    "PLAN_SYSTEM_PROMPT": ("planning.window", "JSON", "window", ("AC-04", "AC-25")),
    "CONFIRM_SYSTEM_PROMPT": ("planning.confirm", "JSON", "ConfirmationVerdict", ("AC-03", "AC-14")),
    "SUBMISSION_SYSTEM_PROMPT": ("submission.detect", "JSON", "SubmissionVerdict", ("AC-06",)),
    "EVALUATION_JUDGE_SYSTEM_PROMPT": ("evaluation.judge", "JSON", "EvaluationResult", ("AC-08", "AC-09")),
    "CONDENSE_CYCLE_SYSTEM_PROMPT": ("summary.session", "JSON", "summary", ("AC-27", "AC-32")),
    "CONDENSE_PROGRESS_SYSTEM_PROMPT": ("summary.rolling", "JSON", "summary", ("AC-32",)),
    "PROGRESS_MEMORY_PROMPT": ("context.rolling", "text", "context-data", ("AC-20", "AC-31")),
    "SESSION_HISTORY_PROMPT": ("context.sessions", "text", "context-data", ("AC-10", "AC-31")),
    "RAG_SYSTEM_PROMPT": ("context.resources", "text", "source-citations", ("AC-20", "AC-23")),
    "KNOWN_INFO_PROMPT": ("context.state", "text", "authoritative-state", ("AC-05", "AC-21")),
}


# Per-entry versions: changing one prompt does not version unrelated prompts.
PROMPT_VERSIONS = {
    "profile.extract": "0.18.0",
    "assessment.plan": "0.18.0",
    "assessment.judge": "0.18.0",
    "planning.roadmap": "0.18.0",
    "planning.window": "0.18.0",
    "planning.confirm": "0.18.0",
    "submission.detect": "0.18.0",
    "evaluation.judge": "0.18.0",
    "summary.session": "0.18.0",
    "summary.rolling": "0.18.0",
    "context.rolling": "0.18.0",
    "context.sessions": "0.18.0",
    "context.resources": "0.18.0",
    "context.state": "0.18.0",
    "stage.goal_clarification": "0.18.0",
    "stage.assessment": "0.18.0",
    "stage.planning": "0.18.0",
    "stage.learning": "0.18.0",
    "stage.evaluation": "0.18.0",
    "stage.completed": "0.18.0"
}

def catalog():
    entries = [PromptSpec(pid, PROMPT_VERSIONS[pid], getattr(tasks, symbol), symbol, output, contract, ac)
               for symbol, (pid, output, contract, ac) in _TASKS.items()]
    entries += [PromptSpec("stage." + name, PROMPT_VERSIONS["stage." + name], text, "coach dialogue: " + name,
                           "text", "stage-dialogue", ("AC-02", "AC-05", "AC-20"))
                for name, text in stages.STAGE_PROMPTS.items()]
    return tuple(entries)


def get_prompt(prompt_id):
    for item in catalog():
        if item.id == prompt_id:
            return item
    raise KeyError(prompt_id)


def manifest():
    return {"schema_version": 1, "prompts": [p.metadata() for p in catalog()]}


def validate_manifest(path=None):
    path = Path(path) if path else Path(__file__).with_name("manifest.json")
    expected = json.loads(path.read_text(encoding="utf-8"))
    errors = []
    if expected != manifest():
        errors.append("Prompt manifest differs: review text/contracts, bump changed versions and regenerate manifest.")
    registered = set(_TASKS)
    actual = {k for k, v in vars(tasks).items() if k.endswith("_PROMPT") and isinstance(v, str)}
    if actual != registered:
        errors.append("Unregistered or missing prompt constants: " + repr(sorted(actual ^ registered)))
    if any(not re.fullmatch(r"\d+\.\d+\.\d+", p.version) for p in catalog()):
        errors.append("Prompt versions must be semantic versions")
    if set(PROMPT_VERSIONS) != {p.id for p in catalog()}:
        errors.append("Prompt version inventory differs from registered prompts")
    if len({p.id for p in catalog()}) != len(catalog()):
        errors.append("Duplicate prompt IDs")
    return errors


def identify_messages(messages):
    """Return registered static fragments only; never include personal message text."""
    systems = [m.get("content", "") for m in messages if m.get("role") == "system"]
    return [p.metadata() for p in catalog()
            if any(isinstance(body, str) and p.text and p.text in body for body in systems)]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Offline prompt inventory and manifest validation")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        errors = validate_manifest()
        for error in errors:
            print(error)
        print(f"{len(catalog())} prompt entries; " + ("FAIL" if errors else "PASS"))
        return int(bool(errors))
    print(json.dumps(manifest(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
