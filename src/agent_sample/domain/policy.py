"""Limites, validação dos achados propostos, consolidação e política de decisão."""

from dataclasses import dataclass

from agent_sample.domain.diff import ChangeSet
from agent_sample.domain.model import (
    CATEGORIES,
    SEVERITIES,
    Decision,
    Discarded,
    Finding,
    Origin,
    ProposedFinding,
    severity_rank,
)


@dataclass(frozen=True, slots=True)
class Limits:
    """Limites explícitos da revisão; a infra os faz valer na etapa agêntica."""

    max_tool_rounds: int = 8
    timeout_seconds: float = 120.0
    max_context_chars: int = 40_000
    max_subagents: int = 3
    max_tool_output_chars: int = 8_000
    max_part_chars: int = 20_000
    max_file_lines: int = 1_500


def validate(
    proposed: tuple[ProposedFinding, ...], change: ChangeSet
) -> tuple[tuple[Finding, ...], tuple[Discarded, ...]]:
    """Nada do agente é aceito às cegas: cada descarte sai com o motivo."""
    accepted: list[Finding] = []
    discarded: list[Discarded] = []
    for item in proposed:
        reason = _rejection(item, change)
        if reason is not None:
            location = f"{item.file}:{item.start_line}-{item.end_line}"
            discarded.append(Discarded(item.reviewer, location, item.description, reason))
            continue
        plugin, _, _ = item.reviewer.rpartition(":")
        accepted.append(
            Finding(
                file=item.file,
                start_line=item.start_line,
                end_line=item.end_line,
                severity=item.severity,  # type: ignore[arg-type]
                category=item.category,  # type: ignore[arg-type]
                description=item.description.strip(),
                suggestion=item.suggestion.strip(),
                origin=Origin("agent", item.reviewer, item.skill, plugin or None),
                evidence=item.evidence.strip(),
            )
        )
    return tuple(accepted), tuple(discarded)


def _rejection(item: ProposedFinding, change: ChangeSet) -> str | None:
    if not item.description.strip():
        return "missing description"
    if item.severity not in SEVERITIES:
        return f"severity outside the list: {item.severity!r}"
    if item.category not in CATEGORIES:
        return f"category outside the list: {item.category!r}"
    file = change.file(item.file)
    if file is None:
        return f"file not in the reviewed change: {item.file}"
    if item.end_line < item.start_line:
        return "line range is reversed"
    for line in (item.start_line, item.end_line):
        if not file.has_new_line(line):
            return f"line {line} does not exist in the new code shown by the diff"
    if not item.evidence.strip():
        return "missing evidence"
    if not file.contains(item.evidence):
        return "evidence not found in the diff"
    return None


def consolidate(checks: tuple[Finding, ...], agent: tuple[Finding, ...]) -> tuple[Finding, ...]:
    """Junta os achados; duplicados ficam uma vez só, com a origem de maior severidade.

    As checagens entram primeiro e vencem empates, então o agente não remove nem rebaixa um
    achado delas: no máximo acrescenta outro, ou um duplicado mais grave.
    """
    kept: list[Finding] = []
    for finding in (*checks, *agent):
        twin = next((item for item in kept if _duplicates(item, finding)), None)
        if twin is None:
            kept.append(finding)
        elif severity_rank(finding.severity) < severity_rank(twin.severity):
            kept[kept.index(twin)] = finding
    return tuple(sorted(kept, key=_order))


def _duplicates(left: Finding, right: Finding) -> bool:
    return (
        left.file == right.file
        and left.category == right.category
        and left.start_line <= right.end_line
        and right.start_line <= left.end_line
    )


def _order(finding: Finding) -> tuple[str, int, int, str, str, str]:
    return (
        finding.file,
        finding.start_line,
        severity_rank(finding.severity),
        finding.category,
        finding.origin.label,
        finding.description,
    )


def decide(findings: tuple[Finding, ...]) -> Decision:
    """Qualquer critical ou major → request_changes; só minor/nit → comment; nada → approve."""
    if any(finding.severity in ("critical", "major") for finding in findings):
        return "request_changes"
    if findings:
        return "comment"
    return "approve"


def summarize(change: ChangeSet, findings: tuple[Finding, ...], decision: Decision) -> str:
    languages = ", ".join(change.languages) or "no code"
    parts = [f"{len(change.files)} file(s) reviewed ({languages})"]
    if findings:
        counts = [
            f"{count} {severity}"
            for severity in SEVERITIES
            if (count := sum(1 for item in findings if item.severity == severity))
        ]
        parts.append(f"{len(findings)} finding(s): {', '.join(counts)}")
    else:
        parts.append("no findings")
    if change.unreviewed:
        parts.append(f"{len(change.unreviewed)} file(s) not reviewed")
    return f"{'; '.join(parts)}. Decision: {decision}."
