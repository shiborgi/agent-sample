import json
from collections.abc import Callable

from agent_sample.domain.content import AgentAnswer
from agent_sample.domain.errors import AgentFailed
from agent_sample.domain.model import ClassificationFailed, subject_by_id
from agent_sample.domain.review.model import ProposedFinding, ReviewAnswer

type AnswerReader[T] = Callable[[str, str], T]
"""Lê o texto final do modelo (`text`, `source`) na resposta da tarefa."""


def parse_answer(text: str, source: str) -> AgentAnswer:
    """Lê a resposta final do modelo: JSON com `subject_id` e `rationale`."""
    try:
        payload = extract_json(text)
        subject_id = str(payload["subject_id"])
        subject_by_id(subject_id)
        return AgentAnswer(subject_id, str(payload.get("rationale") or ""))
    except (KeyError, TypeError, ValueError) as exc:
        raise ClassificationFailed(source, "response was not a subject verdict") from exc


def extract_json(text: str) -> dict[str, object]:
    stripped = text.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no json object")
    payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise TypeError("json payload must be an object")
    return payload


def parse_review(text: str, source: str) -> ReviewAnswer:
    """Lê a revisão do modelo: JSON com `summary` e `findings`.

    É tolerante no formato de cada achado (tipos errados viram campos vazios) porque quem decide
    se um achado vale é a validação do domínio, que registra o motivo de cada descarte.
    """
    try:
        payload = extract_json(text)
        items = payload.get("findings", [])
        if not isinstance(items, list):
            raise TypeError("findings must be a list")
    except (TypeError, ValueError) as exc:
        raise AgentFailed(source, "response was not a review") from exc
    return ReviewAnswer(
        summary=_text(payload.get("summary")),
        findings=tuple(_proposal(item) for item in items),
    )


def _proposal(item: object) -> ProposedFinding:
    raw = item if isinstance(item, dict) else {}
    return ProposedFinding(
        path=_text(raw.get("path")),
        start=_line(raw.get("start_line")),
        end=_line(raw.get("end_line")),
        severity=_text(raw.get("severity")),
        category=_text(raw.get("category")),
        description=_text(raw.get("description")),
        suggestion=_text(raw.get("suggestion")),
    )


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _line(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None
