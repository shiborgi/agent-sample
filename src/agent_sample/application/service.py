from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Self

from agent_sample.domain.errors import DomainError
from agent_sample.domain.model import Verdict
from agent_sample.domain.ports import SubjectClassifier
from agent_sample.domain.session import classify_subject


class Options:
    """Base das opções de cada caso de uso (dataclasses congeladas)."""

    __slots__ = ()

    def merge(self, **changes: object) -> Self:
        """Aplica só as opções informadas; o resto segue o padrão."""
        return replace(self, **{key: value for key, value in changes.items() if value})  # type: ignore[type-var]


@dataclass(frozen=True, slots=True)
class ClassifyOptions(Options):
    strategy: str = "hybrid"
    engine: str = "sequential"
    agent: str = "langgraph"
    prompt_version: str | None = None
    skills: tuple[str, ...] = ()


ClassifierFactory = Callable[[ClassifyOptions], SubjectClassifier]


class ClassificationService:
    """Ponto de entrada único da CLI e do A2A para classificar."""

    def __init__(self, factory: ClassifierFactory, defaults: ClassifyOptions) -> None:
        self._factory = factory
        self.defaults = defaults

    def build(self, options: ClassifyOptions) -> SubjectClassifier:
        return self._factory(options)

    async def classify(self, text: str, options: ClassifyOptions | None = None) -> Verdict:
        return await classify_subject(text, self.build(options or self.defaults))


def error_message(exc: BaseException) -> str:
    if isinstance(exc, DomainError):
        return f"error: {exc}"
    return f"unexpected error: {type(exc).__name__}: {exc}"
