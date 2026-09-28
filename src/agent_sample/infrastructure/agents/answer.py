import json

from agent_sample.domain.content import AgentAnswer
from agent_sample.domain.model import ClassificationFailed, subject_by_id


def parse_answer(text: str, source: str) -> AgentAnswer:
    """Lê a resposta final do modelo: JSON com `subject_id` e `rationale`."""
    try:
        payload = _extract_json(text)
        subject_id = str(payload["subject_id"])
        subject_by_id(subject_id)
        return AgentAnswer(subject_id, str(payload.get("rationale") or ""))
    except (KeyError, TypeError, ValueError) as exc:
        raise ClassificationFailed(source, "response was not a subject verdict") from exc


def _extract_json(text: str) -> dict[str, object]:
    stripped = text.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no json object")
    payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise TypeError("json payload must be an object")
    return payload
