"""A revisão como comentários de PR: corpo da revisão e um comentário por achado."""

from agent_sample.domain.model import Finding, Review

ICONS = {"critical": "🛑", "major": "⚠️", "minor": "💡", "nit": "✏️"}


def review_body(review: Review) -> str:
    lines = [f"**Code review: `{review.decision}`**", "", review.summary]
    if review.unreviewed:
        lines += ["", "Not reviewed:"]
        lines += [f"- `{item.file}`: {item.reason}" for item in review.unreviewed]
    return "\n".join(lines)


def comment_body(finding: Finding) -> str:
    return "\n".join(
        [
            f"{ICONS[finding.severity]} **{finding.severity}** · {finding.category} — "
            f"{finding.description}",
            "",
            f"Suggestion: {finding.suggestion}",
            "",
            "```",
            finding.evidence,
            "```",
            f"<sub>{finding.origin.label}</sub>",
        ]
    )


class PullRequestCommentsRenderer:
    name = "pr-comments"

    def render(self, review: Review) -> str:
        parts = [review_body(review)]
        for finding in review.findings:
            parts.append(f"---\n`{finding.location}`\n\n{comment_body(finding)}")
        return "\n\n".join(parts)
