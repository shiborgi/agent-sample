"""Ferramentas do agente revisor. Todas são somente leitura e confinadas ao repositório revisado.

Para adicionar uma, crie um `Tool(spec, run)` e registre em `REVIEW_TOOLS`: todos os agentes a
recebem. Se ela precisar de uma nova capacidade de leitura, amplie a porta `Repository`.
"""

import json
from typing import Any

from agent_sample.domain.content import SkillVersion
from agent_sample.domain.ports import ToolSpec
from agent_sample.domain.review.model import CATEGORIES, DECISION_RULE, SEVERITIES, RepositoryError
from agent_sample.domain.review.policy import MAX_READ_LINES, MAX_SEARCH_HITS, MAX_TOOL_OUTPUT_CHARS
from agent_sample.domain.review.ports import Repository
from agent_sample.domain.tools import LOAD_SKILL, RunContext, Tool


class ReviewContext(RunContext):
    """Execução do revisor: skills oferecidas e o repositório que ele pode ler (se houver)."""

    def __init__(self, skills: tuple[SkillVersion, ...], repository: Repository | None) -> None:
        super().__init__(skills)
        self.repository = repository


def _read_repo_file(context: ReviewContext, arguments: dict[str, Any]) -> str:
    path = str(arguments.get("path", ""))
    start = _positive(arguments.get("start_line"), 1)
    end = (
        None if start is None else _positive(arguments.get("end_line"), start + MAX_READ_LINES - 1)
    )
    if start is None or end is None or end < start:
        return (
            "erro: start_line e end_line devem ser inteiros positivos, com start_line <= end_line"
        )
    problem = _outside(path)
    if problem is not None:
        return f"erro: {problem}"
    if context.repository is None:
        return "erro: repositório indisponível nesta revisão; use só o diff"
    try:
        content = context.repository.read(path)
    except RepositoryError as exc:
        return f"erro: {exc}"
    lines = content.splitlines()[start - 1 : min(end, start + MAX_READ_LINES - 1)]
    numbered = "\n".join(f"{number}: {text}" for number, text in enumerate(lines, start))
    return _truncate(numbered or f"(sem linhas em {start}..{end})")


def _search_repo(context: ReviewContext, arguments: dict[str, Any]) -> str:
    text = str(arguments.get("text", ""))
    if len(text.strip()) < 2:
        return "erro: informe um texto de busca com pelo menos 2 caracteres"
    if context.repository is None:
        return "erro: repositório indisponível nesta revisão; use só o diff"
    hits = context.repository.search(text, MAX_SEARCH_HITS)
    if not hits:
        return "nenhuma ocorrência"
    return _truncate("\n".join(f"{hit.path}:{hit.line}: {hit.text}" for hit in hits))


def _list_criteria(context: ReviewContext, arguments: dict[str, Any]) -> str:
    del arguments
    payload = {
        "severities": list(SEVERITIES),
        "categories": list(CATEGORIES),
        "decision_rule": DECISION_RULE,
        "skills": [
            {"name": skill.name, "description": skill.description}
            for skill in context.skills.values()
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _outside(path: str) -> str | None:
    """Recusa, antes de tocar no repositório, caminhos que apontam para fora dele."""
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    if not path.strip():
        return "informe o caminho de um arquivo do repositório"
    if normalized.startswith(("/", "~")) or ":" in parts[0] or ".." in parts:
        return f"caminho fora do repositório: {path}"
    return None


def _positive(value: object, default: int) -> int | None:
    if value is None:
        return default
    try:
        number = int(str(value))
    except ValueError:
        return None
    return number if number >= 1 else None


def _truncate(text: str) -> str:
    if len(text) <= MAX_TOOL_OUTPUT_CHARS:
        return text
    return text[:MAX_TOOL_OUTPUT_CHARS] + "\n[... truncado]"


REVIEW_TOOLS: tuple[Tool[ReviewContext], ...] = (
    Tool(
        ToolSpec(
            name="read_repo_file",
            description=(
                "Lê um arquivo do repositório revisado (ou um trecho), com linhas numeradas. "
                f"Até {MAX_READ_LINES} linhas por chamada. Somente leitura."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "caminho relativo à raiz"},
                    "start_line": {"type": "integer", "description": "primeira linha (1)"},
                    "end_line": {"type": "integer", "description": "última linha"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        _read_repo_file,
    ),
    Tool(
        ToolSpec(
            name="search_repo",
            description="Busca um símbolo ou texto literal no repositório revisado.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "texto a procurar"}},
                "required": ["text"],
                "additionalProperties": False,
            },
        ),
        _search_repo,
    ),
    Tool(
        ToolSpec(
            name="list_criteria",
            description="Lista severidades, categorias, a regra de decisão e as skills de revisão.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        _list_criteria,
    ),
    LOAD_SKILL,
)
