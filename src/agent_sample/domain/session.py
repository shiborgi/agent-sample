from agent_sample.domain.model import EmptyMessage, Verdict, subject_by_id
from agent_sample.domain.ports import SubjectClassifier


async def classify_subject(text: str, classifier: SubjectClassifier) -> Verdict:
    cleaned = text.strip()
    if not cleaned:
        raise EmptyMessage()
    verdict = await classifier.classify(cleaned)
    subject_by_id(verdict.subject_id)
    return verdict
