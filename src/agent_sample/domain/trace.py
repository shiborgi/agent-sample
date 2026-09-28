from dataclasses import dataclass
from typing import Literal

StepKind = Literal["workflow", "agent", "prediction", "fallback", "validation", "decision"]
Outcome = Literal["decided", "undecided", "failed", "completed", "discarded", "skipped"]


@dataclass(frozen=True, slots=True)
class Step:
    """Uma etapa do caminho até o resultado (veredito ou revisão)."""

    kind: StepKind
    name: str
    outcome: Outcome
    detail: str
    prompt: str | None = None
    skills: tuple[str, ...] = ()
