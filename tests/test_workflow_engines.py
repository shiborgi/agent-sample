import asyncio

import pytest

from agent_sample.domain.strategies import WorkflowStrategy
from agent_sample.domain.workflow import WORKFLOW, WorkflowState
from agent_sample.infrastructure.workflow.langgraph import LangGraphEngine
from agent_sample.infrastructure.workflow.sequential import SequentialEngine

CORPUS = (
    "Fui cobrado duas vezes",
    "A API retorna 500",
    "O suporte está demorando",
    "Preciso de capital de giro",
    "Erro na fatura",
    "Bom dia",
    "Quero um desconto no plano anual",
    "Não consigo fazer login, a senha dá erro",
    "Boleto com erro e pedido de upgrade",
)


@pytest.mark.parametrize("text", CORPUS)
def test_engines_produce_the_same_state(text: str) -> None:
    sequential = asyncio.run(SequentialEngine().run(WORKFLOW, WorkflowState(text)))
    graph = asyncio.run(LangGraphEngine().run(WORKFLOW, WorkflowState(text)))
    assert sequential == graph
    assert sequential.outcome is not None


def test_engines_produce_the_same_verdicts() -> None:
    for text in CORPUS:
        left = asyncio.run(WorkflowStrategy(SequentialEngine()).classify(text))
        right = asyncio.run(WorkflowStrategy(LangGraphEngine()).classify(text))
        assert (left.subject_id, left.rationale) == (right.subject_id, right.rationale)
        assert right.decided_by == "workflow:langgraph"


def test_langgraph_engine_compiles_the_workflow_once() -> None:
    engine = LangGraphEngine()
    for text in CORPUS:
        asyncio.run(engine.run(WORKFLOW, WorkflowState(text)))
    assert len(engine._graphs) == 1
