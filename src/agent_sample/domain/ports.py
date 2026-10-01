"""Portas com significado de revisão. Nenhuma fala de URL, verbo HTTP, git, arquivo ou framework."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from agent_sample.domain.capabilities import CapabilitySet, Conflict, Plugin
from agent_sample.domain.change import PullRequestContext
from agent_sample.domain.model import ProposedFinding, Review, StepRecord

if TYPE_CHECKING:
    from agent_sample.domain.plan import AgentTask
    from agent_sample.domain.policy import Limits
    from agent_sample.domain.workflow import ReviewContext, ReviewState, WorkflowStep


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Contrato de uma ferramenta oferecida ao agente, independente do framework."""

    name: str
    description: str
    parameters: dict[str, Any]


class ToolCatalog(Protocol):
    def specs(self) -> tuple[ToolSpec, ...]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> str: ...


class RevisionSource(Protocol):
    """Obter a mudança entre duas referências de um repositório local."""

    async def diff(self, repository: str, base: str, head: str) -> str: ...


class PullRequestHost(Protocol):
    """Pull requests de um provedor remoto: obter mudança, obter contexto, publicar revisão."""

    name: str

    def handles(self, locator: str) -> bool: ...

    async def get_change(self, locator: str) -> str: ...

    async def get_context(self, locator: str) -> PullRequestContext: ...

    async def publish(self, locator: str, review: Review) -> str: ...


class RepositoryReader(Protocol):
    """Leitura somente do repositório revisado. Caminhos já chegam relativos e normalizados."""

    async def read(self, path: str, start: int | None, end: int | None) -> str: ...

    async def search(self, query: str) -> tuple[str, ...]: ...

    async def list(self, directory: str) -> tuple[str, ...]: ...

    async def blame(self, path: str, start: int, end: int) -> str: ...


class ReaderFactory(Protocol):
    def open(self, repository: str, revision: str | None) -> RepositoryReader: ...


@dataclass(frozen=True, slots=True)
class AgentOutcome:
    """O que a etapa agêntica devolve: achados propostos e revisores acionados."""

    proposed: tuple[ProposedFinding, ...]
    reviewers: tuple[str, ...] = ()


class AgentReviewer(Protocol):
    """Porta da etapa agêntica. Mensagens, grafo, middleware e tool calls ficam na infra."""

    name: str

    def unavailable(self) -> str | None:
        """Motivo pelo qual a etapa não pode rodar, ou `None` se pode."""
        ...

    async def review(
        self, task: "AgentTask", tools: ToolCatalog, limits: "Limits"
    ) -> AgentOutcome: ...


class Renderer(Protocol):
    name: str

    def render(self, review: Review) -> str: ...


class CapabilityCatalog(Protocol):
    def plugins(self) -> tuple[Plugin, ...]: ...

    def enabled(self, plugin: Plugin) -> bool: ...

    def conflicts(self) -> tuple[Conflict, ...]: ...

    def select(self, pins: tuple[str, ...], skills: tuple[str, ...] = ()) -> CapabilitySet: ...


ProgressListener = Callable[[StepRecord], Awaitable[None]]


class WorkflowEngine(Protocol):
    name: str

    async def run(
        self,
        steps: Sequence["WorkflowStep"],
        state: "ReviewState",
        context: "ReviewContext",
        on_step: ProgressListener | None = None,
    ) -> "ReviewState": ...
