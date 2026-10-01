import asyncio
from collections.abc import Callable
from functools import cache

import typer

from agent_sample.application.cli.present import (
    format_comparison,
    format_plugin,
    format_plugins,
    format_skills,
)
from agent_sample.application.service import ReviewService, error_message
from agent_sample.domain.change import ChangeRef, InlineDiff, PullRequest, RevisionRange
from agent_sample.domain.model import ReviewError

EXIT_REQUEST_CHANGES = 1
EXIT_ERROR = 2

Bootstrap = Callable[[], ReviewService]
Lock = Callable[[tuple[str, ...]], list[str]]


class SourceError(ReviewError, ValueError):
    pass


def change_ref(
    diff: str, diff_file: typer.FileText | None, repo: str, base: str, head: str, pr: str
) -> ChangeRef:
    """Exatamente uma fonte: texto, arquivo (`-` = stdin), duas referências git ou PR remoto."""
    chosen = [
        name
        for name, given in (("--diff", diff), ("--diff-file", diff_file), ("--pr", pr))
        if given
    ]
    if base or head:
        chosen.append("--base/--head")
    if len(chosen) != 1:
        raise SourceError(
            "choose exactly one change source: --diff, --diff-file, --base/--head or --pr"
        )
    if pr:
        return PullRequest(pr, repository=repo or None)
    if base or head:
        if not (base and head):
            raise SourceError("--base and --head go together")
        return RevisionRange(repo or ".", base, head)
    text = diff if diff else diff_file.read() if diff_file else ""
    return InlineDiff(text, repository=repo or None)


def build_app(bootstrap: Bootstrap, lock: Lock) -> typer.Typer:
    app = typer.Typer(add_completion=False, no_args_is_help=True, pretty_exceptions_enable=False)
    plugins = typer.Typer(no_args_is_help=True, help="Lista, inspeciona, valida e trava plugins.")
    skills = typer.Typer(no_args_is_help=True, help="Lista e inspeciona skills.")
    app.add_typer(plugins, name="plugins")
    app.add_typer(skills, name="skills")
    service = cache(bootstrap)

    source_options = {
        "diff": typer.Option("", help="diff unificado em texto"),
        "diff_file": typer.Option(None, help="arquivo com o diff (- para stdin)"),
        "repo": typer.Option("", help="repositório local (contexto das ferramentas; git)"),
        "base": typer.Option("", help="referência base (git)"),
        "head": typer.Option("", help="referência revisada (git)"),
        "pr": typer.Option("", help="pull request: URL ou dono/repo#número"),
    }

    @app.command()
    def review(
        diff: str = source_options["diff"],
        diff_file: typer.FileText | None = source_options["diff_file"],
        repo: str = source_options["repo"],
        base: str = source_options["base"],
        head: str = source_options["head"],
        pr: str = source_options["pr"],
        mode: str = typer.Option("", help="workflow | hybrid | agent"),
        focus: list[str] = typer.Option([], help="foco: security, tests, performance..."),
        language: str = typer.Option("", help="linguagem, quando não dá para deduzir"),
        plugin: list[str] = typer.Option([], help="plugin a usar: nome ou nome@versão"),
        skill: list[str] = typer.Option([], help="restringe as skills oferecidas"),
        output: str = typer.Option("", "--format", help="text | json | pr-comments"),
        post: bool = typer.Option(False, "--post", help="publica a revisão no PR remoto"),
    ) -> None:
        """Revisa uma mudança. Sai com 1 se a decisão for request_changes e 2 em erro."""

        def action() -> tuple[str, int]:
            ref = change_ref(diff, diff_file, repo, base, head, pr)
            reviewer = service()
            options = reviewer.defaults.merge(
                mode=mode,
                focus=tuple(focus),
                language=language,
                plugins=tuple(plugin),
                skills=tuple(skill),
                format=output,
                post=post,
            )
            result = asyncio.run(reviewer.review(ref, options))
            code = EXIT_REQUEST_CHANGES if result.review.decision == "request_changes" else 0
            return result.output, code

        _run(action)

    @app.command()
    def compare(
        diff: str = source_options["diff"],
        diff_file: typer.FileText | None = source_options["diff_file"],
        repo: str = source_options["repo"],
        base: str = source_options["base"],
        head: str = source_options["head"],
        pr: str = source_options["pr"],
        mode: str = typer.Option("", help="workflow | hybrid | agent"),
        plugin: list[str] = typer.Option(..., help="uma variante por valor: nome@versão"),
    ) -> None:
        """Revisa a mesma mudança com versões de plugin diferentes, lado a lado."""

        def action() -> tuple[str, int]:
            ref = change_ref(diff, diff_file, repo, base, head, pr)
            reviewer = service()
            rows = []
            for variant in plugin:
                options = reviewer.defaults.merge(mode=mode, plugins=(variant,), format="text")
                rows.append((variant, asyncio.run(reviewer.review(ref, options)).review))
            return format_comparison(rows), 0

        _run(action)

    @plugins.command("list")
    def list_plugins() -> None:
        """Plugins carregados, com fonte, versão, estado e conflitos."""
        _run(lambda: (format_plugins(service().catalog), 0))

    @plugins.command("show")
    def show_plugin(name: str) -> None:
        """Detalha um plugin (nome ou nome@versão): skills, revisores e avisos."""
        _run(lambda: (format_plugin(service().catalog, name), 0))

    @plugins.command("validate")
    def validate_plugins() -> None:
        """Valida manifesto, skills, revisores, ferramentas, compatibilidade e lock."""

        def action() -> tuple[str, int]:
            catalog = service().catalog
            loaded = catalog.plugins()
            warnings = [f"  {p.ref}: {w}" for p in loaded for w in p.warnings]
            lines = [f"ok: {len(loaded)} plugin(s) valid and matching the lock", *warnings]
            return "\n".join(lines), 0

        _run(action)

    @plugins.command("lock")
    def lock_plugins(
        builtin: bool = typer.Option(False, help="também trava o plugin embutido (mantenedores)"),
    ) -> None:
        """Resolve as fontes configuradas e grava o lock (fonte, versão resolvida e hash)."""
        scopes = ("builtin", "user", "project") if builtin else ("user", "project")
        _run(lambda: ("\n".join(lock(scopes)) or "no configured sources to lock", 0))

    @skills.command("list")
    def list_skills() -> None:
        """Skills dos plugins habilitados, com versão e conflitos."""
        _run(lambda: (format_skills(service().catalog), 0))

    @skills.command("show")
    def show_skill(name: str) -> None:
        """Mostra o corpo de uma skill (nome ou plugin:nome)."""

        def action() -> tuple[str, int]:
            found = service().catalog.select(()).skill(name)
            if found is None:
                raise ReviewError(f"skill not found: {name}")
            return f"# {found.ref}\n{found.description}\n\n{found.body}", 0

        _run(action)

    return app


def _run(action: Callable[[], tuple[str, int]]) -> None:
    try:
        output, code = action()
    except Exception as exc:
        typer.echo(error_message(exc), err=True)
        raise typer.Exit(EXIT_ERROR) from None
    typer.echo(output)
    if code:
        raise typer.Exit(code)


def run(bootstrap: Bootstrap, lock: Lock) -> None:
    build_app(bootstrap, lock)()
