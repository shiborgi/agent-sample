from agent_sample.application.compare import ComparisonRow
from agent_sample.domain.model import Verdict


def format_verdict(verdict: Verdict) -> str:
    confidence = "n/a" if verdict.confidence is None else f"{verdict.confidence:.2f}"
    return f"{verdict.runtime}\t{verdict.subject_id}\t{confidence}\t{verdict.rationale}"


def format_comparison(rows: tuple[ComparisonRow, ...]) -> str:
    lines = ["runtime\tsubject\tconfidence\trationale"]
    for row in rows:
        if row.verdict is None:
            lines.append(f"{row.runtime}\terror\tn/a\t{row.error}")
        else:
            lines.append(format_verdict(row.verdict))
    return "\n".join(lines)
