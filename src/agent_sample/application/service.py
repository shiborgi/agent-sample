"""Ponto de entrada único da CLI e do A2A: traduz opções em pedido e chama o workflow."""

from collections.abc import Callable
from dataclasses import dataclass, replace

from agent_sample.domain.change import ChangeRef
from agent_sample.domain.model import MODES, Review, ReviewError, UnknownOption
from agent_sample.domain.ports import CapabilityCatalog, ProgressListener, WorkflowEngine
from agent_sample.domain.workflow import ReviewContext, ReviewRequest, run_review


@dataclass(frozen=True, slots=True)
class ReviewOptions:
    mode: str = "hybrid"
    focus: tuple[str, ...] = ()
    language: str | None = None
    plugins: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    format: str = "text"
    post: bool = False

    def merge(self, **changes: object) -> "ReviewOptions":
        """Aplica só as opções informadas; o resto segue o padrão."""
        return replace(self, **{key: value for key, value in changes.items() if value})


@dataclass(frozen=True, slots=True)
class ReviewResult:
    review: Review
    output: str


ContextFactory = Callable[[ReviewOptions], ReviewContext]


class ReviewService:
    def __init__(
        self,
        contexts: ContextFactory,
        engine: WorkflowEngine,
        catalog: CapabilityCatalog,
        defaults: ReviewOptions,
    ) -> None:
        self._contexts = contexts
        self._engine = engine
        self.catalog = catalog
        self.defaults = defaults
        self.context(defaults)

    def context(self, options: ReviewOptions) -> ReviewContext:
        if options.mode not in MODES:
            raise UnknownOption("mode", options.mode, MODES)
        return self._contexts(options)

    async def review(
        self,
        ref: ChangeRef,
        options: ReviewOptions | None = None,
        on_step: ProgressListener | None = None,
    ) -> ReviewResult:
        chosen = options or self.defaults
        request = ReviewRequest(
            ref=ref,
            mode=chosen.mode,  # type: ignore[arg-type]
            focus=chosen.focus,
            language=chosen.language,
            post=chosen.post,
        )
        state = await run_review(request, self.context(chosen), self._engine, on_step)
        if state.review is None:
            raise ReviewError("review did not finish")
        return ReviewResult(state.review, state.output)


def error_message(exc: BaseException) -> str:
    if isinstance(exc, ReviewError):
        return f"error: {exc}"
    return f"unexpected error: {type(exc).__name__}: {exc}"
