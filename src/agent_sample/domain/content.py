from dataclasses import dataclass

from agent_sample.domain.policy import MAX_TOOL_ROUNDS


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
    tasks: tuple[str, ...] = ()
    """Tarefas às quais a skill se oferece (frontmatter `tasks:`), além das que a declaram."""

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass(frozen=True, slots=True)
class AgentTask:
    """Capacidades de conteúdo que uma tarefa agêntica pede, sem fixar versões.

    `skills` são as obrigatórias. Uma skill também pode se oferecer à tarefa marcando
    `tasks: <name>` no frontmatter, sem mudar código.
    """

    name: str
    prompt: str
    skills: tuple[str, ...] = ()


CLASSIFY_TASK = AgentTask(
    "classify_subject", "classify_subject", ("subject-boundaries", "out-of-scope")
)
REVIEW_TASK = AgentTask("review_change", "review_change")


@dataclass(frozen=True, slots=True)
class AgentRequest:
    """O que um agente recebe: a entrada da tarefa e o conteúdo versionado que o guia."""

    text: str
    prompt: PromptVersion
    skills: tuple[SkillVersion, ...]
    max_tool_rounds: int = MAX_TOOL_ROUNDS


@dataclass(frozen=True, slots=True)
class AgentAnswer:
    """A resposta final do agente classificador, já fora do formato do modelo."""

    subject_id: str
    rationale: str
