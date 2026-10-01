"""O contrato da revisão: achados, decisão, arquivos não revisados e o caminho percorrido."""

from dataclasses import dataclass
from typing import Literal

SEVERITIES: tuple[str, ...] = ("critical", "major", "minor", "nit")
CATEGORIES: tuple[str, ...] = (
    "correctness",
    "security",
    "performance",
    "maintainability",
    "tests",
    "style",
)
MODES: tuple[str, ...] = ("workflow", "hybrid", "agent")

Severity = Literal["critical", "major", "minor", "nit"]
Category = Literal["correctness", "security", "performance", "maintainability", "tests", "style"]
Decision = Literal["approve", "comment", "request_changes"]
Mode = Literal["workflow", "hybrid", "agent"]
Nature = Literal["deterministic", "agentic"]
StepOutcome = Literal["ok", "skipped", "failed", "degraded"]


def severity_rank(severity: str) -> int:
    """Menor é mais grave: critical=0 ... nit=3."""
    return SEVERITIES.index(severity)


class ReviewError(Exception):
    """Erro esperado da revisão, com mensagem pronta para quem usa."""


class EmptyDiff(ReviewError, ValueError):
    def __init__(self) -> None:
        super().__init__("diff is empty: nothing to review")


class InvalidDiff(ReviewError, ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"diff is not a readable unified diff: {reason}")


class ChangeNotFound(ReviewError, LookupError):
    def __init__(self, what: str) -> None:
        super().__init__(f"change not found: {what}")


class UnknownOption(ReviewError, ValueError):
    def __init__(self, kind: str, value: str, choices: tuple[str, ...]) -> None:
        super().__init__(f"unknown {kind}: {value} (choose from {', '.join(choices)})")


class CapabilityError(ReviewError, ValueError):
    """Plugin, skill ou revisor inválido, inexistente, incompatível ou divergente do lock."""


class AgentUnavailable(ReviewError, RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"agentic review unavailable: {reason}")


class AgentLimitExceeded(ReviewError, RuntimeError):
    def __init__(self, limit: str) -> None:
        super().__init__(f"agentic review exceeded its limit: {limit}")


class RemoteError(ReviewError, RuntimeError):
    """Falha ao falar com o provedor remoto, já traduzida para quem usa."""


class PublishNotAllowed(ReviewError, ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"cannot publish: {reason}")


@dataclass(frozen=True, slots=True)
class Origin:
    """Quem produziu o achado: uma checagem determinística ou um revisor agêntico."""

    kind: Literal["check", "agent"]
    name: str
    skill: str | None = None
    plugin: str | None = None

    @property
    def label(self) -> str:
        label = f"{self.kind}:{self.name}"
        if self.skill:
            label += f" skill={self.skill}"
        if self.plugin:
            label += f" plugin={self.plugin}"
        return label


@dataclass(frozen=True, slots=True)
class Finding:
    file: str
    start_line: int
    end_line: int
    severity: Severity
    category: Category
    description: str
    suggestion: str
    origin: Origin
    evidence: str

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"invalid severity: {self.severity}")
        if self.category not in CATEGORIES:
            raise ValueError(f"invalid category: {self.category}")
        if self.end_line < self.start_line:
            raise ValueError("end_line must not come before start_line")

    @property
    def location(self) -> str:
        if self.start_line == self.end_line:
            return f"{self.file}:{self.start_line}"
        return f"{self.file}:{self.start_line}-{self.end_line}"


@dataclass(frozen=True, slots=True)
class ProposedFinding:
    """O que um revisor agêntico propôs, antes de validar. Campos ainda não confiáveis."""

    file: str
    start_line: int
    end_line: int
    severity: str
    category: str
    description: str
    suggestion: str
    evidence: str
    reviewer: str
    skill: str | None = None


@dataclass(frozen=True, slots=True)
class Unreviewed:
    file: str
    reason: str


@dataclass(frozen=True, slots=True)
class StepRecord:
    name: str
    nature: Nature
    outcome: StepOutcome
    detail: str


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    tool: str
    arguments: str
    outcome: str


@dataclass(frozen=True, slots=True)
class Discarded:
    reviewer: str
    location: str
    description: str
    reason: str


@dataclass(frozen=True, slots=True)
class Trace:
    """O caminho percorrido até a revisão."""

    steps: tuple[StepRecord, ...] = ()
    reviewers: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    skills_loaded: tuple[str, ...] = ()
    tool_calls: tuple[ToolCallRecord, ...] = ()
    discarded: tuple[Discarded, ...] = ()
    failures: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Review:
    decision: Decision
    summary: str
    findings: tuple[Finding, ...]
    unreviewed: tuple[Unreviewed, ...]
    trace: Trace
