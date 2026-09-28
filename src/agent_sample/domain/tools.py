import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_sample.domain.content import SkillVersion
from agent_sample.domain.model import SUBJECTS
from agent_sample.domain.ports import ToolSpec


class RunContext:
    """Estado de uma execução do agente: skills oferecidas e quais foram carregadas."""

    def __init__(self, skills: tuple[SkillVersion, ...]) -> None:
        self.skills = {skill.name: skill for skill in skills}
        self.loaded: list[str] = []


@dataclass(frozen=True, slots=True)
class Tool:
    spec: ToolSpec
    run: Callable[[RunContext, dict[str, Any]], str]


def _list_subjects(context: RunContext, arguments: dict[str, Any]) -> str:
    del context, arguments
    payload = [
        {"id": subject.id, "name": subject.name, "description": subject.description}
        for subject in SUBJECTS
    ]
    return json.dumps(payload, ensure_ascii=False)


def _load_skill(context: RunContext, arguments: dict[str, Any]) -> str:
    name = str(arguments.get("name", ""))
    skill = context.skills.get(name)
    if skill is None:
        return f"skill desconhecida: {name}. Disponíveis: {', '.join(context.skills)}"
    if skill.ref not in context.loaded:
        context.loaded.append(skill.ref)
    return skill.body


# Ferramentas oferecidas a todos os agentes. Adicionar uma aqui vale para todos os frameworks.
TOOLS: tuple[Tool, ...] = (
    Tool(
        ToolSpec(
            name="list_subjects",
            description="Lista os assuntos permitidos para classificar a mensagem.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        _list_subjects,
    ),
    Tool(
        ToolSpec(
            name="load_skill",
            description="Carrega as instruções completas de uma skill listada no prompt.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string", "description": "nome da skill"}},
                "required": ["name"],
                "additionalProperties": False,
            },
        ),
        _load_skill,
    ),
)


class Toolbox:
    """Ferramentas de uma execução, no formato que os agentes consomem (`ToolCatalog`)."""

    def __init__(self, skills: tuple[SkillVersion, ...], tools: tuple[Tool, ...] = TOOLS) -> None:
        self.context = RunContext(skills)
        self._tools = {tool.spec.name: tool for tool in tools}

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(tool.spec for tool in self._tools.values())

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(name)
        return tool.run(self.context, arguments)

    @property
    def loaded_skills(self) -> tuple[str, ...]:
        return tuple(self.context.loaded)
