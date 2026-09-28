import asyncio

import pytest

from agent_sample.domain.model import EmptyMessage, Step, UnknownSubject, Verdict
from agent_sample.domain.session import classify_subject
from tests.fakes import FixedClassifier

STEP = Step("workflow", "test", "decided", "")


def test_verdict_rejects_unknown_subject() -> None:
    with pytest.raises(UnknownSubject):
        Verdict("nope", "x", "test", (STEP,))


@pytest.mark.parametrize("kind", ["workflow", "fallback"])
def test_rules_and_fallback_never_report_confidence(kind: str) -> None:
    step = Step(kind, "test", "decided", "")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="never report confidence"):
        Verdict("billing", "x", "test", (step,), confidence=0.9)


def test_verdict_requires_a_path() -> None:
    with pytest.raises(ValueError, match="path"):
        Verdict("other", "x", "test", ())


def test_empty_message_is_rejected() -> None:
    with pytest.raises(EmptyMessage):
        asyncio.run(classify_subject("  ", FixedClassifier("billing")))


def test_session_returns_the_classifier_verdict() -> None:
    verdict = asyncio.run(classify_subject("fui cobrado", FixedClassifier("billing")))
    assert verdict.subject_id == "billing"
    assert verdict.decided_by == "fixed"
