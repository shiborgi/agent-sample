"""Checagens determinísticas: explícitas, reproduzíveis e sem modelo.

Para adicionar uma, escreva `(change, files) -> tuple[Finding, ...]` e registre em `CHECKS`: o
workflow ganha uma etapa com o nome dela e todos os motores passam a executá-la.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from agent_sample.domain.review.change import Change, is_source, is_test
from agent_sample.domain.review.diff import DiffLine, FileChange
from agent_sample.domain.review.model import Category, Finding, Severity
from agent_sample.domain.review.secrets import mask_secrets, secret_kind


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    run: Callable[[Change, tuple[FileChange, ...]], tuple[Finding, ...]]


def rule_finding(
    check: str,
    file: FileChange,
    start: int,
    end: int,
    severity: Severity,
    category: Category,
    description: str,
    suggestion: str,
) -> Finding:
    """Achado de regra. Descrição e evidência passam pela máscara de segredos."""
    return Finding(
        path=file.path,
        start=start,
        end=end,
        severity=severity,
        category=category,
        description=mask_secrets(description),
        suggestion=suggestion,
        origin="rule",
        source=f"rule:{check}",
        evidence=mask_secrets(file.evidence(start, end)),
    )


# --- credenciais -------------------------------------------------------------------------------


def _secrets(change: Change, files: tuple[FileChange, ...]) -> tuple[Finding, ...]:
    del change
    findings: list[Finding] = []
    for file in files:
        for line in file.added:
            kind = secret_kind(line.text)
            if kind is None:
                continue
            findings.append(
                rule_finding(
                    "secrets",
                    file,
                    _number(line),
                    _number(line),
                    "critical",
                    "security",
                    f"Possível credencial no código ({kind}).",
                    "Remova do código e do histórico, revogue a credencial e leia de variável de "
                    "ambiente ou cofre de segredos.",
                )
            )
    return tuple(findings)


# --- resquícios de depuração -------------------------------------------------------------------

DEBUG_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "python": (
        re.compile(r"^\s*print\("),
        re.compile(r"\bbreakpoint\(\)"),
        re.compile(r"\bi?pdb\.set_trace\("),
        re.compile(r"^\s*import i?pdb\b"),
    ),
    "javascript": (
        re.compile(r"\bconsole\.(?:log|debug|trace)\("),
        re.compile(r"^\s*debugger\s*;?\s*$"),
    ),
    "typescript": (
        re.compile(r"\bconsole\.(?:log|debug|trace)\("),
        re.compile(r"^\s*debugger\s*;?\s*$"),
    ),
    "ruby": (re.compile(r"\bbinding\.pry\b"), re.compile(r"^\s*byebug\b")),
}
COMMENT_PREFIX: dict[str, str] = {"python": "#", "ruby": "#", "shell": "#"}
CODE_LIKE = re.compile(
    r"[;{}]\s*$|\)\s*:?\s*$|^\s*(?:def|class|return|import|from|if|for|while|const|let|var|"
    r"function)\b|\s=\s"
)
MIN_COMMENTED_BLOCK = 3


def _debug_leftovers(change: Change, files: tuple[FileChange, ...]) -> tuple[Finding, ...]:
    del change
    findings: list[Finding] = []
    for file in files:
        patterns = DEBUG_PATTERNS.get(file.language or "", ())
        for line in file.added:
            if any(pattern.search(line.text) for pattern in patterns):
                findings.append(
                    rule_finding(
                        "debug-leftovers",
                        file,
                        _number(line),
                        _number(line),
                        "minor",
                        "maintainability",
                        f"Resquício de depuração: {line.text.strip()}",
                        "Remova antes do merge ou troque por logging com nível adequado.",
                    )
                )
        for start, end in _commented_blocks(file):
            findings.append(
                rule_finding(
                    "debug-leftovers",
                    file,
                    start,
                    end,
                    "minor",
                    "maintainability",
                    f"Bloco de código comentado ({end - start + 1} linhas).",
                    "Apague o código morto; o histórico do git guarda a versão anterior.",
                )
            )
    return tuple(findings)


def _commented_blocks(file: FileChange) -> list[tuple[int, int]]:
    """Linhas adicionadas consecutivas que são comentário com cara de código."""
    prefix = COMMENT_PREFIX.get(file.language or "", "//")
    runs: list[list[int]] = []
    for line in file.added:
        stripped = line.text.strip()
        if not (stripped.startswith(prefix) and CODE_LIKE.search(stripped[len(prefix) :])):
            continue
        number = _number(line)
        if runs and runs[-1][-1] == number - 1:
            runs[-1].append(number)
        else:
            runs.append([number])
    return [(run[0], run[-1]) for run in runs if len(run) >= MIN_COMMENTED_BLOCK]


# --- testes ------------------------------------------------------------------------------------


def _missing_tests(change: Change, files: tuple[FileChange, ...]) -> tuple[Finding, ...]:
    """Código-fonte alterado sem nenhuma alteração de teste no mesmo diff."""
    if any(is_test(file.path) for file in change.files):
        return ()
    sources = [file for file in files if is_source(file) and file.added]
    if not sources:
        return ()
    first = sources[0]
    line = _number(first.added[0])
    others = ", ".join(file.path for file in sources[1:])
    description = "Código-fonte alterado sem nenhuma alteração de teste correspondente"
    description += f" (também: {others})." if others else "."
    return (
        rule_finding(
            "missing-tests",
            first,
            line,
            line,
            "minor",
            "tests",
            description,
            "Adicione ou atualize testes que exercitem o comportamento alterado.",
        ),
    )


# --- marcadores pendentes ----------------------------------------------------------------------

PENDING = re.compile(r"\b(TODO|FIXME)\b")


def _pending_markers(change: Change, files: tuple[FileChange, ...]) -> tuple[Finding, ...]:
    del change
    return tuple(
        rule_finding(
            "pending-markers",
            file,
            _number(line),
            _number(line),
            "nit",
            "maintainability",
            f"Marcador pendente adicionado: {line.text.strip()}",
            "Resolva antes do merge ou registre em uma issue e referencie-a.",
        )
        for file in files
        for line in file.added
        if PENDING.search(line.text)
    )


def _number(line: DiffLine) -> int:
    if line.new_line is None:
        raise ValueError("removed lines have no number in the new code")
    return line.new_line


CHECKS: tuple[Check, ...] = (
    Check("secrets", _secrets),
    Check("debug-leftovers", _debug_leftovers),
    Check("missing-tests", _missing_tests),
    Check("pending-markers", _pending_markers),
)
