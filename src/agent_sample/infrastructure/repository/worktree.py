"""Leitura de um diretório de trabalho, confinada à raiz (bloqueia `..`, absolutos e symlinks)."""

import asyncio
from pathlib import Path

from agent_sample.domain.model import ReviewError
from agent_sample.domain.ports import RepositoryReader
from agent_sample.domain.tools import OutsideRepository
from agent_sample.infrastructure.repository.git import (
    MAX_MATCHES,
    GitRevisionReader,
    git,
    number_lines,
)

SKIPPED_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__"})


class WorktreeReader:
    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        if not self._root.is_dir():
            raise ReviewError(f"repository not found: {root}")

    def _resolve(self, path: str) -> Path:
        target = (self._root / path).resolve()
        if not target.is_relative_to(self._root):
            raise OutsideRepository(path)
        return target

    async def read(self, path: str, start: int | None, end: int | None) -> str:
        target = self._resolve(path)
        if not target.is_file():
            raise ReviewError(f"file not found: {path}")
        text = await asyncio.to_thread(target.read_text, errors="replace")
        return number_lines(text, start, end)

    async def search(self, query: str) -> tuple[str, ...]:
        return await asyncio.to_thread(self._search, query)

    def _search(self, query: str) -> tuple[str, ...]:
        if git(str(self._root), "rev-parse", "--git-dir").returncode == 0:
            return self._git_search(query)
        return self._walk_search(query)

    def _git_search(self, query: str) -> tuple[str, ...]:
        """`git grep` nos arquivos rastreados: rápido e nunca sai do repositório."""
        result = git(str(self._root), "grep", "-n", "-I", "-F", "-e", query, "--", ".")
        if result.returncode == 1:
            return ()
        if result.returncode != 0:
            detail = (result.stderr.strip().splitlines() or ["git grep failed"])[-1]
            raise ReviewError(f"git grep: {detail}")
        return tuple(result.stdout.splitlines()[:MAX_MATCHES])

    def _walk_search(self, query: str) -> tuple[str, ...]:
        matches: list[str] = []
        for path in sorted(self._root.rglob("*")):
            if any(part in SKIPPED_DIRS for part in path.relative_to(self._root).parts):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            try:
                lines = path.read_text().splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            relative = path.relative_to(self._root).as_posix()
            for number, line in enumerate(lines, 1):
                if query in line:
                    matches.append(f"{relative}:{number}:{line.strip()}")
                    if len(matches) >= MAX_MATCHES:
                        return tuple(matches)
        return tuple(matches)

    async def list(self, directory: str) -> tuple[str, ...]:
        target = self._resolve(directory)
        if not target.is_dir():
            raise ReviewError(f"directory not found: {directory or '.'}")
        return tuple(
            f"{item.name}/" if item.is_dir() else item.name
            for item in sorted(target.iterdir())
            if item.name not in SKIPPED_DIRS
        )

    async def blame(self, path: str, start: int, end: int) -> str:
        target = self._resolve(path)
        relative = target.relative_to(self._root).as_posix()
        return await GitRevisionReader(str(self._root), "HEAD").blame(relative, start, end)


class RepositoryReaders:
    """Revisão fixa → leitura pelo git; sem revisão → diretório de trabalho confinado."""

    def open(self, repository: str, revision: str | None) -> RepositoryReader:
        if revision is not None:
            if git(repository, "rev-parse", "--git-dir").returncode:
                raise ReviewError(f"{repository} is not a git repository")
            return GitRevisionReader(repository, revision)
        return WorktreeReader(repository)
