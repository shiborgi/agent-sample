from dataclasses import dataclass


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


@dataclass(frozen=True, slots=True)
class AgentRequest:
    """O que um agente recebe: a mensagem e o conteúdo versionado que o guia."""

    text: str
    prompt: PromptVersion
    skills: tuple[SkillVersion, ...]


@dataclass(frozen=True, slots=True)
class AgentAnswer:
    """A resposta final do agente, já fora do formato do modelo."""

    subject_id: str
    rationale: str
