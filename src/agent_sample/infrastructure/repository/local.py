import os
from pathlib import Path

from agent_sample.domain.review.model import RepositoryError
from agent_sample.domain.review.ports import SearchHit

SKIP_DIRS = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache"}
)
MAX_FILE_BYTES = 1_000_000


class LocalRepository:
    """Repositório no disco. Todo caminho é resolvido (inclusive symlinks) e precisa ficar dentro
    da raiz; o que sair dela é recusado. Nada aqui escreve ou executa."""

    def __init__(self, root: Path) -> None:
        if not root.is_dir():
            raise RepositoryError(f"repository not found: {root}")
        self._root = root.resolve()

    def read(self, path: str) -> str:
        target = (self._root / path).resolve()
        if not target.is_relative_to(self._root):
            raise RepositoryError(f"path outside the repository: {path}")
        if not target.is_file():
            raise RepositoryError(f"file not found: {path}")
        try:
            text = _text(target)
        except OSError as exc:
            raise RepositoryError(f"cannot read {path}: {exc.strerror}") from exc
        if text is None:
            raise RepositoryError(f"not a readable text file: {path}")
        return text

    def search(self, text: str, limit: int) -> tuple[SearchHit, ...]:
        """Busca literal, em ordem de caminho. Binários, grandes e ilegíveis ficam de fora."""
        hits: list[SearchHit] = []
        for path in self._files():
            try:
                content = _text(path)
            except OSError:
                continue
            if content is None:
                continue
            for number, line in enumerate(content.splitlines(), 1):
                if text in line:
                    relative = path.relative_to(self._root).as_posix()
                    hits.append(SearchHit(relative, number, line.strip()[:200]))
                    if len(hits) >= limit:
                        return tuple(hits)
        return tuple(hits)

    def _files(self) -> list[Path]:
        found: list[Path] = []
        for directory, dirnames, filenames in os.walk(self._root, followlinks=False):
            dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
            for name in sorted(filenames):
                path = Path(directory) / name
                if path.is_file() and path.resolve().is_relative_to(self._root):
                    found.append(path)
        return found


def _text(path: Path) -> str | None:
    """Conteúdo de um arquivo de texto de tamanho razoável; `None` para binário ou grande."""
    if path.stat().st_size > MAX_FILE_BYTES:
        return None
    data = path.read_bytes()
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")
