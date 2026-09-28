from collections.abc import Callable
from dataclasses import dataclass

from agent_sample.application.service import Options
from agent_sample.domain.review.model import Review
from agent_sample.domain.review.ports import ChangeReviewer, DiffSource
from agent_sample.domain.review.session import review_change


@dataclass(frozen=True, slots=True)
class ReviewOptions(Options):
    strategy: str = "hybrid"
    engine: str = "sequential"
    agent: str = "langgraph"
    prompt_version: str | None = None
    skills: tuple[str, ...] = ()
    focus: tuple[str, ...] = ()
    language: str | None = None
    repo: str | None = None
    """Repositório lido pelas ferramentas do agente e pelo git. Nunca vem de um cliente remoto."""


ReviewerFactory = Callable[[ReviewOptions], ChangeReviewer]
DiffSources = Callable[[str | None], DiffSource]


@dataclass(frozen=True, slots=True)
class ReviewRow:
    name: str
    review: Review | None
    error: str | None


class ReviewService:
    """Ponto de entrada único da CLI e do A2A para revisar."""

    def __init__(
        self, factory: ReviewerFactory, sources: DiffSources, defaults: ReviewOptions
    ) -> None:
        self._factory = factory
        self._sources = sources
        self.defaults = defaults

    def build(self, options: ReviewOptions) -> ChangeReviewer:
        return self._factory(options)

    async def review(self, diff: str, options: ReviewOptions | None = None) -> Review:
        options = options or self.defaults
        return await review_change(diff, self.build(options), options.focus, options.language)

    def diff_between(self, base: str, head: str, options: ReviewOptions) -> str:
        return self._sources(options.repo).between(base, head)

    async def compare(
        self, diff: str, variants: tuple[tuple[str, ReviewOptions], ...]
    ) -> tuple[ReviewRow, ...]:
        """Revisa o mesmo diff com cada variante; a falha de uma não esconde as outras."""
        rows: list[ReviewRow] = []
        for name, options in variants:
            try:
                rows.append(ReviewRow(name, await self.review(diff, options), None))
            except Exception as exc:
                rows.append(ReviewRow(name, None, str(exc)))
        return tuple(rows)
