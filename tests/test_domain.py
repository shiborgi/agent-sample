import pytest

from agent_sample.domain.model import EmptyMessage, UnknownSubject, Verdict
from agent_sample.domain.session import classify_subject
from tests.fakes import FixedClassifier


def test_verdict_rejects_unknown_subject() -> None:
    with pytest.raises(UnknownSubject):
        Verdict("nope", 0.2, "x", "test")


def test_empty_message_is_rejected() -> None:
    with pytest.raises(EmptyMessage):
        _run(classify_subject("  ", FixedClassifier("billing")))


def test_session_returns_the_classifier_verdict() -> None:
    verdict = _run(classify_subject("fui cobrado", FixedClassifier("billing")))
    assert verdict.subject_id == "billing"
    assert verdict.runtime == "fixed"


def _run(awaitable):  # type: ignore[no-untyped-def]
    import asyncio

    return asyncio.run(awaitable)
