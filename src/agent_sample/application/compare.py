from dataclasses import dataclass

from agent_sample.domain.model import Verdict
from agent_sample.domain.ports import SubjectClassifier
from agent_sample.domain.session import classify_subject


@dataclass(frozen=True, slots=True)
class ComparisonRow:
    runtime: str
    verdict: Verdict | None
    error: str | None


async def compare_subject(
    text: str,
    classifiers: tuple[SubjectClassifier, ...],
) -> tuple[ComparisonRow, ...]:
    rows: list[ComparisonRow] = []
    for classifier in classifiers:
        try:
            verdict = await classify_subject(text, classifier)
        except Exception as exc:
            rows.append(ComparisonRow(classifier.runtime, None, str(exc)))
        else:
            rows.append(ComparisonRow(classifier.runtime, verdict, None))
    return tuple(rows)
