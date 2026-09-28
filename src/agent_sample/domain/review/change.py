from dataclasses import dataclass, replace

from agent_sample.domain.errors import UnknownOption
from agent_sample.domain.review.diff import FileChange, parse_diff
from agent_sample.domain.review.model import CATEGORIES, Unreviewed
from agent_sample.domain.review.policy import MAX_FILE_LINES, MAX_PART_CHARS

EXTENSIONS: dict[str, str] = {
    "py": "python",
    "js": "javascript",
    "jsx": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "go": "go",
    "java": "java",
    "kt": "kotlin",
    "rb": "ruby",
    "rs": "rust",
    "c": "c",
    "h": "c",
    "cpp": "cpp",
    "cs": "csharp",
    "php": "php",
    "swift": "swift",
    "sh": "shell",
}
LANGUAGES: tuple[str, ...] = tuple(sorted(set(EXTENSIONS.values())))
TEST_DIRS = ("test", "tests", "__tests__", "spec")


@dataclass(frozen=True, slots=True)
class Change:
    """A mudança a revisar: arquivos do diff (com linguagem resolvida) e o foco pedido."""

    files: tuple[FileChange, ...]
    focus: tuple[str, ...] = ()
    language: str | None = None


def prepare_change(text: str, focus: tuple[str, ...] = (), language: str | None = None) -> Change:
    """Lê o diff e valida as opções. A linguagem informada vale para arquivos sem extensão."""
    for item in focus:
        if item not in CATEGORIES:
            raise UnknownOption("focus", item, CATEGORIES)
    if language is not None and language not in LANGUAGES:
        raise UnknownOption("language", language, LANGUAGES)
    files = tuple(
        replace(file, language=language_of(file.path, language)) for file in parse_diff(text)
    )
    return Change(files, focus, language)


def language_of(path: str, fallback: str | None = None) -> str | None:
    name = path.rsplit("/", 1)[-1]
    stem, dot, extension = name.rpartition(".")
    if not dot or not stem:
        return fallback
    return EXTENSIONS.get(extension.lower())


def is_test(path: str) -> bool:
    parts = path.lower().split("/")
    name = parts[-1]
    stem = name.rsplit(".", 1)[0]
    return (
        any(part in TEST_DIRS for part in parts[:-1])
        or stem.startswith("test_")
        or stem.endswith(("_test", ".test", ".spec", "_spec"))
    )


def is_source(file: FileChange) -> bool:
    return file.language is not None and not is_test(file.path)


def triage(files: tuple[FileChange, ...]) -> tuple[tuple[FileChange, ...], tuple[Unreviewed, ...]]:
    """Separa o que pode ser revisado; binários e arquivos grandes ficam registrados."""
    reviewable: list[FileChange] = []
    unreviewed: list[Unreviewed] = []
    for file in files:
        changed = len(file.added) + file.removed_count
        if file.binary:
            unreviewed.append(Unreviewed(file.path, "arquivo binário"))
        elif changed > MAX_FILE_LINES:
            unreviewed.append(
                Unreviewed(
                    file.path, f"grande: {changed} linhas alteradas (limite {MAX_FILE_LINES})"
                )
            )
        elif len(file.text) > MAX_PART_CHARS:
            unreviewed.append(
                Unreviewed(
                    file.path,
                    f"grande: {len(file.text)} caracteres de diff (limite {MAX_PART_CHARS})",
                )
            )
        else:
            reviewable.append(file)
    return tuple(reviewable), tuple(unreviewed)


def split_parts(
    files: tuple[FileChange, ...], budget: int = MAX_PART_CHARS
) -> tuple[tuple[FileChange, ...], ...]:
    """Agrupa arquivos inteiros em partes de até `budget` caracteres de diff, na ordem do diff."""
    parts: list[list[FileChange]] = []
    size = 0
    for file in files:
        if not parts or size + len(file.text) > budget:
            parts.append([])
            size = 0
        parts[-1].append(file)
        size += len(file.text)
    return tuple(tuple(part) for part in parts)
