import asyncio

import pytest

from agent_sample.domain.review.change import prepare_change
from agent_sample.domain.review.checks import CHECKS
from agent_sample.domain.review.model import Finding, Review, decide
from agent_sample.domain.review.strategies import WorkflowReviewer
from agent_sample.domain.review.workflow import REVIEW_WORKFLOW, ReviewState
from agent_sample.domain.trace import Step
from agent_sample.infrastructure.workflow.langgraph import LangGraphEngine
from agent_sample.infrastructure.workflow.sequential import SequentialEngine

# Segredos montados em partes para não parecerem credenciais reais no repositório.
AWS_KEY = "AKIA" + "Q" * 16
GITHUB_TOKEN = "ghp_" + "a1" * 18


def added(path: str, *lines: str) -> str:
    body = "".join(f"+{line}\n" for line in lines)
    return f"--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n{body}"


def review(text: str, engine: object = None) -> Review:
    reviewer = WorkflowReviewer(engine or SequentialEngine())  # type: ignore[arg-type]
    return asyncio.run(reviewer.review(prepare_change(text)))


def by_source(result: Review, source: str) -> list[Finding]:
    return [finding for finding in result.findings if finding.source == f"rule:{source}"]


@pytest.mark.parametrize(
    "line",
    [
        f'KEY = "{AWS_KEY}"',
        f"token: {GITHUB_TOKEN}",
        "-----BEGIN RSA PRIVATE KEY-----",
        'API_KEY = "9f8e7d6c5b4a39281706"',
        '{"password": "s3nh4-f0rte!"}',
    ],
)
def test_secrets_are_critical_security_findings(line: str) -> None:
    (finding,) = by_source(review(added("app/settings.py", line)), "secrets")
    assert (finding.severity, finding.category, finding.origin) == ("critical", "security", "rule")
    assert (finding.path, finding.start, finding.end) == ("app/settings.py", 1, 1)


def test_secret_evidence_is_masked() -> None:
    (finding,) = by_source(review(added("app.py", f'KEY = "{AWS_KEY}"')), "secrets")
    assert AWS_KEY not in finding.evidence
    assert finding.evidence == '+KEY = "AKIA****"'


@pytest.mark.parametrize(
    "line",
    [
        'password = "changeme123"',
        'api_key = "${API_KEY_FROM_ENV}"',
        "token = os.environ['TOKEN']",
        'secret = "short"',
    ],
)
def test_placeholders_and_env_lookups_are_not_secrets(line: str) -> None:
    assert by_source(review(added("app.py", line)), "secrets") == []


@pytest.mark.parametrize(
    ("path", "line"),
    [
        ("app.py", 'print("debug", total)'),
        ("app.py", "breakpoint()"),
        ("app.py", "import pdb; pdb.set_trace()"),
        ("web/app.ts", "console.log(user)"),
        ("web/app.js", "debugger;"),
    ],
)
def test_debug_leftovers_are_minor(path: str, line: str) -> None:
    (finding,) = by_source(review(added(path, line)), "debug-leftovers")
    assert (finding.severity, finding.category) == ("minor", "maintainability")


def test_print_is_only_debug_in_python() -> None:
    assert by_source(review(added("notes.md", "print(x)")), "debug-leftovers") == []


def test_commented_out_code_block_is_reported_as_a_range() -> None:
    text = added(
        "app.py",
        "value = 1",
        "# old = compute(value)",
        "# if old:",
        "#     return old",
        "# Um comentário comum.",
    )
    (finding,) = by_source(review(text), "debug-leftovers")
    assert (finding.start, finding.end) == (2, 4)
    assert finding.evidence.count("\n") == 2


def test_source_without_tests_is_a_minor_tests_finding() -> None:
    text = added("app/a.py", "x = 1") + added("app/b.py", "y = 2") + added("README.md", "doc")
    (finding,) = by_source(review(text), "missing-tests")
    assert (finding.severity, finding.category, finding.path) == ("minor", "tests", "app/a.py")
    assert "app/b.py" in finding.description


def test_any_test_change_satisfies_the_tests_check() -> None:
    text = added("app/a.py", "x = 1") + added("tests/test_a.py", "def test_x(): ...")
    assert by_source(review(text), "missing-tests") == []
    assert by_source(review(added("README.md", "doc")), "missing-tests") == []


def test_pending_markers_are_nits_and_removed_ones_are_ignored() -> None:
    text = (
        "--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n"
        "-# TODO: antigo\n"
        "+# FIXME: tratar timeout\n"
        " x = 1\n"
    )
    (finding,) = by_source(review(text), "pending-markers")
    assert (finding.severity, finding.start) == ("nit", 1)


@pytest.mark.parametrize(
    ("severities", "decision"),
    [
        (("critical", "nit"), "request_changes"),
        (("major",), "request_changes"),
        (("minor", "nit"), "comment"),
        ((), "approve"),
    ],
)
def test_decision_rule(severities: tuple[str, ...], decision: str) -> None:
    findings = tuple(_finding(severity) for severity in severities)
    assert decide(findings) == decision


def test_review_rejects_a_decision_that_breaks_the_rule() -> None:
    step = Step("decision", "policy", "decided", "")
    with pytest.raises(ValueError, match="decision rule"):
        Review("approve", "x", (_finding("critical"),), (), "test", (step,))


def test_workflow_trace_lists_every_step_and_the_decision() -> None:
    result = review(added("app.py", 'print("x")'))
    names = [step.name for step in result.trace]
    assert names == [
        "sequential/triage",
        *(f"sequential/{check.name}" for check in CHECKS),
        "policy",
    ]
    assert result.trace[-1].detail == "comment: 2 minor"
    assert result.reviewed_by == "workflow:sequential"


CORPUS = (
    added("app.py", f'KEY = "{AWS_KEY}"', 'print("x")', "# TODO: depois"),
    added("app.py", "x = 1") + added("tests/test_app.py", "def test_x(): ..."),
    "diff --git a/logo.png b/logo.png\nBinary files a/logo.png and b/logo.png differ\n",
)


@pytest.mark.parametrize("text", CORPUS)
def test_engines_produce_the_same_review_state(text: str) -> None:
    change = prepare_change(text)
    sequential = asyncio.run(SequentialEngine().run(REVIEW_WORKFLOW, ReviewState(change)))
    graph = asyncio.run(LangGraphEngine().run(REVIEW_WORKFLOW, ReviewState(change)))
    assert sequential == graph


@pytest.mark.parametrize("text", CORPUS)
def test_same_diff_same_review(text: str) -> None:
    assert review(text) == review(text)


def _finding(severity: str) -> Finding:
    return Finding(
        "a.py",
        1,
        1,
        severity,
        "style",
        "x",
        "",
        "rule",
        "rule:test",
        "+x",  # type: ignore[arg-type]
    )
