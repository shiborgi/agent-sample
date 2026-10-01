from dataclasses import replace

import pytest

from agent_sample.domain.diff import normalize, parse_diff
from agent_sample.domain.model import Finding, Origin
from agent_sample.domain.policy import consolidate, decide, validate
from tests.fakes import SOURCE_DIFF, proposal

CHANGE = normalize(parse_diff(SOURCE_DIFF), 1000)


def finding(severity: str = "minor", category: str = "correctness", line: int = 4) -> Finding:
    return Finding(
        "src/app.py",
        line,
        line,
        severity,  # type: ignore[arg-type]
        category,  # type: ignore[arg-type]
        "d",
        "s",
        Origin("check", "c"),
        "e",
    )


def test_valid_proposal_becomes_an_agent_finding() -> None:
    accepted, discarded = validate((proposal(),), CHANGE)
    assert discarded == ()
    (item,) = accepted
    assert item.origin == Origin(
        "agent",
        "code-review:python-reviewer",
        "code-review:python-practices@1.0.0",
        "code-review",
    )


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"file": "src/other.py"}, "file not in the reviewed change"),
        ({"start_line": 40, "end_line": 40}, "line 40 does not exist"),
        ({"description": " "}, "missing description"),
        ({"severity": "blocker"}, "severity outside the list"),
        ({"category": "naming"}, "category outside the list"),
        ({"evidence": ""}, "missing evidence"),
        ({"evidence": "return 42"}, "evidence not found in the diff"),
        ({"start_line": 4, "end_line": 2}, "line range is reversed"),
    ],
)
def test_invalid_proposals_are_discarded_with_the_reason(changes: dict, reason: str) -> None:
    accepted, (discarded,) = validate((proposal(**changes),), CHANGE)
    assert accepted == ()
    assert reason in discarded.reason
    assert discarded.reviewer == "code-review:python-reviewer"


def test_duplicates_keep_one_with_the_highest_severity() -> None:
    check = finding("critical", "security")
    agent_lower = replace(finding("minor", "security"), origin=Origin("agent", "lead"))
    assert consolidate((check,), (agent_lower,)) == (check,)
    agent_higher = replace(finding("major", "correctness"), origin=Origin("agent", "lead"))
    weaker = finding("nit", "correctness")
    assert consolidate((weaker,), (agent_higher,)) == (agent_higher,)
    other_category = finding("minor", "style")
    assert len(consolidate((check,), (other_category,))) == 2


def test_decision_rule() -> None:
    assert decide(()) == "approve"
    assert decide((finding("nit"), finding("minor"))) == "comment"
    assert decide((finding("minor"), finding("major"))) == "request_changes"
    assert decide((finding("critical"),)) == "request_changes"
