from agent_sample.domain.model import EmptyMessage, Verdict
from agent_sample.domain.ports import SubjectClassifier


async def classify_subject(text: str, classifier: SubjectClassifier) -> Verdict:
    cleaned = text.strip()
    if not cleaned:
        raise EmptyMessage()
    return await classifier.classify(cleaned)
