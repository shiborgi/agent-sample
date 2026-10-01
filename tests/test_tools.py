"""As ferramentas do agente só leem o repositório revisado."""

import asyncio
import subprocess
from pathlib import Path

import pytest

from agent_sample.domain.change import PullRequestContext
from agent_sample.domain.model import ChangeNotFound
from agent_sample.domain.tools import OutsideRepository, RunContext, Toolbox, safe_path
from agent_sample.infrastructure.repository.git import GitRevisionReader, GitRevisionSource
from agent_sample.infrastructure.repository.worktree import RepositoryReaders, WorktreeReader
from tests.fakes import builtin_capabilities


def git_repo(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)

    def run(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("def one():\n    return 1\n")
    run("add", ".")
    run("commit", "-q", "-m", "base")
    (root / "src" / "app.py").write_text("def one():\n    return 1\n\n\ndef two():\n    return 2\n")
    run("commit", "-q", "-am", "head")
    return run("rev-parse", "HEAD")


def toolbox(
    reader: object, max_output: int = 8000, pr: PullRequestContext | None = None
) -> Toolbox:
    return Toolbox(RunContext(reader, builtin_capabilities(), pr), max_output)  # type: ignore[arg-type]


def call(box: Toolbox, tool: str, **arguments: object) -> str:
    return asyncio.run(box.call(tool, dict(arguments)))


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "src/../../x", "C:/x", "..\\x"])
def test_paths_outside_the_repository_are_refused(path: str) -> None:
    with pytest.raises(OutsideRepository):
        safe_path(path)


def test_safe_paths_are_normalized() -> None:
    assert safe_path("src/./app.py") == "src/app.py"
    assert safe_path("") == ""


def test_worktree_reader_stays_inside_the_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("a = 1\nb = 2\n")
    (tmp_path / "secret.txt").write_text("TOP SECRET")
    (repo / "link.txt").symlink_to(tmp_path / "secret.txt")
    box = toolbox(WorktreeReader(str(repo)))
    assert call(box, "read_repo_file", path="src/app.py", start_line=2) == "2: b = 2"
    for escape in ("../secret.txt", "link.txt", str(tmp_path / "secret.txt")):
        output = call(box, "read_repo_file", path=escape)
        assert output.startswith("error: path is outside the reviewed repository")
        assert "TOP SECRET" not in output
    assert "TOP SECRET" not in call(box, "search_code", query="TOP SECRET")
    assert call(box, "list_repo_files") == "link.txt\nsrc/"
    assert call(box, "list_repo_files", directory="..").startswith("error:")
    assert [record.outcome.split(":")[0] for record in box.calls].count("error") == 4


def test_worktree_search_uses_git_grep_inside_a_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    git_repo(repo)
    (repo / "untracked.py").write_text("def two():\n    pass\n")
    box = toolbox(WorktreeReader(str(repo)))
    assert call(box, "search_code", query="def two") == "src/app.py:5:def two():"
    assert call(box, "search_code", query="nothing like this") == "(no matches)"


def test_git_reader_reads_only_the_reviewed_revision(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    head = git_repo(repo)
    box = toolbox(RepositoryReaders().open(str(repo), head))
    assert "5: def two():" in call(box, "read_repo_file", path="src/app.py")
    assert call(box, "search_code", query="def two") == "src/app.py:5:def two():"
    assert call(box, "list_repo_files", directory="src") == "src/app.py"
    assert "def two():" in call(box, "blame", path="src/app.py", start_line=5, end_line=5)
    assert call(box, "read_repo_file", path="../../etc/passwd").startswith("error: path is outside")
    assert call(box, "read_repo_file", path="missing.py").startswith("error: git show")


def test_tool_output_is_truncated_with_a_warning(tmp_path: Path) -> None:
    (tmp_path / "big.txt").write_text("x" * 500)
    box = toolbox(WorktreeReader(str(tmp_path)), max_output=50)
    output = call(box, "read_repo_file", path="big.txt")
    assert output.endswith("[truncated: 453 more characters]")
    assert box.calls[-1].outcome == "ok (truncated)"


def test_tools_offered_depend_on_what_the_review_has() -> None:
    assert [spec.name for spec in toolbox(None).specs()] == ["load_skill"]
    pr = PullRequestContext("t", "d", ("#1 bug",), "success")
    names = [spec.name for spec in toolbox(WorktreeReader("."), pr=pr).specs()]
    assert names == [
        "read_repo_file",
        "search_code",
        "list_repo_files",
        "blame",
        "load_skill",
        "pr_context",
    ]
    assert "#1 bug" in call(toolbox(None, pr=pr), "pr_context")


def test_load_skill_records_the_version() -> None:
    box = toolbox(None)
    assert "Verifique" in call(box, "load_skill", name="code-review:security-review")
    assert call(box, "load_skill", name="nope").startswith("error: unknown skill: nope")
    assert box.loaded_skills == ("code-review:security-review@1.0.0",)


def test_git_source_diffs_two_references(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    git_repo(repo)
    diff = asyncio.run(GitRevisionSource().diff(str(repo), "HEAD~1", "HEAD"))
    assert "+def two():" in diff
    with pytest.raises(ChangeNotFound, match="'nope' does not exist"):
        asyncio.run(GitRevisionSource().diff(str(repo), "nope", "HEAD"))
    with pytest.raises(ChangeNotFound, match="not a git repository"):
        asyncio.run(GitRevisionSource().diff(str(tmp_path), "HEAD~1", "HEAD"))


def test_git_reader_never_takes_option_like_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    head = git_repo(repo)
    reader = GitRevisionReader(str(repo), head)
    with pytest.raises(OutsideRepository):
        asyncio.run(reader.read("--output=/tmp/x", None, None))
