from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class Subject:
    id: str
    name: str
    description: str


SUBJECTS: tuple[Subject, ...] = (
    Subject("billing", "Cobrança", "faturas, pagamentos, reembolsos e cobrança duplicada"),
    Subject("technical", "Técnico", "erros, indisponibilidade, bugs e acesso"),
    Subject("sales", "Comercial", "preço, contrato, demonstração e upgrade"),
    Subject("other", "Outro", "qualquer assunto fora de cobrança, técnico ou comercial"),
)

SAFE_SUBJECT = "other"


class SubjectError(Exception):
    """Erro esperado da classificação, com mensagem pronta para quem usa."""


class UnknownSubject(SubjectError, ValueError):
    def __init__(self, subject_id: str) -> None:
        self.subject_id = subject_id
        super().__init__(f"unknown subject: {subject_id}")


class EmptyMessage(SubjectError, ValueError):
    def __init__(self) -> None:
        super().__init__("message is empty")


class ClassificationFailed(SubjectError, RuntimeError):
    def __init__(self, source: str, reason: str) -> None:
        self.source = source
        self.reason = reason
        super().__init__(f"{source}: {reason}")


class ModelUnavailable(SubjectError, RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"model unavailable: {reason}")


class UnknownOption(SubjectError, ValueError):
    def __init__(self, kind: str, value: str, choices: tuple[str, ...]) -> None:
        super().__init__(f"unknown {kind}: {value} (choose from {', '.join(choices)})")


class ContentError(SubjectError, ValueError):
    """Prompt ou skill inválido, inexistente ou alterado depois de publicado."""


def subject_by_id(subject_id: str) -> Subject:
    for subject in SUBJECTS:
        if subject.id == subject_id:
            return subject
    raise UnknownSubject(subject_id)


StepKind = Literal["workflow", "agent", "prediction", "fallback"]
Outcome = Literal["decided", "undecided", "failed"]


@dataclass(frozen=True, slots=True)
class Step:
    """Uma etapa do caminho até o veredito."""

    kind: StepKind
    name: str
    outcome: Outcome
    detail: str
    prompt: str | None = None
    skills: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Verdict:
    subject_id: str
    rationale: str
    decided_by: str
    trace: tuple[Step, ...]
    confidence: float | None = None

    def __post_init__(self) -> None:
        subject_by_id(self.subject_id)
        if not self.trace:
            raise ValueError("verdict needs the path that led to it")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
