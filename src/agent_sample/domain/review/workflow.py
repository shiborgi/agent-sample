from dataclasses import dataclass, replace

from agent_sample.domain.review.change import Change, triage
from agent_sample.domain.review.checks import CHECKS, Check
from agent_sample.domain.review.diff import FileChange
from agent_sample.domain.review.model import Finding, Unreviewed
from agent_sample.domain.workflow import WorkflowStep


@dataclass(frozen=True, slots=True)
class ReviewState:
    change: Change
    files: tuple[FileChange, ...] = ()
    unreviewed: tuple[Unreviewed, ...] = ()
    findings: tuple[Finding, ...] = ()
    log: tuple[tuple[str, str], ...] = ()
    """(etapa, o que ela fez): vira o caminho da revisão."""


def _triage(state: ReviewState) -> ReviewState:
    files, unreviewed = triage(state.change.files)
    skipped = "; ".join(f"{item.path} ({item.reason})" for item in unreviewed)
    detail = f"{len(files)} arquivo(s) revisável(is)" + (
        f"; não revisados: {skipped}" if skipped else ""
    )
    return replace(state, files=files, unreviewed=unreviewed, log=(*state.log, ("triage", detail)))


def _check(check: Check) -> WorkflowStep[ReviewState]:
    def run(state: ReviewState) -> ReviewState:
        found = check.run(state.change, state.files)
        detail = f"{len(found)} achado(s)" if found else "nenhum achado"
        return replace(
            state, findings=(*state.findings, *found), log=(*state.log, (check.name, detail))
        )

    return WorkflowStep(check.name, run)


# O workflow de revisão: triagem e uma etapa por checagem. Os motores só executam em ordem.
REVIEW_WORKFLOW: tuple[WorkflowStep[ReviewState], ...] = (
    WorkflowStep("triage", _triage),
    *(_check(check) for check in CHECKS),
)
