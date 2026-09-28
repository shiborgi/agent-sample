import json
import shutil
from collections.abc import Sequence
from pathlib import Path

from agent_sample.application.review import ReviewOptions, ReviewService
from agent_sample.composition import CONTENT_ROOT, Composition
from agent_sample.domain.content import AgentAnswer, AgentRequest
from agent_sample.domain.model import Verdict
from agent_sample.domain.ports import Prediction, ToolCatalog, ToolSpec
from agent_sample.domain.review.model import ProposedFinding, ReviewAnswer
from agent_sample.domain.trace import Step
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


def review_service(root: Composition, defaults: ReviewOptions | None = None) -> ReviewService:
    return ReviewService(root.reviewer, root.diff_source, defaults or ReviewOptions())


# Variáveis de ambiente que mudam padrões; os testes da CLI rodam sem elas.
ENV = (
    "MODEL_API_KEY",
    "STRATEGY",
    "ENGINE",
    "AGENT",
    "PROMPT_VERSION",
    "REVIEW_STRATEGY",
    "REVIEW_ENGINE",
    "REVIEW_AGENT",
    "REVIEW_PROMPT_VERSION",
    "REVIEW_REPO",
)


def _answer(subject_id: str) -> str:
    return json.dumps({"subject_id": subject_id, "rationale": "scripted"}, ensure_ascii=False)


class FixedReviewAgent:
    """Revisor falso: carrega skills pelas ferramentas e devolve achados roteirizados."""

    name = "fixed"

    def __init__(
        self,
        findings: tuple[ProposedFinding, ...] = (),
        error: Exception | None = None,
        load: tuple[str, ...] = ("security-review",),
        summary: str = "resumo do agente",
    ) -> None:
        self._summary = summary
        self._findings = findings
        self._error = error
        self._load = load
        self.requests: list[AgentRequest] = []

    async def run(self, request: AgentRequest, tools: ToolCatalog) -> ReviewAnswer:
        self.requests.append(request)
        for skill in self._load:
            await tools.call("load_skill", {"name": skill})
        if self._error is not None:
            raise self._error
        return ReviewAnswer(self._summary, self._findings)


class ScriptedReviewGateway:
    """Modelo falso do revisor: carrega uma skill e lê um arquivo, depois responde a revisão."""

    def __init__(
        self, read: str = "app/pricing.py", findings: list[dict[str, object]] | None = None
    ):
        self.read = read
        self.findings = findings if findings is not None else []
        self.calls: list[tuple[tuple[ChatMessage, ...], tuple[ToolSpec, ...]]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] = (),
    ) -> Completion:
        self.calls.append((tuple(messages), tuple(tools)))
        if any(message.role == "tool" for message in messages):
            payload = {"summary": "revisado", "findings": self.findings}
            return Completion(text=json.dumps(payload, ensure_ascii=False))
        return Completion(
            text="",
            tool_calls=(
                ToolCall(id="call-1", name="load_skill", arguments={"name": "python-practices"}),
                ToolCall(id="call-2", name="read_repo_file", arguments={"path": self.read}),
            ),
        )


def proposal(
    path: str = "app/pricing.py", start: int | None = 2, **changes: object
) -> ProposedFinding:
    fields: dict[str, object] = {
        "path": path,
        "start": start,
        "end": None,
        "severity": "major",
        "category": "correctness",
        "description": "divide por zero com lista vazia",
        "suggestion": "trate a lista vazia",
    }
    fields.update(changes)
    return ProposedFinding(**fields)  # type: ignore[arg-type]
