import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from agent_sample.application.cli.app import EXIT_REQUEST_CHANGES, build_app
from agent_sample.application.review import ReviewOptions
from agent_sample.application.service import ClassificationService, ClassifyOptions
from agent_sample.composition import bootstrap
from agent_sample.domain.review.model import DiffUnavailable, RepositoryError
from agent_sample.infrastructure.repository.git import GitDiffSource
from tests.fakes import ENV, ScriptedReviewGateway, composition, review_service

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "review"


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    """A CLI como sai da inicialização padrão, sem credencial de modelo."""
    for name in (*ENV, "CONTENT_DIR"):
        monkeypatch.delenv(name, raising=False)
    return CliRunner()


def invoke(runner: CliRunner, *args: str, stdin: str | None = None) -> Result:
    service, review, root = bootstrap()
    app = build_app(service, root.implementations, root.content, review)
    return runner.invoke(app, ["review", *args], input=stdin)


def as_json(result: Result) -> dict[str, object]:
    return json.loads(result.stdout)


def findings(result: Result) -> list[tuple[str, str]]:
    return [(item["severity"], item["category"]) for item in as_json(result)["findings"]]  # type: ignore[index]


def test_api_key_example_requests_changes(cli: CliRunner) -> None:
    result = invoke(cli, str(EXAMPLES / "api_key.diff"), "--format", "json")
    assert result.exit_code == EXIT_REQUEST_CHANGES
    assert ("critical", "security") in findings(result)
    assert as_json(result)["decision"] == "request_changes"
    assert "9f8e7d6c5b4a" not in result.stdout


def test_debug_print_example_comments(cli: CliRunner) -> None:
    result = invoke(cli, str(EXAMPLES / "debug_print.diff"), "--format", "json")
    assert result.exit_code == 0, result.output
    assert findings(result) == [("minor", "maintainability")]
    assert as_json(result)["decision"] == "comment"


def test_source_without_tests_example_comments(cli: CliRunner) -> None:
    result = invoke(cli, str(EXAMPLES / "source_without_tests.diff"), "--format", "json")
    assert result.exit_code == 0, result.output
    assert findings(result) == [("minor", "tests")]
    assert as_json(result)["decision"] == "comment"


def test_clean_example_with_test_approves(cli: CliRunner) -> None:
    result = invoke(cli, str(EXAMPLES / "clean_with_test.diff"), "--format", "json")
    assert result.exit_code == 0, result.output
    assert findings(result) == []
    assert as_json(result)["decision"] == "approve"


def test_binary_example_lists_the_file_as_unreviewed(cli: CliRunner) -> None:
    result = invoke(cli, str(EXAMPLES / "binary_file.diff"), "--format", "json")
    assert result.exit_code == 0, result.output
    assert as_json(result)["unreviewed"] == [
        {"path": "assets/logo.png", "reason": "arquivo binário"}
    ]


def test_empty_example_is_a_clear_error(cli: CliRunner) -> None:
    result = invoke(cli, str(EXAMPLES / "empty.diff"))
    assert result.exit_code == 1
    assert result.stderr.strip() == "error: diff is empty"
    assert result.stdout == ""
    assert "Traceback" not in result.output


def test_default_mode_records_that_the_agent_was_unavailable(cli: CliRunner) -> None:
    result = invoke(cli, str(EXAMPLES / "debug_print.diff"), "--format", "json")
    trace = as_json(result)["trace"]
    failed = [step for step in trace if step["kind"] == "agent"]  # type: ignore[union-attr]
    assert failed[0]["outcome"] == "failed"  # type: ignore[index]
    assert "model unavailable: MODEL_API_KEY is not set" in failed[0]["detail"]  # type: ignore[index]
    assert failed[0]["prompt"] == "review_change@v1"  # type: ignore[index]
    assert "O agente falhou" in as_json(result)["summary"]  # type: ignore[operator]


@pytest.mark.parametrize("output", ["json", "text"])
def test_workflow_mode_is_byte_for_byte_reproducible(cli: CliRunner, output: str) -> None:
    args = (str(EXAMPLES / "api_key.diff"), "--strategy", "workflow", "--format", output)
    first, second = invoke(cli, *args), invoke(cli, *args)
    assert first.stdout == second.stdout
    assert first.stdout


def test_text_output_is_readable(cli: CliRunner) -> None:
    result = invoke(cli, str(EXAMPLES / "api_key.diff"), "--strategy", "workflow")
    lines = result.stdout.splitlines()
    assert lines[0] == "request_changes\tworkflow:sequential"
    assert "  1. [critical/security] app/config.py:2 (rule:secrets)" in lines
    assert '     > +API_KEY = "9f8e****"' in lines
    assert lines[-1].endswith("request_changes: 1 critical, 1 minor")


def test_diff_from_text_and_stdin(cli: CliRunner) -> None:
    diff = (EXAMPLES / "clean_with_test.diff").read_text()
    assert invoke(cli, "--text", diff).stdout.startswith("approve")
    assert invoke(cli, "-", stdin=diff).stdout.startswith("approve")


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((), "choose exactly one diff source"),
        (("x.diff", "--text", "y"), "choose exactly one diff source"),
        (("--head", "HEAD"), "--head needs --base"),
        (("missing.diff",), "cannot read missing.diff"),
        (("--text", "não é diff"), "not a readable unified diff"),
        (("--text", "x", "--format", "xml"), "unknown format: xml"),
        (("--text", "x", "--focus", "speed"), "unknown focus: speed"),
        (("--text", "x", "--strategy", "magic"), "unknown strategy: magic"),
    ],
)
def test_bad_input_is_a_short_error(cli: CliRunner, args: tuple[str, ...], message: str) -> None:
    result = invoke(cli, *args)
    assert result.exit_code == 1
    assert result.stderr.startswith("error: ")
    assert message in result.stderr


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)
    return completed.stdout.decode()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "test")
    (root / "app.py").write_text("x = 1\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    (root / "app.py").write_text('x = 1\nprint("debug")\n')
    git(root, "commit", "-qam", "change")
    return root


def test_diff_between_two_git_references(cli: CliRunner, repo: Path) -> None:
    result = invoke(
        cli, "--base", "HEAD~1", "--repo", str(repo), "--strategy", "workflow", "--format", "json"
    )
    assert result.exit_code == 0, result.output
    assert [(item["path"], item["start_line"]) for item in as_json(result)["findings"]] == [  # type: ignore[index]
        ("app.py", 2),
        ("app.py", 2),
    ]


def test_git_references_cannot_become_options(repo: Path) -> None:
    source = GitDiffSource(repo)
    with pytest.raises(DiffUnavailable, match="invalid git reference: '--output=x'"):
        source.between("--output=x", "HEAD")
    with pytest.raises(DiffUnavailable, match="git diff failed"):
        source.between("nope", "HEAD")


def test_compare_review_prompts_side_by_side(cli: CliRunner, tmp_path: Path) -> None:
    root = composition(ScriptedReviewGateway())
    service = ClassificationService(root.build, ClassifyOptions())
    app = build_app(service, root.implementations, root.content, review_service(root))
    diff = str(EXAMPLES / "debug_print.diff")
    result = cli.invoke(app, ["compare-review-prompts", diff, "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[1].startswith("review_change@v1\tapprove\t0")
    assert "prompt=review_change@v1 skills=python-practices@v1" in result.stdout


def test_repository_must_exist(tmp_path: Path) -> None:
    root = composition(ScriptedReviewGateway())
    options = ReviewOptions(repo=str(tmp_path / "nope"))
    with pytest.raises(RepositoryError, match="repository not found"):
        root.reviewer(options)
