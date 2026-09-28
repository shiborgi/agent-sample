"""O resultado do agente não é aceito às cegas: cada achado é validado contra o diff."""

from typing import cast

from agent_sample.domain.review.diff import FileChange
from agent_sample.domain.review.model import (
    CATEGORIES,
    SEVERITIES,
    Category,
    Finding,
    ProposedFinding,
    Severity,
)
from agent_sample.domain.review.secrets import diff_secrets, mask_secrets
from agent_sample.domain.trace import Step


def validate(
    proposals: tuple[ProposedFinding, ...],
    files: tuple[FileChange, ...],
    source: str,
) -> tuple[tuple[Finding, ...], tuple[Step, ...]]:
    """Aceita só achados em arquivos e linhas do código novo do diff; registra cada descarte.

    A evidência do achado aceito vem sempre do diff, nunca do texto do agente, e segredos são
    mascarados em tudo o que o achado mostra.
    """
    by_path = {file.path: file for file in files}
    known = diff_secrets(files)
    accepted: list[Finding] = []
    discarded: list[Step] = []
    for proposal in proposals:
        file = by_path.get(proposal.path)
        end = proposal.end if proposal.end is not None else proposal.start
        reason = _problem(proposal, file, end)
        if reason is not None:
            discarded.append(_discard(proposal, reason))
            continue
        assert file is not None and proposal.start is not None and end is not None
        accepted.append(
            Finding(
                path=proposal.path,
                start=proposal.start,
                end=end,
                severity=cast(Severity, proposal.severity),
                category=cast(Category, proposal.category),
                description=mask_secrets(proposal.description.strip(), known),
                suggestion=mask_secrets(proposal.suggestion.strip(), known),
                origin="agent",
                source=source,
                evidence=mask_secrets(file.evidence(proposal.start, end)),
            )
        )
    return tuple(accepted), tuple(discarded)


def merge(
    rules: tuple[Finding, ...], agent: tuple[Finding, ...]
) -> tuple[tuple[Finding, ...], tuple[Step, ...]]:
    """Junta os achados. Os das regras ficam intactos: o agente só acrescenta.

    Duplicado é o mesmo arquivo, a mesma categoria e linhas sobrepostas; aparece uma vez só.
    """
    kept = list(rules)
    discarded: list[Step] = []
    for finding in agent:
        twin = next((other for other in kept if _same(finding, other)), None)
        if twin is None:
            kept.append(finding)
            continue
        discarded.append(
            Step(
                "validation",
                "duplicate",
                "discarded",
                f"{finding.path}:{finding.start} ({finding.source}) duplica "
                f"{twin.severity}/{twin.category} de {twin.source}",
            )
        )
    return tuple(kept), tuple(discarded)


def _problem(proposal: ProposedFinding, file: FileChange | None, end: int | None) -> str | None:
    if file is None:
        return f"arquivo fora do diff revisado: {proposal.path or '(vazio)'}"
    if not proposal.description.strip():
        return "achado sem descrição"
    if proposal.severity not in SEVERITIES:
        return f"severidade inválida: {proposal.severity or '(vazia)'}"
    if proposal.category not in CATEGORIES:
        return f"categoria inválida: {proposal.category or '(vazia)'}"
    if proposal.start is None or end is None or proposal.start < 1 or end < proposal.start:
        return f"intervalo de linhas inválido: {proposal.start}..{end}"
    visible = file.new_lines
    if proposal.start not in visible or end not in visible:
        return f"linha {proposal.start}..{end} não existe no código novo do diff"
    return None


def _discard(proposal: ProposedFinding, reason: str) -> Step:
    where = f"{proposal.path or '?'}:{proposal.start if proposal.start is not None else '?'}"
    return Step("validation", "agent-finding", "discarded", f"{where} — {reason}")


def _same(left: Finding, right: Finding) -> bool:
    return (
        left.path == right.path
        and left.category == right.category
        and left.start <= right.end
        and right.start <= left.end
    )
