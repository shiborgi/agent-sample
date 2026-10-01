"""Contrato das ferramentas do agente. Todas somente leitura e restritas à mudança revisada.

O domínio define nome, descrição, parâmetros e o que cada uma pode acessar; a infra executa as
leituras através de `RepositoryReader`. Uma ferramenta nova registrada em `TOOLS` vale para todos
os revisores que a referenciarem.
"""

import json
import posixpath
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from agent_sample.domain.capabilities import CapabilitySet
from agent_sample.domain.change import PullRequestContext
from agent_sample.domain.model import ReviewError, ToolCallRecord
from agent_sample.domain.ports import RepositoryReader, ToolSpec


class OutsideRepository(ReviewError, ValueError):
    def __init__(self, path: str) -> None:
        super().__init__(f"path is outside the reviewed repository: {path}")


def safe_path(path: str) -> str:
    """Caminho relativo e normalizado dentro do repositório; qualquer fuga é recusada."""
    raw = path.strip().replace("\\", "/")
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        raise OutsideRepository(path)
    normalized = posixpath.normpath(raw) if raw else "."
    if normalized == ".." or normalized.startswith("../"):
        raise OutsideRepository(path)
    return "" if normalized == "." else normalized


class RunContext:
    """Estado de uma execução: o que está disponível e o que foi usado."""

    def __init__(
        self,
        reader: RepositoryReader | None,
        capabilities: CapabilitySet,
        context: PullRequestContext | None,
    ) -> None:
        self.reader = reader
        self.capabilities = capabilities
        self.context = context
        self.loaded: list[str] = []


Runner = Callable[[RunContext, dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class Tool:
    spec: ToolSpec
    run: Runner
    needs: str | None = None  # "repository" | "pull_request" | None


def _reader(context: RunContext) -> RepositoryReader:
    if context.reader is None:
        raise ReviewError("no repository available for this review")
    return context.reader


def _int(arguments: dict[str, Any], key: str) -> int | None:
    value = arguments.get(key)
    if value is None or value == "":
        return None
    return int(value)


async def _read_file(context: RunContext, arguments: dict[str, Any]) -> str:
    path = safe_path(str(arguments.get("path", "")))
    if not path:
        raise ReviewError("path is required")
    return await _reader(context).read(
        path, _int(arguments, "start_line"), _int(arguments, "end_line")
    )


async def _search_code(context: RunContext, arguments: dict[str, Any]) -> str:
    query = str(arguments.get("query", "")).strip()
    if not query:
        raise ReviewError("query is required")
    return "\n".join(await _reader(context).search(query)) or "(no matches)"


async def _list_files(context: RunContext, arguments: dict[str, Any]) -> str:
    directory = safe_path(str(arguments.get("directory", "")))
    return "\n".join(await _reader(context).list(directory)) or "(empty)"


async def _blame(context: RunContext, arguments: dict[str, Any]) -> str:
    path = safe_path(str(arguments.get("path", "")))
    start = _int(arguments, "start_line") or 1
    end = _int(arguments, "end_line") or start
    return await _reader(context).blame(path, start, end)


async def _load_skill(context: RunContext, arguments: dict[str, Any]) -> str:
    name = str(arguments.get("name", ""))
    skill = context.capabilities.skill(name)
    if skill is None:
        available = ", ".join(f"{item.plugin}:{item.name}" for item in context.capabilities.skills)
        raise ReviewError(f"unknown skill: {name}. Available: {available}")
    if skill.ref not in context.loaded:
        context.loaded.append(skill.ref)
    return skill.body


async def _pr_context(context: RunContext, arguments: dict[str, Any]) -> str:
    del arguments
    if context.context is None:
        raise ReviewError("this review has no pull request context")
    return context.context.render()


def _schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


PATH = {"type": "string", "description": "path relative to the repository root"}
LINE = {"type": "integer", "description": "1-based line number"}

TOOLS: tuple[Tool, ...] = (
    Tool(
        ToolSpec(
            "read_repo_file",
            "Read a file of the reviewed revision, optionally only a line range.",
            _schema({"path": PATH, "start_line": LINE, "end_line": LINE}, ("path",)),
        ),
        _read_file,
        "repository",
    ),
    Tool(
        ToolSpec(
            "search_code",
            "Search the reviewed revision for a symbol or text; returns path:line:text.",
            _schema({"query": {"type": "string"}}, ("query",)),
        ),
        _search_code,
        "repository",
    ),
    Tool(
        ToolSpec(
            "list_repo_files",
            "List files and directories of a directory in the reviewed revision.",
            _schema({"directory": {**PATH, "description": "directory; empty for the root"}}),
        ),
        _list_files,
        "repository",
    ),
    Tool(
        ToolSpec(
            "blame",
            "Show who last changed a line range and in which commit.",
            _schema({"path": PATH, "start_line": LINE, "end_line": LINE}, ("path", "start_line")),
        ),
        _blame,
        "repository",
    ),
    Tool(
        ToolSpec(
            "load_skill",
            "Load the full instructions of a skill listed in the prompt.",
            _schema(
                {"name": {"type": "string", "description": "skill or plugin:skill"}}, ("name",)
            ),
        ),
        _load_skill,
    ),
    Tool(
        ToolSpec(
            "pr_context",
            "Pull request context: description, linked issues, CI status, previous comments.",
            _schema({}),
        ),
        _pr_context,
        "pull_request",
    ),
)
TOOL_NAMES: tuple[str, ...] = tuple(tool.spec.name for tool in TOOLS)


class Toolbox:
    """Ferramentas de uma execução no formato que os agentes consomem (`ToolCatalog`)."""

    def __init__(
        self,
        context: RunContext,
        max_output_chars: int,
        tools: tuple[Tool, ...] = TOOLS,
    ) -> None:
        self.context = context
        self._max_output = max_output_chars
        self._tools = {tool.spec.name: tool for tool in tools if self._available(tool)}
        self.calls: list[ToolCallRecord] = []

    def _available(self, tool: Tool) -> bool:
        if tool.needs == "repository":
            return self.context.reader is not None
        if tool.needs == "pull_request":
            return self.context.context is not None
        return True

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(tool.spec for tool in self._tools.values())

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(name)
        rendered = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
        try:
            output = await tool.run(self.context, arguments)
        except (ReviewError, LookupError, ValueError, TypeError) as exc:
            self.calls.append(ToolCallRecord(name, rendered, f"error: {exc}"))
            return f"error: {exc}"
        if len(output) > self._max_output:
            omitted = len(output) - self._max_output
            output = f"{output[: self._max_output]}\n[truncated: {omitted} more characters]"
            self.calls.append(ToolCallRecord(name, rendered, "ok (truncated)"))
        else:
            self.calls.append(ToolCallRecord(name, rendered, "ok"))
        return output

    @property
    def loaded_skills(self) -> tuple[str, ...]:
        return tuple(self.context.loaded)
