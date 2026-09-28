from collections.abc import Callable
from dataclasses import dataclass, replace

from agent_sample.domain.rules import Matches, RuleOutcome, decide, match, tokenize


@dataclass(frozen=True, slots=True)
class WorkflowState:
    text: str
    tokens: tuple[str, ...] = ()
    matches: Matches = ()
    outcome: RuleOutcome | None = None


@dataclass(frozen=True, slots=True)
class WorkflowStep[S]:
    """Uma etapa do workflow: função pura do estado. Serve a qualquer caso de uso."""

    name: str
    run: Callable[[S], S]


def _normalize(state: WorkflowState) -> WorkflowState:
    return replace(state, tokens=tokenize(state.text))


def _match(state: WorkflowState) -> WorkflowState:
    return replace(state, matches=match(state.tokens))


def _decide(state: WorkflowState) -> WorkflowState:
    return replace(state, outcome=decide(state.matches))


# O workflow determinístico: o domínio define as etapas; os motores só as executam em ordem.
WORKFLOW: tuple[WorkflowStep[WorkflowState], ...] = (
    WorkflowStep("normalize", _normalize),
    WorkflowStep("match", _match),
    WorkflowStep("decide", _decide),
)
