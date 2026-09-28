from dataclasses import dataclass
from typing import Protocol

from agent_sample.domain.review.change import Change
from agent_sample.domain.review.model import Review


@dataclass(frozen=True, slots=True)
class SearchHit:
    path: str
    line: int
    text: str


class Repository(Protocol):
    """Leitura somente do repositório revisado. Caminhos são relativos à raiz dele.

    Implementações recusam, com `RepositoryError`, qualquer caminho que saia da raiz.
    """

    def read(self, path: str) -> str: ...

    def search(self, text: str, limit: int) -> tuple[SearchHit, ...]: ...


class DiffSource(Protocol):
    """Gera o diff unificado entre duas referências de um repositório."""

    def between(self, base: str, head: str) -> str: ...


class ChangeReviewer(Protocol):
    name: str

    async def review(self, change: Change) -> Review: ...
