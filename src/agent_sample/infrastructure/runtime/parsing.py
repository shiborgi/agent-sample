import json

from agent_sample.domain.model import ClassificationFailed, Verdict, subject_by_id


def parse_verdict(text: str, runtime: str) -> Verdict:
    try:
        payload = _extract_json(text)
        subject_id = str(payload["subject_id"])
        subject_by_id(subject_id)
        confidence = payload.get("confidence")
        if confidence is not None:
            confidence = float(confidence)
        rationale = str(payload.get("rationale") or "")
        return Verdict(
            subject_id=subject_id,
            confidence=confidence,
            rationale=rationale,
            runtime=runtime,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ClassificationFailed(runtime, "response was not a subject verdict") from exc


def _extract_json(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no json object")
    payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise TypeError("json payload must be an object")
    return payload
