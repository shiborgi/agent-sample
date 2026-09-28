from agent_sample.application.compare import ComparisonRow
from agent_sample.domain.content import PromptVersion, SkillVersion
from agent_sample.domain.model import Verdict
from agent_sample.domain.trace import Step


def format_verdict(verdict: Verdict) -> str:
    lines = ["\t".join(_fields(verdict))]
    lines.extend(f"  {index}. {format_step(step)}" for index, step in enumerate(verdict.trace, 1))
    return "\n".join(lines)


def format_step(step: Step) -> str:
    parts = [f"{step.kind}:{step.name}", step.outcome]
    if step.prompt is not None:
        parts.append(f"prompt={step.prompt}")
        parts.append(f"skills={','.join(step.skills) or '-'}")
    return f"{' '.join(parts)} — {step.detail}"


def format_comparison(rows: tuple[ComparisonRow, ...]) -> str:
    lines = ["implementation\tsubject\tdecided_by\tconfidence\trationale"]
    for row in rows:
        if row.verdict is None:
            lines.append(f"{row.name}\terror\t-\tn/a\t{row.error}")
            continue
        lines.append("\t".join((row.name, *_fields(row.verdict))))
        lines.extend(f"  {format_step(step)}" for step in row.verdict.trace if step.prompt)
    return "\n".join(lines)


def format_prompts(prompts: tuple[PromptVersion, ...]) -> str:
    lines = ["prompt\tversion\tstatus"]
    lines.extend(f"{item.name}\t{item.version}\t{_status(item.published)}" for item in prompts)
    return "\n".join(lines)


def format_skills(skills: tuple[SkillVersion, ...]) -> str:
    lines = ["skill\tversion\tstatus\tdescription"]
    lines.extend(
        f"{item.name}\t{item.version}\t{_status(item.published)}\t{item.description}"
        for item in skills
    )
    return "\n".join(lines)


def _fields(verdict: Verdict) -> tuple[str, str, str, str]:
    confidence = "n/a" if verdict.confidence is None else f"{verdict.confidence:.2f}"
    return verdict.subject_id, verdict.decided_by, confidence, verdict.rationale


def _status(published: bool) -> str:
    return "published" if published else "draft"
