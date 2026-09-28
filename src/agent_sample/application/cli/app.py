import asyncio
import sys
from collections.abc import Callable
from pathlib import Path

import typer

from agent_sample.application.cli.present import (
    format_comparison,
    format_prompts,
    format_skills,
    format_verdict,
)
from agent_sample.application.compare import compare_subject
from agent_sample.application.review import ReviewOptions, ReviewService
from agent_sample.application.review_output import FORMATS, format_review_comparison
from agent_sample.application.service import ClassificationService, error_message
from agent_sample.domain.content import CLASSIFY_TASK, REVIEW_TASK
from agent_sample.domain.errors import UnknownOption
from agent_sample.domain.ports import ContentLibrary, SubjectClassifier
from agent_sample.domain.review.model import CATEGORIES, DiffUnavailable

Implementations = Callable[[], tuple[SubjectClassifier, ...]]

# Código de saída quando a revisão pede mudanças (1 é erro e 2 é erro de uso do Click).
EXIT_REQUEST_CHANGES = 3


def build_app(
    service: ClassificationService,
    implementations: Implementations,
    content: ContentLibrary,
    review: ReviewService,
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

    @app.command("review")
    def review_diff(
        diff: str | None = typer.Argument(
            None, help="arquivo com o diff unificado ('-' lê da entrada padrão)"
        ),
        text: str | None = typer.Option(None, help="o diff unificado como texto"),
        base: str = typer.Option("", help="referência git de base; gera o diff até --head"),
        head: str = typer.Option("", help="referência git final (padrão: HEAD)"),
        repo: str = typer.Option(".", help="repositório lido pelo git e pelas ferramentas"),
        strategy: str = typer.Option("", help="workflow | agent | hybrid"),
        engine: str = typer.Option("", help="motor do workflow: sequential | langgraph"),
        agent: str = typer.Option("", help="agente: langgraph | deepagents"),
        prompt_version: str = typer.Option("", help="versão do prompt (padrão: última publicada)"),
        skill: list[str] = typer.Option([], help="fixa a versão de uma skill: nome@versão"),
        focus: list[str] = typer.Option([], help=f"foco da revisão: {' | '.join(CATEGORIES)}"),
        language: str = typer.Option("", help="linguagem dos arquivos sem extensão"),
        output_format: str = typer.Option("text", "--format", help=" | ".join(FORMATS)),
    ) -> None:
        """Revisa um diff. Sai com código 3 quando a decisão é request_changes."""
        options = review.defaults.merge(
            strategy=strategy,
            engine=engine,
            agent=agent,
            prompt_version=prompt_version,
            skills=tuple(skill),
            focus=tuple(focus),
            language=language,
            repo=repo,
        )

        def action() -> tuple[str, bool]:
            if output_format not in FORMATS:
                raise UnknownOption("format", output_format, tuple(FORMATS))
            source = _diff_text(review, options, diff, text, base, head)
            result = asyncio.run(review.review(source, options))
            return FORMATS[output_format](result), result.decision == "request_changes"

        output, request_changes = _attempt(action)
        typer.echo(output)
        if request_changes:
            raise typer.Exit(EXIT_REQUEST_CHANGES)

    @app.command("compare-review-prompts")
    def compare_review_prompts(
        diff: str = typer.Argument(..., help="arquivo com o diff unificado ('-' lê da entrada)"),
        version: list[str] = typer.Option([], help="versões a comparar (padrão: todas)"),
        agent: str = typer.Option("", help="agente: langgraph | deepagents"),
        repo: str = typer.Option(".", help="repositório lido pelas ferramentas"),
    ) -> None:
        """Compara versões do prompt de revisão lado a lado no mesmo diff."""

        def action() -> str:
            options = review.defaults.merge(strategy="agent", agent=agent, repo=repo)
            versions = version or [
                item.version for item in content.prompts() if item.name == REVIEW_TASK.prompt
            ]
            variants = tuple(
                (f"{REVIEW_TASK.prompt}@{value}", options.merge(prompt_version=value))
                for value in versions
            )
            source = _diff_text(review, options, diff, None, "", "")
            return format_review_comparison(asyncio.run(review.compare(source, variants)))

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
    typer.echo(_attempt(action))


def _attempt[T](action: Callable[[], T]) -> T:
    """Erros viram uma linha curta em stderr e código de saída 1, sem traceback."""
    try:
        return action()
    except Exception as exc:
        typer.echo(error_message(exc), err=True)
        raise typer.Exit(1) from None


def _diff_text(
    review: ReviewService,
    options: ReviewOptions,
    path: str | None,
    text: str | None,
    base: str,
    head: str,
) -> str:
    """O diff vem de exatamente uma fonte: arquivo (ou '-'), --text ou --base/--head."""
    if head and not base:
        raise DiffUnavailable("--head needs --base")
    given = [value for value in (path, text, base or None) if value is not None]
    if len(given) != 1:
        raise DiffUnavailable("choose exactly one diff source: a file (or -), --text or --base")
    if base:
        return review.diff_between(base, head or "HEAD", options)
    if text is not None:
        return text
    if path == "-":
        return sys.stdin.read()
    try:
        return Path(str(path)).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise DiffUnavailable(f"cannot read {path}: {exc.strerror}") from exc


def run(
    service: ClassificationService,
    implementations: Implementations,
    content: ContentLibrary,
    review: ReviewService,
) -> None:
    build_app(service, implementations, content, review)()
