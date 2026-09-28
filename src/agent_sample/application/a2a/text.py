from agent_sample.domain.model import Verdict
from agent_sample.domain.trace import Step


def artifact_text(verdict: Verdict) -> str:
    confidence = "n/a" if verdict.confidence is None else f"{verdict.confidence:.2f}"
    path = " -> ".join(_step(step) for step in verdict.trace)
    return (
        f"{verdict.subject_id} ({confidence}) {verdict.rationale}\n"
        f"decided_by: {verdict.decided_by}\n"
        f"path: {path}"
    )


def _step(step: Step) -> str:
    label = f"{step.kind}:{step.name}[{step.outcome}"
    if step.prompt is not None:
        label += f" prompt={step.prompt} skills={','.join(step.skills) or '-'}"
    return label + "]"
