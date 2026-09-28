from dataclasses import dataclass


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


class UnknownSubject(ValueError):
    def __init__(self, subject_id: str) -> None:
        self.subject_id = subject_id
        super().__init__(f"unknown subject: {subject_id}")


class EmptyMessage(ValueError):
    def __init__(self) -> None:
        super().__init__("message is empty")


class ClassificationFailed(RuntimeError):
    def __init__(self, runtime: str, reason: str) -> None:
        self.runtime = runtime
        self.reason = reason
        super().__init__(f"{runtime}: {reason}")


def subject_by_id(subject_id: str) -> Subject:
    for subject in SUBJECTS:
        if subject.id == subject_id:
            return subject
    raise UnknownSubject(subject_id)


@dataclass(frozen=True, slots=True)
class Verdict:
    subject_id: str
    confidence: float | None
    rationale: str
    runtime: str

    def __post_init__(self) -> None:
        subject_by_id(self.subject_id)
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
