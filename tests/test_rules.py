import asyncio

import pytest

from agent_sample.domain.rules import KEYWORDS, decide, match, normalize, tokenize
from agent_sample.domain.strategies import WorkflowStrategy
from agent_sample.infrastructure.workflow.sequential import SequentialEngine


@pytest.mark.parametrize(
    ("text", "subject_id"),
    [
        ("Fui cobrado duas vezes", "billing"),
        ("A API retorna 500", "technical"),
        ("O suporte está demorando", "other"),
        ("Preciso de capital de giro", "other"),
        ("Erro na fatura", "other"),
        ("Bom dia", "other"),
        ("Quero uma DEMONSTRAÇÃO do plano", "sales"),
        ("o sistema está fora do ar", "technical"),
    ],
)
def test_workflow_classifies_without_a_model(text: str, subject_id: str) -> None:
    verdict = asyncio.run(WorkflowStrategy(SequentialEngine()).classify(text))
    assert verdict.subject_id == subject_id
    assert verdict.confidence is None
    assert verdict.decided_by == "workflow:sequential"


def test_word_fragments_do_not_match() -> None:
    assert decide(match(tokenize("capital"))).subject_id is None
    assert decide(match(tokenize("demorando"))).subject_id is None
    assert decide(match(tokenize("apimentado demonstrativo"))).subject_id is None


def test_accents_and_case_do_not_change_the_result() -> None:
    variants = ["Cobrança indevida", "COBRANCA INDEVIDA", "cobrança indevida"]
    assert {decide(match(tokenize(text))).subject_id for text in variants} == {"billing"}


def test_tie_and_no_evidence_are_undecided() -> None:
    tie = decide(match(tokenize("Erro na fatura")))
    assert tie.subject_id is None
    assert "empatadas" in tie.detail
    assert decide(match(tokenize("Bom dia"))).detail == "regras sem evidência"


def test_phrases_match_whole_word_sequences() -> None:
    assert decide(match(tokenize("preciso da nota fiscal"))).subject_id == "billing"
    assert decide(match(tokenize("nota de fiscalização"))).subject_id is None


def test_keywords_are_already_normalized() -> None:
    for terms in KEYWORDS.values():
        for term in terms:
            assert normalize(term) == term
