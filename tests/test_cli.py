"""CLI ponta a ponta com os diffs de exemplo versionados, sem credencial de modelo."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_sample.application.cli.app import build_app
from agent_sample.composition import bootstrap, lock
from tests.fakes import EXAMPLES, isolated_env
from tests.test_tools import git_repo

DIFFS = EXAMPLES / "diffs"


@pytest.fixture
def cli(tmp_path: Path):
    env = isolated_env(tmp_path)
    app = build_app(lambda: bootstrap(env), lambda scopes: lock(scopes, env))
    runner = CliRunner()
    return lambda *args: runner.invoke(app, list(args))


def reviewed(cli, name: str, *args: str) -> tuple[int, dict]:
    result = cli("review", "--diff-file", str(DIFFS / name), "--format", "json", *args)
    return result.exit_code, json.loads(result.stdout) if result.exit_code in (0, 1) else {}


def test_api_key_is_critical_security_and_requests_changes(cli) -> None:
    code, review = reviewed(cli, "api_key.diff")
    assert code == 1
    assert review["decision"] == "request_changes"
    assert [(f["severity"], f["category"]) for f in review["findings"]] == [
        ("critical", "security")
    ]
    assert "sk-test-4f9a8b7c6d5e" not in json.dumps(review)


def test_debug_print_is_minor_and_comments(cli) -> None:
    code, review = reviewed(cli, "debug_print.diff")
    assert code == 0
    assert review["decision"] == "comment"
    assert [f["severity"] for f in review["findings"]] == ["minor"]


def test_source_without_tests_gets_a_tests_finding(cli) -> None:
    code, review = reviewed(cli, "untested_change.diff")
    assert (code, review["decision"]) == (0, "comment")
    assert [f["category"] for f in review["findings"]] == ["tests"]


def test_clean_change_with_tests_is_approved(cli) -> None:
    code, review = reviewed(cli, "clean.diff")
    assert (code, review["decision"], review["findings"]) == (0, "approve", [])


def test_binary_file_is_listed_as_not_reviewed(cli) -> None:
    code, review = reviewed(cli, "binary.diff")
    assert code == 0
    assert review["unreviewed"] == [{"file": "docs/logo.png", "reason": "binary file"}]


def test_empty_diff_is_a_clear_error(cli) -> None:
    result = cli("review", "--diff-file", str(DIFFS / "empty.diff"))
    assert result.exit_code == 2
    assert result.output.strip() == "error: diff is empty: nothing to review"


def test_default_mode_without_model_records_the_missing_agent(cli) -> None:
    _, review = reviewed(cli, "clean.diff")
    steps = {step["name"]: step for step in review["trace"]["steps"]}
    assert steps["plan"]["outcome"] == "degraded"
    assert steps["agentic_review"]["outcome"] == "skipped"
    assert review["trace"]["failures"] == ["agentic review unavailable: MODEL_API_KEY is not set"]


def test_agent_mode_without_model_fails_clearly(cli) -> None:
    result = cli("review", "--diff-file", str(DIFFS / "clean.diff"), "--mode", "agent")
    assert result.exit_code == 2
    assert "agentic review unavailable: MODEL_API_KEY is not set" in result.output


@pytest.mark.parametrize("output", ["text", "json", "pr-comments"])
def test_workflow_mode_is_byte_for_byte_reproducible(cli, output: str) -> None:
    args = ("review", "--diff-file", str(DIFFS / "api_key.diff"), "--mode", "workflow")
    first = cli(*args, "--format", output)
    second = cli(*args, "--format", output)
    assert first.stdout == second.stdout
    assert first.exit_code == second.exit_code == 1


def test_errors_are_short_and_without_traceback(cli) -> None:
    for args in (
        ("review",),
        ("review", "--diff", "x", "--pr", "a/b#1"),
        ("review", "--diff", "not a diff"),
        ("review", "--diff-file", str(DIFFS / "clean.diff"), "--mode", "magic"),
        ("review", "--diff-file", str(DIFFS / "clean.diff"), "--format", "xml"),
        ("review", "--diff-file", str(DIFFS / "clean.diff"), "--plugin", "nope"),
    ):
        result = cli(*args)
        assert result.exit_code == 2, args
        assert result.output.startswith("error: "), result.output
        assert "Traceback" not in result.output


def test_reviews_two_git_references(cli, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    git_repo(repo)
    result = cli("review", "--repo", str(repo), "--base", "HEAD~1", "--head", "HEAD")
    assert result.exit_code == 0, result.output
    assert "source: HEAD~1...HEAD" in result.output
    assert "missing-tests" in result.output


def test_stdin_diff_and_pr_comment_format(cli) -> None:
    runner_input = (DIFFS / "debug_print.diff").read_text()
    app_result = cli("review", "--diff", runner_input, "--format", "pr-comments")
    assert app_result.exit_code == 0
    assert app_result.output.startswith("**Code review: `comment`**")
    assert "`src/orders/service.py:6`" in app_result.output


def test_compare_plugin_versions_side_by_side(cli) -> None:
    result = cli(
        "compare",
        "--diff-file",
        str(DIFFS / "api_key.diff"),
        "--plugin",
        "code-review@1.0.0",
        "--plugin",
        "code-review",
    )
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[1] == "code-review@1.0.0\trequest_changes\t1\t1"


def test_plugin_and_skill_inspection(cli) -> None:
    listed = cli("plugins", "list")
    assert "code-review\t1.0.0\tbuiltin\tenabled,default" in listed.output
    shown = cli("plugins", "show", "code-review")
    assert "security-reviewer" in shown.output
    assert cli("plugins", "validate").output.startswith("ok: 1 plugin(s)")
    assert "lead-reviewer\tcode-review\t1.0.0" in cli("skills", "list").output
    assert "# code-review:security-review@1.0.0" in cli("skills", "show", "security-review").output
