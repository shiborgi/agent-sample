from agent_sample.domain.model import Review


class TextRenderer:
    """Revisão legível no terminal, com o caminho percorrido."""

    name = "text"

    def render(self, review: Review) -> str:
        lines = [f"decision: {review.decision}", f"summary: {review.summary}"]
        if review.findings:
            lines.append("findings:")
        for finding in review.findings:
            lines.append(
                f"  [{finding.severity}/{finding.category}] {finding.location} — "
                f"{finding.description}"
            )
            lines.append(f"      suggestion: {finding.suggestion}")
            lines.append(f"      origin: {finding.origin.label}")
            evidence = finding.evidence.replace("\n", "\n                ")
            lines.append(f"      evidence: {evidence}")
        if review.unreviewed:
            lines.append("not reviewed:")
            lines.extend(f"  {item.file} — {item.reason}" for item in review.unreviewed)
        trace = review.trace
        lines.append("path:")
        lines.extend(
            f"  {index}. {step.name} [{step.nature}] {step.outcome} — {step.detail}"
            for index, step in enumerate(trace.steps, 1)
        )
        for label, values in (
            ("reviewers", trace.reviewers),
            ("capabilities", trace.capabilities),
            ("skills loaded", trace.skills_loaded),
            ("failures", trace.failures),
        ):
            if values:
                lines.append(f"{label}: {'; '.join(values)}")
        if trace.tool_calls:
            lines.append("tool calls:")
            lines.extend(
                f"  {call.tool}({call.arguments}) -> {call.outcome}" for call in trace.tool_calls
            )
        if trace.discarded:
            lines.append("discarded:")
            lines.extend(
                f"  {item.reviewer} {item.location} — {item.reason}: {item.description}"
                for item in trace.discarded
            )
        return "\n".join(lines)
