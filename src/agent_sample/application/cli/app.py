import asyncio
from collections.abc import Callable

import typer

from agent_sample.application.cli.present import format_comparison, format_verdict
from agent_sample.application.compare import compare_subject
from agent_sample.domain.ports import SubjectClassifier
from agent_sample.domain.session import classify_subject

ClassifierFactory = Callable[[str], SubjectClassifier]
AllClassifiers = Callable[[], tuple[SubjectClassifier, ...]]


def build_app(factory: ClassifierFactory, all_classifiers: AllClassifiers) -> typer.Typer:
    app = typer.Typer(add_completion=False, no_args_is_help=True)

    @app.command()
    def classify(
        message: str,
        runtime: str = typer.Option("langgraph", "--runtime"),
    ) -> None:
        verdict = asyncio.run(classify_subject(message, factory(runtime)))
        typer.echo(format_verdict(verdict))

    @app.command()
    def compare(message: str) -> None:
        rows = asyncio.run(compare_subject(message, all_classifiers()))
        typer.echo(format_comparison(rows))

    return app


def run(factory: ClassifierFactory, all_classifiers: AllClassifiers) -> None:
    build_app(factory, all_classifiers)()
