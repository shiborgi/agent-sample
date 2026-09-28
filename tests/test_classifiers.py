import asyncio

import pytest

from agent_sample.application.compare import compare_subject
from agent_sample.domain.model import SUBJECTS
from agent_sample.infrastructure.runtime.deepagents import DeepAgentsSubjectClassifier
from agent_sample.infrastructure.runtime.langgraph import LangGraphSubjectClassifier
from agent_sample.infrastructure.runtime.laya import LayaSubjectClassifier
from agent_sample.infrastructure.tools.subjects import SubjectCatalog
from tests.fakes import ScriptedGateway


def test_three_runtimes_agree_on_the_subject() -> None:
    rows = asyncio.run(
        compare_subject(
            "Fui cobrado duas vezes em março.",
            (
                LangGraphSubjectClassifier(ScriptedGateway("billing"), SubjectCatalog()),
                DeepAgentsSubjectClassifier(ScriptedGateway("billing"), SubjectCatalog()),
                LayaSubjectClassifier(predict=_laya_predict),
            ),
        )
    )
    assert [row.error for row in rows] == [None, None, None]
    assert {row.verdict.subject_id for row in rows if row.verdict} == {"billing"}
    runtimes = [row.verdict.runtime for row in rows if row.verdict]
    assert runtimes == ["langgraph", "deepagents", "laya"]


def test_langgraph_calls_the_subject_catalog() -> None:
    gateway = ScriptedGateway("technical")
    verdict = asyncio.run(
        LangGraphSubjectClassifier(gateway, SubjectCatalog()).classify("A API retorna 500")
    )
    assert verdict.subject_id == "technical"
    assert gateway.calls[0][1][0].name == "list_subjects"
    assert any(message.role == "tool" for message in gateway.calls[1][0])


def test_laya_question_uses_the_domain_catalog() -> None:
    seen: dict[str, object] = {}

    def predict(state: str, questions: dict[str, object], **kwargs: object) -> dict[str, object]:
        del kwargs
        seen["state"] = state
        seen["criteria"] = questions["subject"]["criteria"]  # type: ignore[index]
        return {"answers": {"subject": {"choice": "sales", "answer_confidence": 0.7}}}

    verdict = asyncio.run(LayaSubjectClassifier(predict=predict).classify("quero uma demonstração"))
    criteria = seen["criteria"]
    assert isinstance(criteria, dict)
    assert set(criteria) == {subject.id for subject in SUBJECTS}
    assert verdict.subject_id == "sales"
    assert verdict.confidence == pytest.approx(0.7)


def _laya_predict(state: str, questions: dict[str, object], **kwargs: object) -> dict[str, object]:
    del state, questions, kwargs
    return {"answers": {"subject": {"choice": "billing", "answer_confidence": 0.88}}}
