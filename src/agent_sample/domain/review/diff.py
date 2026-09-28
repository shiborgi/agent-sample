"""Leitura de diff unificado (git ou `diff -u`) em arquivos, hunks e linhas numeradas."""

import re
from dataclasses import dataclass, field
from typing import Literal

from agent_sample.domain.review.model import EmptyDiff, InvalidDiff

LineKind = Literal["+", "-", " "]
Status = Literal["added", "modified", "deleted", "renamed"]

HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
GIT_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")
NULL_PATH = "/dev/null"


@dataclass(frozen=True, slots=True)
class DiffLine:
    kind: LineKind
    text: str
    new_line: int | None
    """Número da linha no código novo; `None` para linhas removidas."""


@dataclass(frozen=True, slots=True)
class Hunk:
    new_start: int
    lines: tuple[DiffLine, ...]


@dataclass(frozen=True, slots=True)
class FileChange:
    path: str
    old_path: str
    status: Status
    binary: bool
    hunks: tuple[Hunk, ...]
    text: str
    """O trecho do diff deste arquivo, como veio."""
    language: str | None = None

    @property
    def lines(self) -> tuple[DiffLine, ...]:
        return tuple(line for hunk in self.hunks for line in hunk.lines)

    @property
    def added(self) -> tuple[DiffLine, ...]:
        return tuple(line for line in self.lines if line.kind == "+")

    @property
    def removed_count(self) -> int:
        return sum(1 for line in self.lines if line.kind == "-")

    @property
    def new_lines(self) -> frozenset[int]:
        """Linhas do código novo que aparecem no diff (adicionadas ou de contexto)."""
        return frozenset(line.new_line for line in self.lines if line.new_line is not None)

    def evidence(self, start: int, end: int) -> str:
        """As linhas do diff que sustentam um achado em `start..end` do código novo."""
        return "\n".join(
            f"{line.kind}{line.text}"
            for line in self.lines
            if line.new_line is not None and start <= line.new_line <= end
        )


@dataclass(slots=True)
class _Builder:
    old_path: str = ""
    new_path: str = ""
    status: Status = "modified"
    binary: bool = False
    hunks: list[Hunk] = field(default_factory=list)
    first: int = 0
    headed: bool = False

    @property
    def complete(self) -> bool:
        """Já tem cabeçalho, hunks ou marca de binário: um novo `---` é outro arquivo."""
        return self.headed or self.binary or bool(self.hunks)

    def build(self, raw: list[str], last: int) -> FileChange:
        path = self.old_path if self.status == "deleted" else self.new_path
        if not path:
            raise InvalidDiff(f"file without a path near line {self.first + 1}")
        return FileChange(
            path=path,
            old_path=self.old_path or path,
            status=self.status,
            binary=self.binary,
            hunks=tuple(self.hunks),
            text="\n".join(raw[self.first : last]),
        )


def parse_diff(text: str) -> tuple[FileChange, ...]:
    """Lê um diff unificado. Diff vazio ou sem nenhum arquivo reconhecível é erro."""
    if not text.strip():
        raise EmptyDiff()
    lines = text.splitlines()
    files: list[FileChange] = []
    current: _Builder | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("diff --git "):
            if current is not None:
                files.append(current.build(lines, index))
            current = _Builder(first=index)
            header = GIT_HEADER.match(line)
            if header:
                current.old_path, current.new_path = header.group(1), header.group(2)
        elif line.startswith("--- ") and _next(lines, index).startswith("+++ "):
            if current is None or current.complete:
                if current is not None:
                    files.append(current.build(lines, index))
                current = _Builder(first=index)
            _file_header(current, line[4:], lines[index + 1][4:])
            index += 1
        elif line.startswith("@@"):
            if current is None:
                raise InvalidDiff(f"hunk without a file header at line {index + 1}")
            hunk, index = _hunk(lines, index)
            current.hunks.append(hunk)
            current.binary = current.binary or any("\x00" in item.text for item in hunk.lines)
        elif current is not None:
            _metadata(current, line)
        index += 1
    if current is not None:
        files.append(current.build(lines, len(lines)))
    if not files:
        raise InvalidDiff("no file headers found")
    return tuple(files)


def _next(lines: list[str], index: int) -> str:
    return lines[index + 1] if index + 1 < len(lines) else ""


def _file_header(current: _Builder, old: str, new: str) -> None:
    current.headed = True
    old_path, new_path = _path(old, "a/"), _path(new, "b/")
    if old_path == NULL_PATH:
        current.status = "added"
    else:
        current.old_path = old_path
    if new_path == NULL_PATH:
        current.status = "deleted"
    else:
        current.new_path = new_path


def _path(raw: str, prefix: str) -> str:
    path = raw.split("\t", 1)[0].strip()
    return path[len(prefix) :] if path.startswith(prefix) else path


def _metadata(current: _Builder, line: str) -> None:
    if line.startswith("new file mode"):
        current.status = "added"
    elif line.startswith("deleted file mode"):
        current.status = "deleted"
    elif line.startswith("rename from "):
        current.status = "renamed"
        current.old_path = line.removeprefix("rename from ")
    elif line.startswith("rename to "):
        current.new_path = line.removeprefix("rename to ")
    elif line.startswith(("Binary files ", "GIT binary patch")):
        current.binary = True


def _hunk(lines: list[str], index: int) -> tuple[Hunk, int]:
    """Lê um hunk pelas contagens do cabeçalho; devolve o índice da última linha lida."""
    header = HUNK_HEADER.match(lines[index])
    if header is None:
        raise InvalidDiff(f"invalid hunk header at line {index + 1}: {lines[index]}")
    old_left = int(header.group(2) or "1")
    new_start = int(header.group(3))
    new_left = int(header.group(4) or "1")
    number = new_start
    body: list[DiffLine] = []
    while old_left > 0 or new_left > 0:
        index += 1
        if index >= len(lines):
            raise InvalidDiff(f"hunk ends early at line {index}")
        line = lines[index]
        if line.startswith("\\"):
            continue
        kind, content = (line[0], line[1:]) if line else (" ", "")
        if kind == "+" and new_left > 0:
            body.append(DiffLine("+", content, number))
            number += 1
            new_left -= 1
        elif kind == "-" and old_left > 0:
            body.append(DiffLine("-", content, None))
            old_left -= 1
        elif kind == " " and old_left > 0 and new_left > 0:
            body.append(DiffLine(" ", content, number))
            number += 1
            old_left -= 1
            new_left -= 1
        else:
            raise InvalidDiff(f"unexpected line in hunk at line {index + 1}: {line[:60]}")
    if _next(lines, index).startswith("\\"):
        index += 1
    return Hunk(new_start, tuple(body)), index
