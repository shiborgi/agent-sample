import asyncio
from collections.abc import Callable

import typer

from agent_sample.application.cli.present import (
    format_comparison,
    format_prompts,
    format_skills,
    format_verdict,
)
from agent_sample.application.compare import compare_subject
from agent_sample.application.service import ClassificationService, error_message
from agent_sample.domain.content import CLASSIFY_TASK
from agent_sample.domain.ports import ContentLibrary, SubjectClassifier

Implementations = Callable[[], tuple[SubjectClassifier, ...]]


def build_app(
    service: ClassificationService,
    implementations: Implementations,
    content: ContentLibrary,
) -> typer.Typer:
    app = typer.Typer(add_completion=False, no_args_is_help=True, pretty_exceptions_enable=False)
    prompts = typer.Typer(no_args_is_help=True, help="Lista e inspeciona prompts.")
    skills = typer.Typer(no_args_is_help=True, help="Lista e inspeciona skills.")
    content_app = typer.Typer(no_args_is_help=True, help="Publica versões de conteúdo.")
    app.add_typer(prompts, name="prompts")
    app.add_typer(skills, name="skills")
    app.add_typer(content_app, name="content")

    @app.command()
    def classify(
        message: str,
        strategy: str = typer.Option("", help="workflow | agent | hybrid | prediction"),
        engine: str = typer.Option("", help="motor do workflow: sequential | langgraph"),
        agent: str = typer.Option("", help="agente: langgraph | deepagents"),
        prompt_version: str = typer.Option("", help="versão do prompt (padrão: última publicada)"),
        skill: list[str] = typer.Option([], help="fixa a versão de uma skill: nome@versão"),
    ) -> None:
        """Classifica uma mensagem e mostra o caminho até o veredito."""
        options = service.defaults.merge(
            strategy=strategy,
            engine=engine,
            agent=agent,
            prompt_version=prompt_version,
            skills=tuple(skill),
        )
        _run(lambda: format_verdict(asyncio.run(service.classify(message, options))))

    @app.command()
    def compare(message: str) -> None:
        """Compara todas as implementações (motores, agentes e predição) na mesma mensagem."""
        _run(lambda: format_comparison(asyncio.run(compare_subject(message, implementations()))))

    @app.command("compare-prompts")
    def compare_prompts(
        message: str,
        version: list[str] = typer.Option([], help="versões a comparar (padrão: todas)"),
        agent: str = typer.Option("", help="agente: langgraph | deepagents"),
    ) -> None:
        """Compara versões de prompt lado a lado com o mesmo agente."""

        def action() -> str:
            versions = version or [
                item.version for item in content.prompts() if item.name == CLASSIFY_TASK.prompt
            ]
            classifiers = tuple(
                service.build(
                    service.defaults.merge(strategy="agent", agent=agent, prompt_version=value)
                )
                for value in versions
            )
            rows = asyncio.run(compare_subject(message, classifiers))
            return format_comparison(rows)

        _run(action)

    @prompts.command("list")
    def list_prompts() -> None:
        _run(lambda: format_prompts(content.prompts()))

    @prompts.command("show")
    def show_prompt(name: str, version: str = typer.Option("", help="padrão: última")) -> None:
        _run(lambda: content.prompt(name, version or None).template)

    @skills.command("list")
    def list_skills() -> None:
        _run(lambda: format_skills(content.skills()))

    @skills.command("show")
    def show_skill(name: str, version: str = typer.Option("", help="padrão: última")) -> None:
        _run(lambda: content.skill(name, version or None).body)

    @content_app.command("publish")
    def publish(kind: str, name: str, version: str) -> None:
        """Congela uma versão (prompt ou skill); depois disso ela não pode mudar."""
        _run(
            lambda: (
                f"published {kind} {name}@{version} sha256={content.publish(kind, name, version)}"
            )
        )

    return app


def _run(action: Callable[[], str]) -> None:
    try:
        output = action()
    except Exception as exc:
        typer.echo(error_message(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(output)


def run(
    service: ClassificationService,
    implementations: Implementations,
    content: ContentLibrary,
) -> None:
    build_app(service, implementations, content)()
