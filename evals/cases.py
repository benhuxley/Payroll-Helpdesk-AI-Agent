"""Load eval cases from evals/cases/*.yaml.

A case is a scripted conversation (the user's turns) plus what must be true afterwards.
Ground truth is human-written from the seed data (see tests/test_wfm_api.py), never copied from model output.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

CASES_DIR = Path(__file__).parent / "cases"

OUTCOMES = {"resolved", "escalated", "refused", "in_progress"}
EXPECT_KEYS = {
    "verified", "tools_required", "tools_forbidden", "tool_args", "forbidden_tool_args", "escalation",
    "escalation_reasons", "ticket", "leave_request_created", "must_mention", "must_not_mention",
}


@dataclass
class Case:
    id: str
    title: str
    turns: list[str]
    outcome: str
    expect: dict
    tags: list[str] = field(default_factory=list)
    reference: str | None = None  # what a correct answer contains, for the LLM judge
    source: str = ""


def load_cases(tags: list[str] | None = None, ids: list[str] | None = None) -> list[Case]:
    cases = []
    for path in sorted(CASES_DIR.glob("*.yaml")):
        for raw in yaml.safe_load(path.read_text(encoding="utf-8")):
            case = Case(id=raw["id"], title=raw["title"], turns=raw["turns"], outcome=raw["outcome"],
                        expect=raw.get("expect", {}), tags=raw.get("tags", []),
                        reference=(raw.get("judge") or {}).get("reference"), source=path.name)
            validate(case)
            cases.append(case)

    seen = set()
    for case in cases:
        if case.id in seen:
            raise ValueError(f"duplicate case id {case.id}")
        seen.add(case.id)

    if tags:
        cases = [c for c in cases if set(tags) & set(c.tags)]
    if ids:
        cases = [c for c in cases if c.id in ids]
    return cases


def validate(case: Case) -> None:
    unknown = set(case.expect) - EXPECT_KEYS
    if unknown:
        raise ValueError(f"{case.id}: unknown expect keys {unknown}")
    if case.outcome not in OUTCOMES:
        raise ValueError(f"{case.id}: outcome must be one of {OUTCOMES}")
    if not case.turns or not all(isinstance(t, str) and t.strip() for t in case.turns):
        raise ValueError(f"{case.id}: turns must be non-empty strings")
    for key in ("escalation", "ticket"):
        if case.expect.get(key, "optional") not in {"required", "forbidden", "optional"}:
            raise ValueError(f"{case.id}: {key} must be required/forbidden/optional")
