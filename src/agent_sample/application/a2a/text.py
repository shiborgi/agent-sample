from agent_sample.domain.model import Verdict


def artifact_text(verdict: Verdict) -> str:
    confidence = "n/a" if verdict.confidence is None else f"{verdict.confidence:.2f}"
    return f"{verdict.subject_id} ({confidence}) {verdict.rationale}"
