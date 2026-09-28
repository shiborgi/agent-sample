from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from agent_sample.domain.content import AgentRequest, PromptVersion, SkillVersion
from agent_sample.domain.model import Verdict
from agent_sample.domain.workflow import WorkflowStep


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Contrato de uma ferramenta oferecida ao agente, independente do framework."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Prediction:
    subject_id: str
    confidence: float | None


class ToolCatalog(Protocol):
    def specs(self) -> tuple[ToolSpec, ...]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> str: ...


class WorkflowEngine(Protocol):
    """Executa em ordem as etapas que o domínio define, para qualquer estado."""

    name: str

    async def run[S](self, steps: Sequence[WorkflowStep[S]], state: S) -> S: ...


class Agent[T](Protocol):
    """Um modelo que raciocina, decide quando usar ferramentas e devolve a resposta final.

    `T` é a resposta da tarefa (veredito, revisão). Como o prompt vira mensagens e como a
    resposta do modelo é lida é problema da infra.
    """

    name: str

    async def run(self, request: AgentRequest, tools: ToolCatalog) -> T: ...


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
