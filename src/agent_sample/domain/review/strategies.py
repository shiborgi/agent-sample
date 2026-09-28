import logging
from collections import Counter

from agent_sample.domain.content import AgentRequest, PromptVersion, SkillVersion
from agent_sample.domain.errors import AgentAttemptFailed
from agent_sample.domain.ports import Agent, WorkflowEngine
from agent_sample.domain.review.change import Change, split_parts, triage
from agent_sample.domain.review.diff import FileChange
from agent_sample.domain.review.model import (
    SEVERITIES,
    Finding,
    Review,
    ReviewAnswer,
    Unreviewed,
    decide,
)
from agent_sample.domain.review.policy import MAX_PART_CHARS, MAX_REVIEW_TOOL_ROUNDS
from agent_sample.domain.review.ports import Repository
from agent_sample.domain.review.secrets import diff_secrets, mask_secrets
from agent_sample.domain.review.tools import REVIEW_TOOLS, ReviewContext
from agent_sample.domain.review.validation import merge, validate
from agent_sample.domain.review.workflow import REVIEW_WORKFLOW, ReviewState
from agent_sample.domain.tools import Toolbox
from agent_sample.domain.trace import Outcome, Step

logger = logging.getLogger(__name__)

AgentOutcome = tuple[tuple[Finding, ...], tuple[str, ...], tuple[Step, ...]]
"""Achados aceitos, resumos do agente por parte e os passos do caminho."""


class WorkflowReviewer:
    """Checagens explícitas e reproduzíveis: mesmo diff, mesma revisão."""

    def __init__(self, engine: WorkflowEngine) -> None:
        self._engine = engine
        self.name = f"workflow:{engine.name}"

    async def inspect(self, change: Change) -> tuple[ReviewState, tuple[Step, ...]]:
        state = await self._engine.run(REVIEW_WORKFLOW, ReviewState(change))
        steps = tuple(
            Step("workflow", f"{self._engine.name}/{name}", "completed", detail)
            for name, detail in state.log
        )
        return state, steps

    async def review(self, change: Change) -> Review:
        state, steps = await self.inspect(change)
        return conclude(change, state.findings, state.unreviewed, self.name, steps)


class AgentReviewer:
    """Um agente lê a mudança por partes, investiga com ferramentas e propõe achados."""

    def __init__(
        self,
        agent: Agent[ReviewAnswer],
        prompt: PromptVersion,
        skills: tuple[SkillVersion, ...],
        repository: Repository | None,
        part_chars: int = MAX_PART_CHARS,
    ) -> None:
        self._agent = agent
        self._prompt = prompt
        self._skills = skills
        self._repository = repository
        self._part_chars = part_chars
        self.name = f"agent:{agent.name}"

    async def consult(
        self, change: Change, files: tuple[FileChange, ...], rules: tuple[Finding, ...]
    ) -> AgentOutcome:
        """Revisa cada parte; a primeira falha interrompe e vira `AgentAttemptFailed`."""
        parts = split_parts(files, self._part_chars)
        if not parts:
            return (), (), (Step("agent", self._agent.name, "skipped", "nada a revisar"),)
        findings: list[Finding] = []
        summaries: list[str] = []
        steps: list[Step] = []
        for index, part in enumerate(parts, 1):
            label = f"parte {index}/{len(parts)} ({', '.join(file.path for file in part)})"
            toolbox = Toolbox(ReviewContext(self._skills, self._repository), REVIEW_TOOLS)
            request = AgentRequest(
                agent_input(change, part, label, rules),
                self._prompt,
                self._skills,
                MAX_REVIEW_TOOL_ROUNDS,
            )
            try:
                answer = await self._agent.run(request, toolbox)
            except Exception as exc:
                raise AgentAttemptFailed(
                    self._step("failed", f"{label}: {exc}", toolbox), exc
                ) from exc
            accepted, discarded = validate(answer.findings, part, self.name)
            detail = f"{label}: {len(accepted)} achado(s) aceito(s), {len(discarded)} descartado(s)"
            steps.extend((self._step("completed", detail, toolbox), *discarded))
            findings.extend(accepted)
            if answer.summary.strip():
                summaries.append(mask_secrets(answer.summary.strip(), diff_secrets(part)))
        return tuple(findings), tuple(summaries), tuple(steps)

    async def review(self, change: Change) -> Review:
        files, unreviewed = triage(change.files)
        found, summaries, steps = await self.consult(change, files, ())
        findings, duplicates = merge((), found)
        return conclude(change, findings, unreviewed, self.name, (*steps, *duplicates), summaries)

    def _step(self, outcome: Outcome, detail: str, toolbox: Toolbox[ReviewContext]) -> Step:
        return Step(
            "agent",
            self._agent.name,
            outcome,
            detail,
            prompt=self._prompt.ref,
            skills=toolbox.loaded_skills,
        )


class HybridReviewer:
    """Regras primeiro; o agente recebe os achados delas e só pode acrescentar.

    Se o agente falhar, a revisão sai com os achados das regras e registra a falha.
    """

    def __init__(self, workflow: WorkflowReviewer, agent: AgentReviewer) -> None:
        self._workflow = workflow
        self._agent = agent
        self.name = f"hybrid({workflow.name}->{agent.name})"

    async def review(self, change: Change) -> Review:
        state, rules = await self._workflow.inspect(change)
        try:
            found, summaries, steps = await self._agent.consult(change, state.files, state.findings)
        except AgentAttemptFailed as exc:
            logger.warning("hybrid review fell back to rules only: %s", exc)
            fallback = Step(
                "fallback", "rules-only", "decided", "revisão só com os achados das regras"
            )
            note = f"O agente falhou e a revisão tem só os achados das regras ({exc})."
            trace = (*rules, exc.step, fallback)
            return conclude(
                change, state.findings, state.unreviewed, self._workflow.name, trace, (note,)
            )
        findings, duplicates = merge(state.findings, found)
        trace = (*rules, *steps, *duplicates)
        return conclude(change, findings, state.unreviewed, self.name, trace, summaries)


def conclude(
    change: Change,
    findings: tuple[Finding, ...],
    unreviewed: tuple[Unreviewed, ...],
    reviewed_by: str,
    trace: tuple[Step, ...],
    notes: tuple[str, ...] = (),
) -> Review:
    """Ordena os achados, aplica a regra de decisão e escreve um resumo determinístico."""
    ordered = tuple(
        sorted(findings, key=lambda item: (item.rank, item.path, item.start, item.category))
    )
    decision = decide(ordered)
    counts = Counter(finding.severity for finding in ordered)
    decided = Step(
        "decision",
        "policy",
        "decided",
        f"{decision}: " + (_counts(counts) if ordered else "nenhum achado"),
    )
    return Review(
        decision=decision,
        summary=_summary(change, ordered, unreviewed, counts, notes),
        findings=ordered,
        unreviewed=unreviewed,
        reviewed_by=reviewed_by,
        trace=(*trace, decided),
    )


def agent_input(
    change: Change, part: tuple[FileChange, ...], label: str, rules: tuple[Finding, ...]
) -> str:
    """A entrada da tarefa para o agente: a parte do diff, o foco e os achados das regras."""
    paths = {file.path for file in part}
    known = [
        f"- {item.path}:{item.start}-{item.end} {item.severity}/{item.category}: {item.description}"
        for item in rules
        if item.path in paths
    ]
    languages = sorted({file.language for file in part if file.language})
    lines = [
        f"Revisão da {label}.",
        f"Foco pedido: {', '.join(change.focus) if change.focus else 'todas as categorias'}.",
        f"Linguagens: {', '.join(languages) if languages else 'não identificadas'}.",
        "Achados das regras nesta parte (já registrados; não repita):",
        *(known or ["- nenhum"]),
        "",
        "Diff:",
        *(file.text for file in part),
    ]
    return "\n".join(lines)


def _counts(counts: Counter[str]) -> str:
    return ", ".join(f"{counts[level]} {level}" for level in SEVERITIES if counts[level])


def _summary(
    change: Change,
    findings: tuple[Finding, ...],
    unreviewed: tuple[Unreviewed, ...],
    counts: Counter[str],
    notes: tuple[str, ...],
) -> str:
    added = sum(len(file.added) for file in change.files)
    removed = sum(file.removed_count for file in change.files)
    parts = [f"{len(change.files)} arquivo(s) alterado(s), +{added}/-{removed} linhas."]
    parts.append(f"{len(findings)} achado(s): {_counts(counts)}." if findings else "Nenhum achado.")
    if unreviewed:
        parts.append(f"{len(unreviewed)} arquivo(s) não revisado(s).")
    parts.extend(notes)
    return " ".join(parts)
