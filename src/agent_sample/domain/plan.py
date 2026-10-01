"""Etapa 4: decidir, por regra explícita, se a etapa agêntica roda, sobre o quê e com quem."""

from dataclasses import dataclass

from agent_sample.domain.capabilities import LEAD_SKILL, CapabilitySet, Reviewer, Skill
from agent_sample.domain.change import PullRequestContext
from agent_sample.domain.diff import ChangeSet, FileChange
from agent_sample.domain.model import AgentUnavailable, CapabilityError, Finding, Mode
from agent_sample.domain.policy import Limits


@dataclass(frozen=True, slots=True)
class AgentTask:
    """Uma parte da mudança entregue ao revisor principal, dentro dos limites."""

    label: str
    files: tuple[FileChange, ...]
    lead: Skill
    skills: tuple[Skill, ...]
    reviewers: tuple[Reviewer, ...]
    check_findings: tuple[Finding, ...]
    focus: tuple[str, ...]
    languages: tuple[str, ...]
    context: PullRequestContext | None


@dataclass(frozen=True, slots=True)
class AgentPlan:
    run: bool
    reason: str
    tasks: tuple[AgentTask, ...] = ()
    degraded: bool = False


def plan_agentic(
    mode: Mode,
    change: ChangeSet,
    capabilities: CapabilitySet,
    check_findings: tuple[Finding, ...],
    focus: tuple[str, ...],
    language: str | None,
    context: PullRequestContext | None,
    unavailable: str | None,
    limits: Limits,
) -> AgentPlan:
    if mode == "workflow":
        return AgentPlan(False, "mode workflow: deterministic steps only")
    # Probe do modo agent: sem modelo, `--mode agent` falha claro mesmo quando a etapa
    # agêntica seria pulada (ex.: mudança só de docs). No híbrido, degrada sem erro.
    if mode == "agent" and unavailable is not None:
        raise AgentUnavailable(unavailable)
    if not change.files:
        return AgentPlan(False, "no reviewable files")
    if all(file.language == "docs" for file in change.files):
        return AgentPlan(False, "documentation-only change")
    if unavailable is not None:
        return AgentPlan(False, f"agentic review unavailable: {unavailable}", degraded=True)
    lead = capabilities.skill(LEAD_SKILL)
    if lead is None:
        raise CapabilityError(f"no enabled plugin provides the '{LEAD_SKILL}' skill")
    languages = tuple(dict.fromkeys((*change.languages, *((language,) if language else ()))))
    reviewers = tuple(
        reviewer
        for reviewer in sorted(capabilities.reviewers, key=lambda item: item.ref)
        if reviewer.applies_to(languages, focus)
    )[: limits.max_subagents]
    parts = split(change.files, limits.max_part_chars)
    tasks = tuple(
        AgentTask(
            label=f"part {index}/{len(parts)}",
            files=files,
            lead=lead,
            skills=capabilities.skills,
            reviewers=reviewers,
            check_findings=tuple(
                item for item in check_findings if item.file in {file.path for file in files}
            ),
            focus=focus,
            languages=languages,
            context=context,
        )
        for index, files in enumerate(parts, 1)
    )
    names = ", ".join(reviewer.ref for reviewer in reviewers) or "lead only"
    return AgentPlan(True, f"{len(tasks)} part(s); reviewers: {names}", tasks)


def split(files: tuple[FileChange, ...], max_chars: int) -> tuple[tuple[FileChange, ...], ...]:
    """Parte por arquivo: junta arquivos em ordem até o limite; um arquivo nunca é cortado."""
    parts: list[tuple[FileChange, ...]] = []
    current: list[FileChange] = []
    size = 0
    for file in files:
        weight = sum(len(line.text) + 2 for hunk in file.hunks for line in hunk.lines)
        if current and size + weight > max_chars:
            parts.append(tuple(current))
            current, size = [], 0
        current.append(file)
        size += weight
    if current:
        parts.append(tuple(current))
    return tuple(parts)
