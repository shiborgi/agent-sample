import json
from collections.abc import Sequence

from agent_sample.domain.model import Verdict
from agent_sample.domain.ports import ChatMessage, Completion, ToolCall, ToolSpec


class ScriptedGateway:
    def __init__(self, subject_id: str = "billing") -> None:
        self.subject_id = subject_id
        self.calls: list[tuple[tuple[ChatMessage, ...], tuple[ToolSpec, ...]]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] = (),
    ) -> Completion:
        stored = (tuple(messages), tuple(tools))
        self.calls.append(stored)
        if any(message.role == "tool" for message in messages) or not tools:
            return Completion(text=_verdict_json(self.subject_id))
        return Completion(
            text="",
            tool_calls=(ToolCall(id="call-1", name="list_subjects", arguments={}),),
        )


class FixedClassifier:
    runtime = "fixed"

    def __init__(self, subject_id: str, error: Exception | None = None) -> None:
        self._subject_id = subject_id
        self._error = error

    async def classify(self, text: str) -> Verdict:
        del text
        if self._error is not None:
            raise self._error
        return Verdict(self._subject_id, 0.5, "fixed", self.runtime)


def _verdict_json(subject_id: str) -> str:
    return json.dumps(
        {"subject_id": subject_id, "confidence": 0.91, "rationale": "scripted"},
        ensure_ascii=False,
    )
