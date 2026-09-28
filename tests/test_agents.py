import asyncio

import pytest

from agent_sample.application.service import ClassifyOptions
from agent_sample.domain.model import ClassificationFailed
from agent_sample.infrastructure.agents.answer import parse_answer
from agent_sample.infrastructure.prediction.laya import LayaPredictor
from tests.fakes import ScriptedGateway, composition

AGENTS = ("langgraph", "deepagents")


@pytest.mark.parametrize("agent", AGENTS)
def test_agent_loads_a_skill_on_demand_and_traces_it(agent: str) -> None:
    gateway = ScriptedGateway("technical", skill="subject-boundaries")
    options = ClassifyOptions(strategy="agent", agent=agent)
    verdict = asyncio.run(composition(gateway).build(options).classify("A API retorna 500"))
    assert verdict.subject_id == "technical"
    assert verdict.decided_by == f"agent:{agent}"
    (step,) = verdict.trace
    assert step.prompt == "classify_subject@v2"
    assert step.skills == ("subject-boundaries@v1",)


@pytest.mark.parametrize("agent", AGENTS)
def test_agents_share_prompt_and_only_see_the_skill_index(agent: str) -> None:
    gateway = ScriptedGateway()
    options = ClassifyOptions(strategy="agent", agent=agent, prompt_version="v1")
    asyncio.run(composition(gateway).build(options).classify("Erro na fatura"))
    first_messages, first_tools = gateway.calls[0]
    system = next(message.content for message in first_messages if message.role == "system")
    assert "chame load_skill com o nome" in system
    assert "- subject-boundaries: Como desempatar" in system
    assert "Fronteiras entre assuntos" not in system
    assert {"list_subjects", "load_skill"} <= {tool.name for tool in first_tools}
    tool_results = [message for message in gateway.calls[1][0] if message.role == "tool"]
    assert "Fronteiras entre assuntos" in tool_results[-1].content


def test_prompt_versions_can_be_compared_on_the_same_message() -> None:
    root = composition(ScriptedGateway("billing"))
    for version in ("v1", "v2"):
        options = ClassifyOptions(strategy="agent", prompt_version=version)
        verdict = asyncio.run(root.build(options).classify("Erro na fatura"))
        assert verdict.trace[0].prompt == f"classify_subject@{version}"


def test_laya_question_uses_the_domain_catalog() -> None:
    seen: dict[str, object] = {}

    def predict(state: str, questions: dict[str, object], **kwargs: object) -> dict[str, object]:
        del kwargs
        seen["criteria"] = questions["subject"]["criteria"]  # type: ignore[index]
        return {"answers": {"subject": {"choice": "sales", "answer_confidence": 0.7}}}

    prediction = asyncio.run(LayaPredictor(predict=predict).predict("quero uma demonstração"))
    assert set(seen["criteria"]) == {"billing", "technical", "sales", "other"}  # type: ignore[arg-type]
    assert prediction.subject_id == "sales"
    assert prediction.confidence == pytest.approx(0.7)


def test_model_answer_is_read_by_the_infrastructure() -> None:
    answer = parse_answer('ok: {"subject_id": "sales", "rationale": "pede demo"}', "fake")
    assert (answer.subject_id, answer.rationale) == ("sales", "pede demo")
    with pytest.raises(ClassificationFailed, match="not a subject verdict"):
        parse_answer("acho que é cobrança", "fake")
