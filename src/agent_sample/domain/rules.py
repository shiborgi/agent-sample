import re
import unicodedata
from dataclasses import dataclass

# Termos já normalizados (sem acento, minúsculos). Um termo casa só com palavras inteiras;
# termos com espaço casam com a sequência exata de palavras.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "billing": (
        "cobrado",
        "cobrada",
        "cobrados",
        "cobranca",
        "cobrancas",
        "cobrar",
        "cobraram",
        "cobrou",
        "fatura",
        "faturas",
        "boleto",
        "boletos",
        "pagamento",
        "pagamentos",
        "paguei",
        "reembolso",
        "estorno",
        "nota fiscal",
    ),
    "technical": (
        "erro",
        "erros",
        "bug",
        "bugs",
        "api",
        "falha",
        "falhou",
        "travou",
        "travando",
        "indisponivel",
        "fora do ar",
        "login",
        "senha",
        "timeout",
        "500",
        "502",
        "503",
        "504",
    ),
    "sales": (
        "preco",
        "precos",
        "plano",
        "planos",
        "contrato",
        "contratar",
        "demonstracao",
        "demo",
        "upgrade",
        "orcamento",
        "desconto",
        "proposta",
        "licenca",
        "licencas",
    ),
}

Matches = tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    """Resultado das regras: um assunto quando há um vencedor claro, senão `None`."""

    subject_id: str | None
    matches: Matches

    @property
    def detail(self) -> str:
        found = [f"{subject} ({', '.join(terms)})" for subject, terms in self.matches if terms]
        if self.subject_id is not None:
            terms = dict(self.matches)[self.subject_id]
            return f"regras: {self.subject_id} ({', '.join(terms)})"
        if found:
            return f"regras empatadas: {'; '.join(found)}"
        return "regras sem evidência"


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return stripped.casefold()


def tokenize(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", normalize(text)))


def match(tokens: tuple[str, ...]) -> Matches:
    return tuple(
        (subject, tuple(term for term in terms if _contains(tokens, tuple(term.split()))))
        for subject, terms in KEYWORDS.items()
    )


def decide(matches: Matches) -> RuleOutcome:
    scores = {subject: len(terms) for subject, terms in matches}
    best = max(scores.values(), default=0)
    winners = [subject for subject, score in scores.items() if score == best]
    if best == 0 or len(winners) > 1:
        return RuleOutcome(None, matches)
    return RuleOutcome(winners[0], matches)


def _contains(tokens: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    size = len(phrase)
    return any(tokens[index : index + size] == phrase for index in range(len(tokens) - size + 1))
