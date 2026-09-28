import asyncio

from typer.testing import CliRunner

from agent_sample.application.a2a.text import artifact_text
from agent_sample.application.cli.app import build_app
from agent_sample.application.cli.present import format_comparison
from agent_sample.application.compare import compare_subject
from agent_sample.domain.model import ClassificationFailed, Verdict
from tests.fakes import FixedClassifier


def test_compare_keeps_each_runtime_result() -> None:
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
    assert "deepagents" in rendered
    assert "boom" in rendered


def test_cli_classify_uses_the_injected_factory() -> None:
    def factory(runtime: str) -> FixedClassifier:
        assert runtime == "laya"
        return FixedClassifier("sales")

    app = build_app(factory, lambda: ())
    result = CliRunner().invoke(app, ["classify", "quero um demo", "--runtime", "laya"])
    assert result.exit_code == 0
    assert "sales" in result.output


def test_artifact_text_is_plain() -> None:
    text = artifact_text(Verdict("technical", 0.8, "erro de api", "langgraph"))
    assert text.startswith("technical")
    assert "erro de api" in text
