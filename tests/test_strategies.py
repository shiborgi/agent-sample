import asyncio
import logging

import pytest

from agent_sample.domain.content import CLASSIFY_TASK, AgentAnswer
from agent_sample.domain.errors import AgentAttemptFailed
from agent_sample.domain.model import ClassificationFailed
from agent_sample.domain.strategies import (
    AgentStrategy,
    HybridStrategy,
    PredictionStrategy,
    WorkflowStrategy,
)
from agent_sample.infrastructure.content.files import FileContentLibrary
from agent_sample.infrastructure.workflow.sequential import SequentialEngine
from tests.fakes import CONTENT_ROOT, FixedAgent, FixedPredictor

CONTENT = FileContentLibrary(CONTENT_ROOT)


def _agent(agent: FixedAgent) -> AgentStrategy:
    skills = tuple(CONTENT.skill(name) for name in CLASSIFY_TASK.skills)
    return AgentStrategy(agent, CONTENT.prompt(CLASSIFY_TASK.prompt), skills)


def _hybrid(agent: FixedAgent) -> HybridStrategy:
    return HybridStrategy(WorkflowStrategy(SequentialEngine()), _agent(agent))


def test_hybrid_uses_rules_without_calling_the_agent() -> None:
    agent = FixedAgent("sales")
    verdict = asyncio.run(_hybrid(agent).classify("Fui cobrado duas vezes"))
    assert verdict.subject_id == "billing"
    assert verdict.decided_by == "workflow:sequential"
    assert agent.calls == 0
    assert [step.kind for step in verdict.trace] == ["workflow"]


def test_hybrid_escalates_to_the_agent_when_rules_do_not_decide() -> None:
    verdict = asyncio.run(_hybrid(FixedAgent("sales")).classify("Erro na fatura"))
    assert verdict.subject_id == "sales"
    assert verdict.decided_by == "agent:fixed"
    rules, agent = verdict.trace
    assert rules.outcome == "undecided"
    assert agent.outcome == "decided"
    assert agent.prompt == "classify_subject@v2"
    assert agent.skills == ("out-of-scope@v1",)


def test_hybrid_falls_back_to_other_and_records_it(caplog: pytest.LogCaptureFixture) -> None:
    agent = FixedAgent(error=ClassificationFailed("fixed", "boom"))
    with caplog.at_level(logging.WARNING):
        verdict = asyncio.run(_hybrid(agent).classify("Bom dia"))
    assert verdict.subject_id == "other"
    assert verdict.decided_by == "fallback"
    assert [step.outcome for step in verdict.trace] == ["undecided", "failed", "decided"]
    assert "boom" in verdict.trace[1].detail
    assert verdict.trace[1].skills == ("out-of-scope@v1",)
    assert "fell back" in caplog.text


def test_agent_strategy_reports_failure_with_its_step() -> None:
    with pytest.raises(AgentAttemptFailed) as info:
        asyncio.run(_agent(FixedAgent(error=RuntimeError("offline"))).classify("oi"))
    assert info.value.step.outcome == "failed"
    assert "offline" in str(info.value)


def test_agent_answer_outside_the_subjects_fails() -> None:
    class Inventive(FixedAgent):
        async def run(self, request, tools):  # type: ignore[no-untyped-def]
            return AgentAnswer("refund", "inventou um assunto")

    with pytest.raises(AgentAttemptFailed, match="unknown subject: refund"):
        asyncio.run(_agent(Inventive()).classify("oi"))


def test_agents_do_not_invent_confidence() -> None:
    verdict = asyncio.run(_agent(FixedAgent("sales")).classify("quero um demo"))
    assert verdict.confidence is None


def test_prediction_is_labeled_and_keeps_its_confidence() -> None:
    verdict = asyncio.run(PredictionStrategy(FixedPredictor()).classify("fui cobrado"))
    assert verdict.decided_by == "prediction:fixed"
    assert verdict.trace[0].kind == "prediction"
    assert verdict.confidence == pytest.approx(0.88)
