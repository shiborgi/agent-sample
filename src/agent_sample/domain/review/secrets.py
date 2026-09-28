"""Detecção de credenciais no texto e máscara para que a saída da revisão nunca as repita."""

import re

from agent_sample.domain.review.diff import FileChange

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("chave de acesso AWS", re.compile(r"\b((?:AKIA|ASIA)[0-9A-Z]{16})\b")),
    ("token do GitHub", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,})\b")),
    ("token do Slack", re.compile(r"\b(xox[abprs]-[A-Za-z0-9-]{10,})\b")),
    ("chave de API", re.compile(r"\b(sk-[A-Za-z0-9_-]{20,})")),
    ("chave da Stripe", re.compile(r"\b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,})")),
    (
        "token JWT",
        re.compile(r"\b(eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,})"),
    ),
    ("chave privada", re.compile(r"(-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----)")),
    (
        "segredo atribuído no código",
        re.compile(
            r"(?i)[\w-]*(?:api[_-]?key|secret|token|passw(?:or)?d|pwd)[\w-]*[\"']?\s*[:=]\s*"
            r"[\"']([^\"'\s]{8,})[\"']"
        ),
    ),
)
PLACEHOLDER = re.compile(
    r"(?i)example|changeme|placeholder|dummy|x{4,}|\*{4,}|^<.*>$|^\$\{|^your[-_]|[-_]here$"
)


def secret_kind(text: str) -> str | None:
    """O tipo do primeiro segredo da linha. Placeholders óbvios não contam."""
    found = _secrets(text)
    return found[0][0] if found else None


def secret_values(text: str) -> tuple[str, ...]:
    return tuple(value for _, value in _secrets(text))


def diff_secrets(files: tuple[FileChange, ...]) -> tuple[str, ...]:
    """Segredos das linhas adicionadas, para mascará-los em qualquer texto do agente."""
    return tuple(
        value for file in files for line in file.added for value in secret_values(line.text)
    )


def mask_secrets(text: str, known: tuple[str, ...] = ()) -> str:
    """Troca cada segredo (reconhecido no texto ou já conhecido) pelo começo dele e `****`."""
    for value in (*secret_values(text), *known):
        text = text.replace(value, f"{value[:4]}****")
    return text


def _secrets(text: str) -> list[tuple[str, str]]:
    return [
        (kind, matched.group(1))
        for kind, pattern in SECRET_PATTERNS
        for matched in pattern.finditer(text)
        if not PLACEHOLDER.search(matched.group(1))
    ]
