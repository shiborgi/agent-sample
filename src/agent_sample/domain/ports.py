from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from agent_sample.domain.content import PromptVersion, SkillVersion
from agent_sample.domain.model import Verdict
from agent_sample.domain.workflow import WorkflowState, WorkflowStep


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class Prediction:
    subject_id: str
    confidence: float | None


class ModelGateway(Protocol):
    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] = (),
    ) -> Completion: ...


class ToolCatalog(Protocol):
    def specs(self) -> tuple[ToolSpec, ...]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> str: ...


class WorkflowEngine(Protocol):
    name: str

    async def run(self, steps: Sequence[WorkflowStep], state: WorkflowState) -> WorkflowState: ...


class Agent(Protocol):
    """Um modelo que raciocina, decide quando usar ferramentas e devolve a resposta final."""

    name: str

    async def run(self, system: str, user: str, tools: ToolCatalog) -> str: ...


class Predictor(Protocol):
    """Predição de passo único: não raciocina nem usa ferramentas."""

    name: str

    async def predict(self, text: str) -> Prediction: ...


class ContentLibrary(Protocol):
    def prompt(self, name: str, version: str | None = None) -> PromptVersion: ...

    def skill(self, name: str, version: str | None = None) -> SkillVersion: ...

    def prompts(self) -> tuple[PromptVersion, ...]: ...

    def skills(self) -> tuple[SkillVersion, ...]: ...

    def publish(self, kind: str, name: str, version: str) -> str: ...


class SubjectClassifier(Protocol):
    name: str

    async def classify(self, text: str) -> Verdict: ...
