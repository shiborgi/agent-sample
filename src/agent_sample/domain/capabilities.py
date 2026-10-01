"""Skills, revisores e plugins como capacidades com nome, descrição e versão.

O domínio não sabe onde nem em que formato o conteúdo mora; recebe tudo já validado.
"""

from dataclasses import dataclass

# Skill cujo corpo é o prompt do revisor principal. Precisa existir em algum plugin habilitado.
LEAD_SKILL = "lead-reviewer"


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    plugin: str
    version: str
    description: str
    body: str
    digest: str

    @property
    def ref(self) -> str:
        return f"{self.plugin}:{self.name}@{self.version}"


@dataclass(frozen=True, slots=True)
class Reviewer:
    """Revisor especializado (subagente): quando acionar, instruções, skills e ferramentas."""

    name: str
    plugin: str
    description: str
    instructions: str
    skills: tuple[str, ...]
    tools: tuple[str, ...]
    languages: tuple[str, ...] = ()
    focus: tuple[str, ...] = ()

    @property
    def ref(self) -> str:
        return f"{self.plugin}:{self.name}"

    def applies_to(self, languages: tuple[str, ...], focus: tuple[str, ...]) -> bool:
        """Sem filtros, sempre se aplica; com filtros, precisa casar linguagem ou foco."""
        if not self.languages and not self.focus:
            return True
        return bool(set(self.languages) & set(languages) or set(self.focus) & set(focus))


@dataclass(frozen=True, slots=True)
class Plugin:
    name: str
    version: str
    description: str
    author: str
    source: str
    digest: str
    skills: tuple[Skill, ...]
    reviewers: tuple[Reviewer, ...]
    warnings: tuple[str, ...] = ()

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def trace_ref(self) -> str:
        return f"{self.ref} source={self.source} sha256={self.digest[:12]}"


@dataclass(frozen=True, slots=True)
class Conflict:
    """Mesmo nome em mais de uma fonte: a de maior precedência vence, e isso fica visível."""

    kind: str
    name: str
    winner: str
    shadowed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CapabilitySet:
    """As capacidades escolhidas para uma revisão: plugins em versões fixas."""

    plugins: tuple[Plugin, ...]

    @property
    def skills(self) -> tuple[Skill, ...]:
        return tuple(skill for plugin in self.plugins for skill in plugin.skills)

    @property
    def all_reviewers(self) -> tuple[Reviewer, ...]:
        return tuple(reviewer for plugin in self.plugins for reviewer in plugin.reviewers)

    @property
    def reviewers(self) -> tuple[Reviewer, ...]:
        """Um revisor por nome; o último plugin da lista tem precedência."""
        by_name = {reviewer.name: reviewer for reviewer in self.all_reviewers}
        return tuple(by_name.values())

    def skill(self, name: str) -> Skill | None:
        """Aceita `skill` ou `plugin:skill`; o último plugin da lista tem precedência."""
        plugin, _, bare = name.rpartition(":")
        for skill in reversed(self.skills):
            if skill.name == bare and (not plugin or skill.plugin == plugin):
                return skill
        return None
