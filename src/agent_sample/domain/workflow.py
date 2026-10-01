"""O workflow de revisão: o domínio define etapas, ordem e o que cada uma pode fazer.

Um motor (`WorkflowEngine`) só executa as etapas em ordem. A etapa 5 é a única agêntica; a 9 é a
única que escreve fora do processo.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace

from agent_sample.domain.capabilities import CapabilitySet
from agent_sample.domain.change import ChangeRef, InlineDiff, PullRequest, RawChange, RevisionRange
from agent_sample.domain.checks import CHECKS, Check, run_checks
from agent_sample.domain.diff import ChangeSet, normalize, parse_diff
from agent_sample.domain.model import (
    Decision,
    Finding,
    Mode,
    Nature,
    ProposedFinding,
    PublishNotAllowed,
    Review,
    ReviewError,
    StepOutcome,
    StepRecord,
    Trace,
    UnknownOption,
)
from agent_sample.domain.plan import AgentPlan, plan_agentic
from agent_sample.domain.policy import Limits, consolidate, decide, summarize, validate
from agent_sample.domain.ports import (
    AgentReviewer,
    ProgressListener,
    PullRequestHost,
    ReaderFactory,
    Renderer,
    RevisionSource,
    WorkflowEngine,
)
from agent_sample.domain.tools import RunContext, Toolbox


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    ref: ChangeRef
    mode: Mode = "hybrid"
    focus: tuple[str, ...] = ()
    language: str | None = None
    post: bool = False


@dataclass(frozen=True, slots=True)
class ReviewContext:
    """As portas e escolhas de uma revisão, ligadas pela composição."""

    revisions: RevisionSource
    hosts: tuple[PullRequestHost, ...]
    readers: ReaderFactory
    agent: AgentReviewer
    capabilities: CapabilitySet
    renderer: Renderer
    limits: Limits = field(default_factory=Limits)
    checks: tuple[Check, ...] = CHECKS


@dataclass(frozen=True, slots=True)
class ReviewState:
    request: ReviewRequest
    raw: RawChange | None = None
    change: ChangeSet | None = None
    check_findings: tuple[Finding, ...] = ()
    plan: AgentPlan | None = None
    proposed: tuple[ProposedFinding, ...] = ()
    agent_findings: tuple[Finding, ...] = ()
    findings: tuple[Finding, ...] = ()
    decision: Decision | None = None
    summary: str = ""
    trace: Trace = Trace()
    review: Review | None = None
    output: str = ""

    def require_change(self) -> ChangeSet:
        if self.change is None:
            raise ReviewError("workflow step ran before the change was normalized")
        return self.change


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    name: str
    nature: Nature
    run: Callable[[ReviewState, ReviewContext], Awaitable[ReviewState]]


def _record(
    state: ReviewState,
    step: str,
    outcome: StepOutcome,
    detail: str,
    nature: Nature = "deterministic",
    **trace: object,
) -> ReviewState:
    steps = (*state.trace.steps, StepRecord(step, nature, outcome, detail))
    return replace(state, trace=replace(state.trace, steps=steps, **trace))


async def obtain(state: ReviewState, context: ReviewContext) -> ReviewState:
    ref = state.request.ref
    if state.request.post and not isinstance(ref, PullRequest):
        raise PublishNotAllowed("posting needs a pull request as the change source")
    if isinstance(ref, InlineDiff):
        raw = RawChange(ref.text, "inline diff", repository=ref.repository)
    elif isinstance(ref, RevisionRange):
        diff = await context.revisions.diff(ref.repository, ref.base, ref.head)
        source = f"{ref.base}...{ref.head}"
        raw = RawChange(diff, source, repository=ref.repository, revision=ref.head)
    else:
        host = _host(ref.locator, context.hosts)
        diff = await host.get_change(ref.locator)
        pr_context = await host.get_context(ref.locator)
        raw = RawChange(
            diff,
            f"{host.name} {ref.locator}",
            repository=ref.repository,
            pull_request=ref.locator,
            context=pr_context,
        )
    detail = f"source: {raw.source}"
    if raw.context is not None and raw.context.notices:
        detail += f"; notices: {'; '.join(raw.context.notices)}"
    return _record(replace(state, raw=raw), "obtain", "ok", detail)


def _host(locator: str, hosts: tuple[PullRequestHost, ...]) -> PullRequestHost:
    for host in hosts:
        if host.handles(locator):
            return host
    raise UnknownOption("pull request", locator, tuple(host.name for host in hosts) or ("none",))


async def normalize_change(state: ReviewState, context: ReviewContext) -> ReviewState:
    if state.raw is None:
        raise ReviewError("normalize ran before the change was obtained")
    change = normalize(parse_diff(state.raw.diff), context.limits.max_file_lines)
    languages = ", ".join(change.languages) or "no code"
    skipped = len(change.unreviewed)
    detail = f"{len(change.files)} file(s) to review ({languages}); {skipped} not reviewed"
    return _record(replace(state, change=change), "normalize", "ok", detail)


async def check(state: ReviewState, context: ReviewContext) -> ReviewState:
    if state.request.mode == "agent":
        return _record(state, "checks", "skipped", "mode agent: deterministic checks do not run")
    findings = run_checks(state.require_change(), context.checks)
    ids = ", ".join(item.id for item in context.checks)
    detail = f"{len(findings)} finding(s) from checks [{ids}]"
    return _record(replace(state, check_findings=findings), "checks", "ok", detail)


async def plan(state: ReviewState, context: ReviewContext) -> ReviewState:
    raw = state.raw
    decided = plan_agentic(
        state.request.mode,
        state.require_change(),
        context.capabilities,
        state.check_findings,
        state.request.focus,
        state.request.language,
        raw.context if raw else None,
        context.agent.unavailable(),
        context.limits,
    )
    outcome: StepOutcome = "degraded" if decided.degraded else "ok" if decided.run else "skipped"
    failures = (*state.trace.failures, decided.reason) if decided.degraded else state.trace.failures
    return _record(replace(state, plan=decided), "plan", outcome, decided.reason, failures=failures)


async def agentic_review(state: ReviewState, context: ReviewContext) -> ReviewState:
    """A única etapa agêntica. Falha ou estouro de limite vira registro, não erro da revisão."""
    decided = state.plan
    if decided is None or not decided.run:
        reason = decided.reason if decided else "not planned"
        return _record(state, "agentic_review", "skipped", reason, "agentic")
    raw = state.raw
    reader = context.readers.open(raw.repository, raw.revision) if raw and raw.repository else None
    toolbox = Toolbox(
        RunContext(reader, context.capabilities, raw.context if raw else None),
        context.limits.max_tool_output_chars,
    )
    proposed: list[ProposedFinding] = []
    reviewers: list[str] = []
    failures: list[str] = []
    for task in decided.tasks:
        try:
            outcome = await context.agent.review(task, toolbox, context.limits)
        except Exception as exc:  # noqa: BLE001 - a falha do agente é registrada, não propagada
            failures.append(f"{context.agent.name} {task.label}: {type(exc).__name__}: {exc}")
            continue
        proposed.extend(outcome.proposed)
        reviewers.extend(name for name in outcome.reviewers if name not in reviewers)
    ran = len(decided.tasks) - len(failures)
    outcome_name: StepOutcome = "ok" if not failures else "degraded" if ran else "failed"
    detail = f"{ran}/{len(decided.tasks)} part(s) reviewed; {len(proposed)} finding(s) proposed"
    if failures:
        detail += f"; failures: {'; '.join(failures)}"
    return _record(
        replace(state, proposed=tuple(proposed)),
        "agentic_review",
        outcome_name,
        detail,
        "agentic",
        reviewers=(*state.trace.reviewers, *reviewers),
        capabilities=tuple(plugin.trace_ref for plugin in context.capabilities.plugins),
        skills_loaded=toolbox.loaded_skills,
        tool_calls=tuple(toolbox.calls),
        failures=(*state.trace.failures, *failures),
    )


async def validate_findings(state: ReviewState, context: ReviewContext) -> ReviewState:
    del context
    if state.plan is None or not state.plan.run:
        return _record(state, "validate", "skipped", "no agentic findings to validate")
    accepted, discarded = validate(state.proposed, state.require_change())
    detail = f"{len(accepted)} accepted, {len(discarded)} discarded"
    return _record(
        replace(state, agent_findings=accepted),
        "validate",
        "ok",
        detail,
        discarded=(*state.trace.discarded, *discarded),
    )


async def consolidate_findings(state: ReviewState, context: ReviewContext) -> ReviewState:
    del context
    findings = consolidate(state.check_findings, state.agent_findings)
    merged = len(state.check_findings) + len(state.agent_findings) - len(findings)
    detail = f"{len(findings)} finding(s); {merged} duplicate(s) merged"
    return _record(replace(state, findings=findings), "consolidate", "ok", detail)


async def decide_review(state: ReviewState, context: ReviewContext) -> ReviewState:
    del context
    decision = decide(state.findings)
    summary = summarize(state.require_change(), state.findings, decision)
    return _record(replace(state, decision=decision, summary=summary), "decide", "ok", decision)


async def publish(state: ReviewState, context: ReviewContext) -> ReviewState:
    """Única etapa que escreve fora: só com pedido explícito e fonte PR."""
    if state.decision is None:
        raise ReviewError("publish ran before a decision was made")
    change = state.require_change()
    detail = f"format {context.renderer.name}"
    posted = ""
    if state.request.post:
        raw = state.raw
        locator = raw.pull_request if raw else None
        if locator is None:
            raise PublishNotAllowed("posting needs a pull request as the change source")
        draft = Review(
            state.decision, state.summary, state.findings, change.unreviewed, state.trace
        )
        posted = await _host(locator, context.hosts).publish(locator, draft)
        detail += f"; posted: {posted}"
    else:
        detail += "; not posted"
    state = _record(state, "publish", "ok", detail)
    review = Review(state.decision, state.summary, state.findings, change.unreviewed, state.trace)
    return replace(state, review=review, output=context.renderer.render(review))


STEPS: tuple[WorkflowStep, ...] = (
    WorkflowStep("obtain", "deterministic", obtain),
    WorkflowStep("normalize", "deterministic", normalize_change),
    WorkflowStep("checks", "deterministic", check),
    WorkflowStep("plan", "deterministic", plan),
    WorkflowStep("agentic_review", "agentic", agentic_review),
    WorkflowStep("validate", "deterministic", validate_findings),
    WorkflowStep("consolidate", "deterministic", consolidate_findings),
    WorkflowStep("decide", "deterministic", decide_review),
    WorkflowStep("publish", "deterministic", publish),
)


async def run_review(
    request: ReviewRequest,
    context: ReviewContext,
    engine: WorkflowEngine,
    on_step: ProgressListener | None = None,
) -> ReviewState:
    state = await engine.run(STEPS, ReviewState(request), context, on_step)
    if state.review is None:
        raise ReviewError(f"workflow engine {engine.name} ended without a review")
    return state
