import json
import shutil
from collections.abc import Sequence
from pathlib import Path

from agent_sample.composition import CONTENT_ROOT, Composition
from agent_sample.domain.content import AgentAnswer, AgentRequest
from agent_sample.domain.model import Step, Verdict
from agent_sample.domain.ports import Prediction, ToolCatalog, ToolSpec
from agent_sample.infrastructure.content.files import FileContentLibrary
from agent_sample.infrastructure.model.ports import ChatMessage, Completion, ModelGateway, ToolCall


class ScriptedGateway:
    """Modelo falso: carrega uma skill na primeira rodada e responde depois do resultado."""

    def __init__(self, subject_id: str = "billing", skill: str = "subject-boundaries") -> None:
        self.subject_id = subject_id
        self.skill = skill
        self.calls: list[tuple[tuple[ChatMessage, ...], tuple[ToolSpec, ...]]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] = (),
    ) -> Completion:
        self.calls.append((tuple(messages), tuple(tools)))
        if any(message.role == "tool" for message in messages):
            return Completion(text=_answer(self.subject_id))
        return Completion(
            text="",
            tool_calls=(ToolCall(id="call-1", name="load_skill", arguments={"name": self.skill}),),
        )


class FixedClassifier:
    name = "fixed"

    def __init__(self, subject_id: str, error: Exception | None = None) -> None:
        self._subject_id = subject_id
        self._error = error

    async def classify(self, text: str) -> Verdict:
        del text
        if self._error is not None:
            raise self._error
        return Verdict(
            self._subject_id, "fixed", self.name, (Step("agent", "fixed", "decided", ""),)
        )


class FixedAgent:
    name = "fixed"

    def __init__(self, subject_id: str = "sales", error: Exception | None = None) -> None:
        self._subject_id = subject_id
        self._error = error
        self.calls = 0

    async def run(self, request: AgentRequest, tools: ToolCatalog) -> AgentAnswer:
        del request
        self.calls += 1
        await tools.call("load_skill", {"name": "out-of-scope"})
        if self._error is not None:
            raise self._error
        return AgentAnswer(self._subject_id, "scripted")


class FixedPredictor:
    name = "fixed"

    async def predict(self, text: str) -> Prediction:
        del text
        return Prediction("billing", 0.88)


def copy_content(tmp_path: Path) -> Path:
    root = tmp_path / "content"
    shutil.copytree(CONTENT_ROOT, root)
    return root


def composition(gateway: ModelGateway, root: Path = CONTENT_ROOT) -> Composition:
    return Composition(FileContentLibrary(root), gateway, FixedPredictor())


def _answer(subject_id: str) -> str:
    return json.dumps({"subject_id": subject_id, "rationale": "scripted"}, ensure_ascii=False)
