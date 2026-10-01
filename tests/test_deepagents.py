"""O adaptador Deep Agents com modelo roteirizado: ferramentas, delegação e limites."""

import asyncio
from typing import Any

import pytest

from agent_sample.domain.diff import normalize, parse_diff
from agent_sample.domain.model import AgentLimitExceeded, ReviewError
from agent_sample.domain.plan import AgentTask, plan_agentic
from agent_sample.domain.policy import Limits
from agent_sample.domain.tools import TOOL_NAMES, RunContext, Toolbox
from agent_sample.infrastructure.agents.deepagents import DeepAgentsReviewer
from agent_sample.infrastructure.model.ports import Completion
from tests.fakes import (
    SOURCE_DIFF,
    ScriptedGateway,
    answer,
    builtin_capabilities,
    call,
    context,
    review,
)

FINDING = {
    "file": "src/app.py",
    "start_line": 4,
    "end_line": 4,
    "severity": "major",
    "category": "correctness",
    "description": "division by zero when items is empty",
    "suggestion": "guard the empty list",
    "evidence": "return total / len(items)",
    "reviewer": "test-reviewer",
    "skill": "code-review:test-quality@1.0.0",
}


def task(limits: Limits = Limits()) -> AgentTask:
    capabilities = builtin_capabilities()
    change = normalize(parse_diff(SOURCE_DIFF), 1000)
    plan = plan_agentic("hybrid", change, capabilities, (), (), None, None, None, limits)
    return plan.tasks[0]


def run(gateway: ScriptedGateway, limits: Limits = Limits()) -> tuple[Any, Toolbox]:
    toolbox = Toolbox(RunContext(None, builtin_capabilities(), None), 8000)
    outcome = asyncio.run(DeepAgentsReviewer(gateway).review(task(limits), toolbox, limits))
    return outcome, toolbox


def is_subagent(messages: tuple[Any, ...]) -> bool:
    return "Revisores especializados" not in messages[0].content


def delegating(messages: tuple[Any, ...], tools: tuple[Any, ...]) -> Completion:
    """Líder delega ao revisor de testes; o revisor carrega a skill e responde."""
    del tools
    replies = [m for m in messages if m.role == "tool"]
    if is_subagent(messages):
        if not replies:
            return call("load_skill", {"name": "test-quality"}, "sub-1")
        return answer(FINDING)
    if not replies:
        return call("task", {"description": "check tests", "subagent_type": "test-reviewer"})
    return Completion(text=replies[-1].content)


def test_lead_delegates_to_a_plugin_reviewer_and_the_trace_sees_it() -> None:
    gateway = ScriptedGateway(delegating)
    outcome, toolbox = run(gateway)
    assert outcome.reviewers == ("lead", "code-review:test-reviewer")
    (finding,) = outcome.proposed
    assert finding.reviewer == "code-review:test-reviewer"
    assert toolbox.loaded_skills == ("code-review:test-quality@1.0.0",)


def test_only_project_catalog_and_planning_tools_reach_the_model() -> None:
    gateway = ScriptedGateway(delegating)
    run(gateway)
    offered = {spec.name for _, tools in gateway.calls for spec in tools}
    assert offered <= set(TOOL_NAMES) | {"task", "write_todos"}
    assert not offered & {"write_file", "edit_file", "execute", "ls", "glob", "grep", "read_file"}


def test_framework_tools_are_refused_even_if_the_model_calls_them() -> None:
    def script(messages: tuple[Any, ...], tools: tuple[Any, ...]) -> Completion:
        del tools
        replies = [m for m in messages if m.role == "tool"]
        if not replies:
            return call("write_file", {"file_path": "/x.py", "content": "boom"})
        assert "write_file is not available" in replies[-1].content
        return answer()

    outcome, toolbox = run(ScriptedGateway(script))
    assert outcome.proposed == ()
    assert toolbox.calls == []


def test_tool_round_limit_becomes_a_limit_error() -> None:
    def forever(messages: tuple[Any, ...], tools: tuple[Any, ...]) -> Completion:
        del messages, tools
        return call("load_skill", {"name": "security-review"})

    with pytest.raises(AgentLimitExceeded, match="2 tool rounds"):
        run(ScriptedGateway(forever), Limits(max_tool_rounds=2))


def test_timeout_becomes_a_limit_error() -> None:
    async def slow(messages: tuple[Any, ...], tools: tuple[Any, ...]) -> Completion:
        del messages, tools
        await asyncio.sleep(1)
        return answer()

    with pytest.raises(AgentLimitExceeded, match="timeout"):
        run(ScriptedGateway(slow), Limits(timeout_seconds=0.05))


def test_subagent_limit_refuses_extra_delegations() -> None:
    def greedy(messages: tuple[Any, ...], tools: tuple[Any, ...]) -> Completion:
        del tools
        replies = [m for m in messages if m.role == "tool"]
        if is_subagent(messages):
            return answer()
        if len(replies) < 2:
            return call(
                "task", {"description": "x", "subagent_type": "test-reviewer"}, f"t{len(replies)}"
            )
        assert "subagent limit reached (1)" in replies[-1].content
        return answer()

    outcome, _ = run(ScriptedGateway(greedy), Limits(max_subagents=1))
    assert outcome.proposed == ()


def test_answer_that_is_not_json_is_an_error() -> None:
    with pytest.raises(ReviewError, match="not JSON"):
        run(ScriptedGateway(lambda messages, tools: Completion(text="looks good to me")))


def test_hybrid_review_through_deep_agents_end_to_end() -> None:
    reviewer = DeepAgentsReviewer(ScriptedGateway(delegating))
    state = review(ctx=context(reviewer))
    agent = [f for f in state.review.findings if f.origin.kind == "agent"]
    assert [f.origin.name for f in agent] == ["code-review:test-reviewer"]
    assert state.review.trace.reviewers == ("lead", "code-review:test-reviewer")
    assert state.review.trace.skills_loaded == ("code-review:test-quality@1.0.0",)
