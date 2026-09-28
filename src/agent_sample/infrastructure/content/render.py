"""Transforma uma versão de prompt no texto de sistema que todos os agentes recebem."""

from string import Template

from agent_sample.domain.content import PromptVersion, SkillVersion
from agent_sample.domain.model import SUBJECTS

PLACEHOLDERS = frozenset({"subjects", "skills"})


def unknown_placeholders(template: str) -> set[str]:
    parsed = Template(template)
    if not parsed.is_valid():
        return {"<invalid $ placeholder>"}
    return set(parsed.get_identifiers()) - PLACEHOLDERS


def render_prompt(prompt: PromptVersion, skills: tuple[SkillVersion, ...]) -> str:
    """Skills entram só como índice; o corpo chega via load_skill quando o agente pede."""
    subjects = "\n".join(f"- {subject.id}: {subject.description}" for subject in SUBJECTS)
    index = "\n".join(f"- {skill.name}: {skill.description}" for skill in skills) or "- (nenhuma)"
    return Template(prompt.template).substitute(subjects=subjects, skills=index)
