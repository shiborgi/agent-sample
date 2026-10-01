"""De onde vem a mudança. As referências são opacas: quem as interpreta é a infra."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InlineDiff:
    """Diff unificado já em texto; `repository` opcional dá contexto às ferramentas."""

    text: str
    repository: str | None = None


@dataclass(frozen=True, slots=True)
class RevisionRange:
    """Duas referências de um repositório local."""

    repository: str
    base: str
    head: str


@dataclass(frozen=True, slots=True)
class PullRequest:
    """Um pull request remoto; `locator` é uma URL ou `dono/repo#número`."""

    locator: str
    repository: str | None = None


ChangeRef = InlineDiff | RevisionRange | PullRequest


@dataclass(frozen=True, slots=True)
class PullRequestContext:
    """Contexto remoto do PR, obtido deterministicamente na etapa 1."""

    title: str
    description: str
    linked_issues: tuple[str, ...] = ()
    ci_status: str = "unknown"
    comments: tuple[str, ...] = ()
    notices: tuple[str, ...] = ()

    def render(self) -> str:
        lines = [f"title: {self.title}", f"ci: {self.ci_status}", "description:", self.description]
        if self.linked_issues:
            lines.append("linked issues:")
            lines.extend(f"- {issue}" for issue in self.linked_issues)
        if self.comments:
            lines.append("previous comments:")
            lines.extend(f"- {comment}" for comment in self.comments)
        if self.notices:
            lines.append("notices:")
            lines.extend(f"- {notice}" for notice in self.notices)
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class RawChange:
    """A mudança obtida da fonte, ainda sem interpretar."""

    diff: str
    source: str
    repository: str | None = None
    revision: str | None = None
    pull_request: str | None = None
    context: PullRequestContext | None = None
