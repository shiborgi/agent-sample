from dataclasses import dataclass
from typing import Literal

from agent_sample.domain.errors import DomainError
from agent_sample.domain.trace import Step

Severity = Literal["critical", "major", "minor", "nit"]
Category = Literal["correctness", "security", "performance", "maintainability", "tests", "style"]
Decision = Literal["approve", "comment", "request_changes"]
Origin = Literal["rule", "agent"]

# Da mais grave para a menos grave; a ordem é usada para ordenar e para decidir.
SEVERITIES: tuple[Severity, ...] = ("critical", "major", "minor", "nit")
CATEGORIES: tuple[Category, ...] = (
    "correctness",
    "security",
    "performance",
    "maintainability",
    "tests",
    "style",
)


class ReviewError(DomainError):
    """Erro esperado da revisão, com mensagem pronta para quem usa."""


class EmptyDiff(ReviewError, ValueError):
    def __init__(self) -> None:
        super().__init__("diff is empty")


class InvalidDiff(ReviewError, ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"diff is not a readable unified diff: {reason}")


class DiffUnavailable(ReviewError, RuntimeError):
    """Não foi possível obter o diff (arquivo, git)."""


class RepositoryError(ReviewError):
    """Acesso ao repositório revisado recusado ou impossível."""


@dataclass(frozen=True, slots=True)
class Finding:
    """Um problema apontado no código novo, com a evidência tirada do diff."""

    path: str
    start: int
    end: int
    severity: Severity
    category: Category
    description: str
    suggestion: str
    origin: Origin
    source: str
    evidence: str

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity: {self.severity}")
        if self.category not in CATEGORIES:
            raise ValueError(f"unknown category: {self.category}")
        if not 1 <= self.start <= self.end:
            raise ValueError("finding needs 1 <= start <= end")
        if not self.description.strip():
            raise ValueError("finding needs a description")

    @property
    def rank(self) -> int:
        return SEVERITIES.index(self.severity)


@dataclass(frozen=True, slots=True)
class Unreviewed:
    """Arquivo do diff que ninguém revisou (binário, grande), com o motivo."""

    path: str
    reason: str


# Política de decisão: explícita, documentada e a única forma de chegar a uma decisão.
DECISION_RULE = (
    "qualquer achado critical ou major → request_changes; "
    "só minor ou nit → comment; nenhum achado → approve"
)


def decide(findings: tuple[Finding, ...]) -> Decision:
    severities = {finding.severity for finding in findings}
    if severities & {"critical", "major"}:
        return "request_changes"
    if severities:
        return "comment"
    return "approve"


@dataclass(frozen=True, slots=True)
class Review:
    decision: Decision
    summary: str
    findings: tuple[Finding, ...]
    unreviewed: tuple[Unreviewed, ...]
    reviewed_by: str
    trace: tuple[Step, ...]

    def __post_init__(self) -> None:
        if not self.trace:
            raise ValueError("review needs the path that led to it")
        if self.decision != decide(self.findings):
            raise ValueError(f"decision {self.decision} does not follow the decision rule")


@dataclass(frozen=True, slots=True)
class ProposedFinding:
    """Achado como o agente o propôs: ainda não validado, campos podem estar errados."""

    path: str
    start: int | None
    end: int | None
    severity: str
    category: str
    description: str
    suggestion: str


@dataclass(frozen=True, slots=True)
class ReviewAnswer:
    """A resposta final do agente revisor, já fora do formato do modelo."""

    summary: str
    findings: tuple[ProposedFinding, ...]
