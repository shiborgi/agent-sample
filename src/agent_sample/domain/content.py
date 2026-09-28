from dataclasses import dataclass
from string import Template

from agent_sample.domain.model import SUBJECTS

PLACEHOLDERS = frozenset({"subjects", "skills"})


@dataclass(frozen=True, slots=True)
class PromptVersion:
    name: str
    version: str
    template: str
    published: bool

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass(frozen=True, slots=True)
class SkillVersion:
    name: str
    version: str
    description: str
    body: str
    published: bool

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass(frozen=True, slots=True)
class AgentTask:
    """Capacidades de conteúdo que uma tarefa agêntica pede, sem fixar versões."""

    prompt: str
    skills: tuple[str, ...]


CLASSIFY_TASK = AgentTask("classify_subject", ("subject-boundaries", "out-of-scope"))


def unknown_placeholders(template: str) -> set[str]:
    parsed = Template(template)
    if not parsed.is_valid():
        return {"<invalid $ placeholder>"}
    return set(parsed.get_identifiers()) - PLACEHOLDERS


def render_prompt(prompt: PromptVersion, skills: tuple[SkillVersion, ...]) -> str:
    """Monta o prompt de sistema. Skills entram só como índice; o corpo vem via load_skill."""
    subjects = "\n".join(f"- {subject.id}: {subject.description}" for subject in SUBJECTS)
    index = "\n".join(f"- {skill.name}: {skill.description}" for skill in skills) or "- (nenhuma)"
    return Template(prompt.template).substitute(subjects=subjects, skills=index)
