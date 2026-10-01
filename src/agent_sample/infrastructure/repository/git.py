"""Git local: diff entre duas referências e leitura somente da revisão revisada.

Ler por `git show <revisão>:<caminho>` garante que nada fora do repositório é alcançável: não há
caminho de sistema de arquivos envolvido.
"""

import asyncio
import subprocess
from pathlib import Path

from agent_sample.domain.model import ChangeNotFound, ReviewError
from agent_sample.domain.tools import OutsideRepository

MAX_MATCHES = 100


def git(repository: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repository, *args], capture_output=True, text=True, check=False
    )


def _checked(repository: str, *args: str) -> str:
    result = git(repository, *args)
    if result.returncode != 0:
        detail = (result.stderr.strip().splitlines() or ["git failed"])[-1]
        raise ReviewError(f"git {args[0]}: {detail}")
    return result.stdout


def _arg(path: str) -> str:
    if path.startswith("-"):
        raise OutsideRepository(path)
    return path


class GitRevisionSource:
    async def diff(self, repository: str, base: str, head: str) -> str:
        return await asyncio.to_thread(self._diff, repository, base, head)

    def _diff(self, repository: str, base: str, head: str) -> str:
        if not Path(repository).is_dir() or git(repository, "rev-parse", "--git-dir").returncode:
            raise ChangeNotFound(f"{repository} is not a git repository")
        for ref in (base, head):
            if git(
                repository, "rev-parse", "--verify", "--quiet", f"{_arg(ref)}^{{commit}}"
            ).returncode:
                raise ChangeNotFound(f"reference {ref!r} does not exist in {repository}")
        return _checked(
            repository, "diff", "--no-color", "--no-ext-diff", "--find-renames", f"{base}...{head}"
        )


class GitRevisionReader:
    """Lê uma revisão fixa. Só leitura: show, grep, ls-tree e blame."""

    def __init__(self, repository: str, revision: str) -> None:
        self._repository = repository
        self._revision = revision

    async def read(self, path: str, start: int | None, end: int | None) -> str:
        text = await asyncio.to_thread(
            _checked, self._repository, "show", f"{self._revision}:{_arg(path)}"
        )
        return number_lines(text, start, end)

    async def search(self, query: str) -> tuple[str, ...]:
        result = await asyncio.to_thread(
            git, self._repository, "grep", "-n", "-I", "-F", "-e", query, self._revision, "--"
        )
        prefix = f"{self._revision}:"
        lines = [line.removeprefix(prefix) for line in result.stdout.splitlines()]
        return tuple(lines[:MAX_MATCHES])

    async def list(self, directory: str) -> tuple[str, ...]:
        target = [f"{_arg(directory)}/"] if directory else []
        output = await asyncio.to_thread(
            _checked, self._repository, "ls-tree", "--name-only", self._revision, "--", *target
        )
        return tuple(output.splitlines())

    async def blame(self, path: str, start: int, end: int) -> str:
        return await asyncio.to_thread(
            _checked,
            self._repository,
            "blame",
            "--date=short",
            "-L",
            f"{start},{end}",
            self._revision,
            "--",
            _arg(path),
        )


def number_lines(text: str, start: int | None, end: int | None) -> str:
    lines = text.splitlines()
    first = max(start or 1, 1)
    last = min(end or len(lines), len(lines))
    return "\n".join(f"{index}: {lines[index - 1]}" for index in range(first, last + 1))
