"""A fronteira entre o workflow determinístico e a etapa agêntica, com agente falso e sem rede."""

import asyncio

import pytest

from agent_sample.domain.change import PullRequest
from agent_sample.domain.model import (
    AgentLimitExceeded,
    AgentUnavailable,
    PublishNotAllowed,
    StepRecord,
)
from agent_sample.domain.policy import Limits
from agent_sample.domain.workflow import STEPS, ReviewRequest, ReviewState, run_review
from agent_sample.infrastructure.workflow.sequential import SequentialEngine
from tests.fakes import SOURCE_DIFF, FakeAgent, FakeHost, context, proposal, review


def test_only_step_five_is_agentic() -> None:
    assert [step.name for step in STEPS if step.nature == "agentic"] == ["agentic_review"]
    assert len(STEPS) == 9


def test_hybrid_accepts_valid_and_records_discarded_findings() -> None:
    agent = FakeAgent(
        (
            proposal(),
            proposal(file="src/elsewhere.py", description="outside the diff"),
            proposal(start_line=99, end_line=99, description="line that does not exist"),
            proposal(evidence="", description="no evidence"),
            proposal(severity="urgent", description="bad severity"),
            proposal(category="naming", description="bad category"),
        )
    )
    state = review(ctx=context(agent))
    agent_findings = [f for f in state.review.findings if f.origin.kind == "agent"]
    assert [f.description for f in agent_findings] == ["division by zero when items is empty"]
    reasons = {item.description: item.reason for item in state.review.trace.discarded}
    assert reasons["outside the diff"].startswith("file not in the reviewed change")
    assert "does not exist" in reasons["line that does not exist"]
    assert reasons["no evidence"] == "missing evidence"
    assert "severity" in reasons["bad severity"]
    assert "category" in reasons["bad category"]


def test_agent_cannot_remove_or_downgrade_a_critical_check_finding() -> None:
    downgrade = proposal(
        start_line=2,
        end_line=2,
        severity="nit",
        category="security",
        description="token looks fine",
        evidence='token = "ghp_',
    )
    state = review(ctx=context(FakeAgent((downgrade,))))
    security = [f for f in state.review.findings if f.category == "security"]
    assert [(f.severity, f.origin.kind) for f in security] == [("critical", "check")]
    assert state.review.decision == "request_changes"


def test_duplicate_findings_appear_once() -> None:
    same = proposal(reviewer="code-review:test-reviewer")
    state = review(ctx=context(FakeAgent((proposal(), same))))
    located = [f for f in state.review.findings if f.location == "src/app.py:4"]
    assert len(located) == 1
    assert "1 duplicate(s) merged" in state.review.trace.steps[6].detail


@pytest.mark.parametrize(
    "error",
    [RuntimeError("model exploded"), AgentLimitExceeded("8 tool rounds"), TimeoutError()],
)
def test_agent_failure_keeps_deterministic_findings(error: Exception) -> None:
    state = review(ctx=context(FakeAgent((proposal(),), error=error)))
    assert state.review.decision == "request_changes"
    assert {f.origin.kind for f in state.review.findings} == {"check"}
    step = state.review.trace.steps[4]
    assert (step.name, step.outcome) == ("agentic_review", "failed")
    assert any(type(error).__name__ in failure for failure in state.review.trace.failures)


def test_trace_records_reviewers_skills_plugins_and_versions() -> None:
    state = review(ctx=context(FakeAgent((proposal(),))))
    trace = state.review.trace
    assert trace.reviewers == ("lead", "code-review:python-reviewer")
    assert trace.skills_loaded == ("code-review:python-practices@1.0.0",)
    assert trace.capabilities[0].startswith("code-review@1.0.0 source=builtin sha256=")
    assert trace.tool_calls[0].tool == "load_skill"
    (finding,) = [f for f in state.review.findings if f.origin.kind == "agent"]
    assert finding.origin.skill == "code-review:python-practices@1.0.0"
    assert "reviewers: code-review:python-reviewer, code-review:test-reviewer" in (
        trace.steps[3].detail
    )


def test_workflow_mode_never_calls_the_agent_and_is_reproducible() -> None:
    agent = FakeAgent((proposal(),))
    first = review(mode="workflow", ctx=context(agent))
    second = review(mode="workflow", ctx=context(agent))
    assert agent.tasks == []
    assert first.review == second.review
    assert first.output == second.output


def test_agent_mode_skips_checks_but_still_validates_and_decides() -> None:
    agent = FakeAgent((proposal(), proposal(file="nope.py")))
    state = review(mode="agent", ctx=context(agent))
    assert state.review.trace.steps[2].outcome == "skipped"
    assert {f.origin.kind for f in state.review.findings} == {"agent"}
    assert len(state.review.trace.discarded) == 1
    assert state.review.decision == "request_changes"


def test_without_model_hybrid_degrades_and_agent_mode_fails() -> None:
    offline = FakeAgent(unavailable="MODEL_API_KEY is not set")
    state = review(ctx=context(offline))
    assert state.review.trace.steps[3].outcome == "degraded"
    assert "MODEL_API_KEY is not set" in state.review.trace.failures[0]
    with pytest.raises(AgentUnavailable, match="MODEL_API_KEY"):
        review(mode="agent", ctx=context(offline))


def test_documentation_only_change_does_not_call_the_agent() -> None:
    diff = "--- a/README.md\n+++ b/README.md\n@@ -1 +1,2 @@\n # T\n+more\n"
    agent = FakeAgent()
    state = review(diff, ctx=context(agent))
    assert agent.tasks == []
    assert state.review.trace.steps[3].detail == "documentation-only change"


def test_agent_mode_fails_without_model_even_when_the_step_would_be_skipped() -> None:
    diff = "--- a/README.md\n+++ b/README.md\n@@ -1 +1,2 @@\n # T\n+more\n"
    offline = FakeAgent(unavailable="MODEL_API_KEY is not set")
    with pytest.raises(AgentUnavailable, match="MODEL_API_KEY"):
        review(diff, mode="agent", ctx=context(offline))


def test_large_changes_are_reviewed_in_parts() -> None:
    second = SOURCE_DIFF.replace("src/app.py", "src/other.py")
    agent = FakeAgent()
    review(SOURCE_DIFF + second, ctx=context(agent, limits=Limits(max_part_chars=10)))
    assert [task.label for task in agent.tasks] == ["part 1/2", "part 2/2"]
    assert [task.files[0].path for task in agent.tasks] == ["src/app.py", "src/other.py"]


def test_progress_is_reported_per_step() -> None:
    seen: list[StepRecord] = []

    async def listen(step: StepRecord) -> None:
        seen.append(step)

    request = ReviewRequest(PullRequest("fake/repo#1"))
    state: ReviewState = asyncio.run(
        run_review(request, context(hosts=(FakeHost(),)), SequentialEngine(), listen)
    )
    assert [step.name for step in seen] == [step.name for step in STEPS]
    assert state.review is not None
    assert "fake-host fake/repo#1" in seen[0].detail


def test_posting_needs_a_pull_request_and_an_explicit_request() -> None:
    host = FakeHost()
    review(ref=PullRequest("fake/repo#1"), ctx=context(hosts=(host,)))
    assert host.published == []
    state = review(ref=PullRequest("fake/repo#1"), ctx=context(hosts=(host,)), post=True)
    assert [locator for locator, _ in host.published] == ["fake/repo#1"]
    assert "posted to fake/repo#1" in state.review.trace.steps[-1].detail
    with pytest.raises(PublishNotAllowed):
        review(post=True)
