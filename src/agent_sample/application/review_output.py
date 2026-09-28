"""Formatos de saída da revisão. Para adicionar um: `Review -> str` registrado em FORMATS."""

import json
from collections.abc import Callable
from typing import Any

from agent_sample.application.cli.present import format_step
from agent_sample.application.review import ReviewRow
from agent_sample.domain.review.model import Review


def review_text(review: Review) -> str:
    lines = [f"{review.decision}\t{review.reviewed_by}", f"Resumo: {review.summary}"]
    if review.findings:
        lines.append("Achados:")
    for index, finding in enumerate(review.findings, 1):
        where = f"{finding.path}:{finding.start}"
        if finding.end != finding.start:
            where += f"-{finding.end}"
        lines.append(
            f"  {index}. [{finding.severity}/{finding.category}] {where} ({finding.source})"
        )
        lines.append(f"     {finding.description}")
        if finding.suggestion:
            lines.append(f"     sugestão: {finding.suggestion}")
        lines.extend(f"     > {line}" for line in finding.evidence.splitlines())
    if review.unreviewed:
        lines.append("Não revisados:")
        lines.extend(f"  - {item.path}: {item.reason}" for item in review.unreviewed)
    lines.append("Caminho:")
    lines.extend(f"  {index}. {format_step(step)}" for index, step in enumerate(review.trace, 1))
    return "\n".join(lines)


def review_json(review: Review) -> str:
    return json.dumps(review_payload(review), ensure_ascii=False, indent=2)


def review_payload(review: Review) -> dict[str, Any]:
    return {
        "decision": review.decision,
        "summary": review.summary,
        "reviewed_by": review.reviewed_by,
        "findings": [
            {
                "path": finding.path,
                "start_line": finding.start,
                "end_line": finding.end,
                "severity": finding.severity,
                "category": finding.category,
                "description": finding.description,
                "suggestion": finding.suggestion,
                "origin": finding.origin,
                "source": finding.source,
                "evidence": finding.evidence,
            }
            for finding in review.findings
        ],
        "unreviewed": [{"path": item.path, "reason": item.reason} for item in review.unreviewed],
        "trace": [
            {
                "kind": step.kind,
                "name": step.name,
                "outcome": step.outcome,
                "detail": step.detail,
                "prompt": step.prompt,
                "skills": list(step.skills),
            }
            for step in review.trace
        ],
    }


FORMATS: dict[str, Callable[[Review], str]] = {
    "text": review_text,
    "json": review_json,
}


def format_review_comparison(rows: tuple[ReviewRow, ...]) -> str:
    lines = ["variant\tdecision\tfindings\tsummary"]
    for row in rows:
        if row.review is None:
            lines.append(f"{row.name}\terror\t-\t{row.error}")
            continue
        review = row.review
        lines.append(f"{row.name}\t{review.decision}\t{len(review.findings)}\t{review.summary}")
        lines.extend(f"  {format_step(step)}" for step in review.trace if step.prompt)
    return "\n".join(lines)
