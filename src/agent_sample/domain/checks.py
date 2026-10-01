"""Checagens determinísticas: explícitas, reproduzíveis e sem modelo.

Para adicionar uma checagem, escreva uma função `ChangeSet -> tuple[Finding, ...]` e registre um
`Check` em `CHECKS`. Nenhuma outra etapa precisa mudar.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from agent_sample.domain.diff import ChangeSet, DiffLine, FileChange, is_test_path
from agent_sample.domain.model import Category, Finding, Origin, Severity


@dataclass(frozen=True, slots=True)
class Check:
    id: str
    description: str
    run: Callable[[ChangeSet], tuple[Finding, ...]]


SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("API secret key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("private key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
    (
        "hardcoded credential",
        re.compile(
            r"(?i)\b[\w-]*(?:api[_-]?key|secret|token|passw(?:or)?d|pwd|access[_-]?key)[\w-]*"
            r"\s*[:=]\s*[\"']([^\"'\s]{8,})[\"']"
        ),
    ),
)
PLACEHOLDERS = ("changeme", "example", "placeholder", "dummy", "your", "xxx", "<", "${", "{{")

JS_DEBUG: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("console output", re.compile(r"\bconsole\.(?:log|debug|trace)\(")),
    ("debugger statement", re.compile(r"^\s*debugger;?\s*$")),
)
DEBUG_PATTERNS: dict[str, tuple[tuple[str, re.Pattern[str]], ...]] = {
    "python": (
        ("debug print", re.compile(r"^\s*print\(")),
        (
            "breakpoint",
            re.compile(r"\bbreakpoint\(\)|\b(?:i?pdb)\.set_trace\(\)|^\s*import i?pdb\b"),
        ),
    ),
    "javascript": JS_DEBUG,
    "typescript": JS_DEBUG,
}
HASH_COMMENT_LANGUAGES = frozenset({"python", "ruby", "shell"})
CODE_LIKE = re.compile(r"(?:[=(){};]|\breturn\b|\bdef\b|\bimport\b|\bif\b.*:$)")
COMMENTED_BLOCK = 3
MARKER = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")


def _finding(
    check: str,
    file: FileChange,
    line: DiffLine,
    severity: Severity,
    category: Category,
    description: str,
    suggestion: str,
    end_line: int | None = None,
    evidence: str | None = None,
) -> Finding:
    number = line.new_line or 1
    return Finding(
        file=file.path,
        start_line=number,
        end_line=end_line or number,
        severity=severity,
        category=category,
        description=description,
        suggestion=suggestion,
        origin=Origin("check", check),
        evidence=evidence if evidence is not None else line.text.strip(),
    )


def find_secrets(change: ChangeSet) -> tuple[Finding, ...]:
    found: list[Finding] = []
    for file in change.files:
        for line in file.added:
            for label, pattern in SECRET_PATTERNS:
                matched = pattern.search(line.text)
                if matched is None or _placeholder(matched.group(matched.lastindex or 0)):
                    continue
                secret = matched.group(matched.lastindex or 0)
                found.append(
                    _finding(
                        "secrets",
                        file,
                        line,
                        "critical",
                        "security",
                        f"{label} committed in the code",
                        "Remove the value, rotate it, and load it from the environment or a "
                        "secret manager.",
                        evidence=line.text.strip().replace(secret, _mask(secret)),
                    )
                )
                break
    return tuple(found)


def find_debug_leftovers(change: ChangeSet) -> tuple[Finding, ...]:
    found: list[Finding] = []
    for file in change.files:
        patterns = () if file.is_test else DEBUG_PATTERNS.get(file.language, ())
        for line in file.added:
            for label, pattern in patterns:
                if pattern.search(line.text):
                    found.append(
                        _finding(
                            "debug-leftovers",
                            file,
                            line,
                            "minor",
                            "maintainability",
                            f"{label} left in the code",
                            "Remove it or use the project's logger.",
                        )
                    )
                    break
        found.extend(_commented_blocks(file))
    return tuple(found)


def _commented_blocks(file: FileChange) -> tuple[Finding, ...]:
    if not file.is_code:
        return ()
    prefix = "#" if file.language in HASH_COMMENT_LANGUAGES else "//"
    found: list[Finding] = []
    run: list[DiffLine] = []
    for hunk in file.hunks:
        for line in (*hunk.lines, None):
            commented = (
                line is not None
                and line.kind == "+"
                and line.text.strip().startswith(prefix)
                and bool(CODE_LIKE.search(line.text.strip()[len(prefix) :].strip()))
            )
            if commented and line is not None:
                run.append(line)
                continue
            if len(run) >= COMMENTED_BLOCK:
                found.append(
                    _finding(
                        "debug-leftovers",
                        file,
                        run[0],
                        "minor",
                        "maintainability",
                        f"block of {len(run)} commented-out code lines",
                        "Delete dead code; version control keeps the history.",
                        end_line=run[-1].new_line,
                        evidence="\n".join(item.text for item in run),
                    )
                )
            run = []
    return tuple(found)


def find_missing_tests(change: ChangeSet) -> tuple[Finding, ...]:
    touched_tests = any(file.is_test for file in change.files) or any(
        is_test_path(item.file) for item in change.unreviewed
    )
    sources = [file for file in change.files if file.is_code and not file.is_test]
    if touched_tests or not sources:
        return ()
    first = sources[0]
    names = ", ".join(file.path for file in sources)
    return (
        _finding(
            "missing-tests",
            first,
            first.added[0],
            "minor",
            "tests",
            f"source code changed without a matching test change: {names}",
            "Add or update tests that exercise the changed behavior.",
        ),
    )


def find_pending_markers(change: ChangeSet) -> tuple[Finding, ...]:
    found: list[Finding] = []
    for file in change.files:
        for line in file.added:
            matched = MARKER.search(line.text)
            if matched is None:
                continue
            found.append(
                _finding(
                    "pending-markers",
                    file,
                    line,
                    "nit",
                    "maintainability",
                    f"{matched.group(1)} marker added",
                    "Resolve it before merging or link it to a tracked issue.",
                )
            )
    return tuple(found)


def _mask(secret: str) -> str:
    """A revisão nunca repete o segredo que encontrou."""
    return f"{secret[:4]}…[redacted]"


def _placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDERS)


CHECKS: tuple[Check, ...] = (
    Check("secrets", "credentials or secrets in added code", find_secrets),
    Check("debug-leftovers", "prints, breakpoints and commented-out code", find_debug_leftovers),
    Check("missing-tests", "source changed without a test change", find_missing_tests),
    Check("pending-markers", "TODO/FIXME markers added", find_pending_markers),
)


def run_checks(change: ChangeSet, checks: tuple[Check, ...] = CHECKS) -> tuple[Finding, ...]:
    return tuple(finding for check in checks for finding in check.run(change))
