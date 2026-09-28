"""Transforma uma versão de prompt no texto de sistema que todos os agentes recebem."""

from collections.abc import Callable
from string import Template

from agent_sample.domain.content import PromptVersion, SkillVersion
from agent_sample.domain.model import SUBJECTS
from agent_sample.domain.review.model import CATEGORIES, DECISION_RULE, SEVERITIES

# Placeholders que qualquer prompt pode usar; o texto vem dos catálogos do domínio.
VARIABLES: dict[str, Callable[[], str]] = {
    "subjects": lambda: "\n".join(f"- {subject.id}: {subject.description}" for subject in SUBJECTS),
    "severities": lambda: "\n".join(f"- {severity}" for severity in SEVERITIES),
    "categories": lambda: "\n".join(f"- {category}" for category in CATEGORIES),
    "decision_rule": lambda: DECISION_RULE,
}
PLACEHOLDERS = frozenset({*VARIABLES, "skills"})


def unknown_placeholders(template: str) -> set[str]:
    parsed = Template(template)
    if not parsed.is_valid():
        return {"<invalid $ placeholder>"}
    return set(parsed.get_identifiers()) - PLACEHOLDERS


def render_prompt(prompt: PromptVersion, skills: tuple[SkillVersion, ...]) -> str:
    """Skills entram só como índice; o corpo chega via load_skill quando o agente pede."""
    index = "\n".join(f"- {skill.name}: {skill.description}" for skill in skills) or "- (nenhuma)"
    values = {name: build() for name, build in VARIABLES.items()}
    return Template(prompt.template).substitute(values, skills=index)
