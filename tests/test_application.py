import asyncio
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_sample.application.a2a.text import artifact_text
from agent_sample.application.cli.app import build_app
from agent_sample.application.cli.present import format_comparison
from agent_sample.application.compare import compare_subject
from agent_sample.application.service import ClassificationService, ClassifyOptions
from agent_sample.composition import bootstrap
from agent_sample.domain.errors import ContentError
from agent_sample.domain.model import ClassificationFailed, Verdict
from agent_sample.domain.trace import Step
from tests.fakes import ENV, FixedClassifier, ScriptedGateway, composition, review_service


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    for name in (*ENV, "CONTENT_DIR"):
        monkeypatch.delenv(name, raising=False)
    return CliRunner()


@pytest.mark.parametrize(
    ("message", "subject_id"),
    [
        ("Fui cobrado duas vezes", "billing"),
        ("A API retorna 500", "technical"),
        ("O suporte está demorando", "other"),
        ("Preciso de capital de giro", "other"),
        ("Erro na fatura", "other"),
        ("Bom dia", "other"),
    ],
)
def test_default_cli_works_without_model_credentials(
    offline: CliRunner, message: str, subject_id: str
) -> None:
    service, review, root = bootstrap()
    result = offline.invoke(
        build_app(service, root.implementations, root.content, review), ["classify", message]
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.split("\t")[0] == subject_id


def test_cli_errors_are_short_and_exit_non_zero(offline: CliRunner) -> None:
    service, review, root = bootstrap()
    app = build_app(service, root.implementations, root.content, review)
    result = offline.invoke(app, ["classify", "Bom dia", "--strategy", "agent"])
    assert result.exit_code == 1
    assert result.stderr.strip() == (
        "error: agent:langgraph failed: model unavailable: MODEL_API_KEY is not set"
    )
    assert "Traceback" not in result.output


def test_invalid_content_dir_fails_at_startup(
    offline: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONTENT_DIR", str(tmp_path))
    with pytest.raises(ContentError, match="prompt not found: classify_subject"):
        bootstrap()


def test_cli_options_select_strategy_agent_and_versions(offline: CliRunner) -> None:
    root = composition(ScriptedGateway("sales"))
    service = ClassificationService(root.build, ClassifyOptions())
    app = build_app(service, root.implementations, root.content, review_service(root))
    result = offline.invoke(
        app,
        [
            "classify",
            "Fui cobrado",
            "--strategy",
            "agent",
            "--agent",
            "deepagents",
            "--prompt-version",
            "v1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("sales\tagent:deepagents")
    assert "prompt=classify_subject@v1" in result.stdout


def test_cli_compare_prompts_and_lists_content(offline: CliRunner) -> None:
    root = composition(ScriptedGateway("billing"))
    service = ClassificationService(root.build, ClassifyOptions())
    app = build_app(service, root.implementations, root.content, review_service(root))
    compared = offline.invoke(app, ["compare-prompts", "Erro na fatura"])
    assert compared.exit_code == 0, compared.output
    assert "prompt=classify_subject@v1" in compared.stdout
    assert "prompt=classify_subject@v2" in compared.stdout
    assert "classify_subject\tv2\tpublished" in offline.invoke(app, ["prompts", "list"]).stdout
    assert "out-of-scope\tv1" in offline.invoke(app, ["skills", "list"]).stdout
    shown = offline.invoke(app, ["skills", "show", "out-of-scope"]).stdout
    assert shown.startswith("# Fora de escopo")


def test_compare_runs_every_implementation(offline: CliRunner) -> None:
    root = composition(ScriptedGateway("billing"))
    names = [classifier.name for classifier in root.implementations()]
    assert names == [
        "workflow:sequential",
        "workflow:langgraph",
        "agent:langgraph",
        "agent:deepagents",
        "prediction:fixed",
    ]


def test_compare_keeps_each_result() -> None:
    rows = asyncio.run(
        compare_subject(
            "fui cobrado duas vezes",
            (
                FixedClassifier("billing"),
                FixedClassifier("technical", ClassificationFailed("deepagents", "boom")),
            ),
        )
    )
    rendered = format_comparison(rows)
    assert "billing" in rendered
    assert "deepagents: boom" in rendered


def test_artifact_text_carries_the_path() -> None:
    step = Step("agent", "langgraph", "decided", "erro", "classify_subject@v2", ("x@v1",))
    text = artifact_text(Verdict("technical", "erro de api", "agent:langgraph", (step,)))
    assert text.startswith("technical (n/a) erro de api")
    assert "decided_by: agent:langgraph" in text
    assert "prompt=classify_subject@v2 skills=x@v1" in text
