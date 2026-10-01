"""Importação modular de plugins: fontes, lock, precedência e validação na inicialização."""

import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_sample.application.cli.app import build_app
from agent_sample.composition import (
    BUILTIN_PLUGINS,
    REVIEWER_VERSION,
    bootstrap,
    load_settings,
    lock,
)
from agent_sample.domain.model import CapabilityError
from agent_sample.infrastructure.plugins.catalog import load_catalog
from tests.fakes import EXAMPLES, isolated_env


def make_plugin(
    root: Path,
    name: str = "extra",
    version: str = "1.0.0",
    skills: tuple[str, ...] = ("extra-skill",),
    agent: str | None = None,
    requires: str | None = None,
) -> Path:
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "version": version, "description": f"{name} plugin"}
    if requires:
        manifest["reviewer"] = {"requires": requires}
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest))
    for skill in skills:
        folder = root / "skills" / skill
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {skill}\ndescription: {skill} criteria\n---\nCheck {skill}.\n"
        )
    if agent is not None:
        (root / "agents").mkdir(exist_ok=True)
        (root / "agents" / "extra-reviewer.md").write_text(agent)
    return root


def configure(tmp_path: Path, sources: str) -> dict[str, str]:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    (project / "reviewer.toml").write_text(sources)
    return isolated_env(tmp_path, REVIEWER_CONFIG=str(project / "reviewer.toml"))


def dir_source(path: Path, name: str = "local") -> str:
    return f'[[sources]]\nname = "{name}"\nkind = "dir"\npath = "{path}"\n'


def catalog(env: dict[str, str]):
    config, cache = load_settings(env)
    return load_catalog(config, REVIEWER_VERSION, cache)


def test_builtin_plugin_matches_its_shipped_lock(tmp_path: Path) -> None:
    loaded = catalog(isolated_env(tmp_path))
    assert [plugin.ref for plugin in loaded.plugins()] == ["code-review@1.0.0"]
    assert loaded.conflicts() == ()


def test_external_example_plugin_is_imported_by_configuration(tmp_path: Path) -> None:
    shutil.copytree(EXAMPLES / "plugins", tmp_path / "plugins")
    env = configure(tmp_path, dir_source(tmp_path / "plugins", "examples"))
    lock(("project",), env)
    selected = catalog(env).select(())
    assert [plugin.ref for plugin in selected.plugins] == [
        "code-review@1.0.0",
        "django-review@1.0.0",
    ]
    reviewer = next(item for item in selected.reviewers if item.name == "django-reviewer")
    assert reviewer.tools == ("read_repo_file", "search_code", "load_skill")
    plugin = selected.plugins[-1]
    assert "commands/: ignored (not supported)" in plugin.warnings
    assert "agents/django-reviewer.md: 'model' ignored" in plugin.warnings
    result = CliRunner().invoke(
        build_app(lambda: bootstrap(env), lambda s: lock(s, env)), ["plugins", "list"]
    )
    assert "django-review\t1.0.0\texamples\tenabled,default" in result.output


def test_shipped_example_configuration_matches_its_lock(tmp_path: Path) -> None:
    env = isolated_env(tmp_path, REVIEWER_CONFIG=str(EXAMPLES / "reviewer.toml"))
    assert "django-review@1.0.0" in [plugin.ref for plugin in catalog(env).plugins()]


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (
            lambda root: (root / ".claude-plugin" / "plugin.json").write_text("{nope"),
            "invalid JSON",
        ),
        (
            lambda root: (root / ".claude-plugin" / "plugin.json").write_text('{"name": "extra"}'),
            "'version' is required",
        ),
        (
            lambda root: (root / "skills" / "extra-skill" / "SKILL.md").write_text(
                "no frontmatter"
            ),
            "frontmatter",
        ),
        (
            lambda root: (root / "skills" / "extra-skill" / "helper.py").write_text("run()"),
            "executable",
        ),
        (
            lambda root: (root / "skills" / "extra-skill" / "run.sh").write_text("#!/bin/sh\n"),
            "executable",
        ),
        (
            lambda root: (root / "skills" / "extra-skill" / "escape").symlink_to(
                Path("/etc/passwd")
            ),
            "outside the plugin root",
        ),
    ],
)
def test_invalid_plugin_fails_at_startup(tmp_path: Path, damage, message: str) -> None:
    root = make_plugin(tmp_path / "plugins" / "extra")
    damage(root)
    env = configure(tmp_path, dir_source(tmp_path / "plugins"))
    with pytest.raises(CapabilityError, match=message):
        lock(("project",), env)


def reviewer_file(tools: str, skills: str) -> str:
    return (
        f"---\nname: extra-reviewer\ndescription: extra\ntools: {tools}\nskills: {skills}\n---\n"
        "Review.\n"
    )


def test_reviewer_with_unknown_skill_or_tool_invalidates_the_plugin(tmp_path: Path) -> None:
    make_plugin(tmp_path / "a" / "extra", agent=reviewer_file("Read", "missing-skill"))
    env = configure(tmp_path, dir_source(tmp_path / "a"))
    with pytest.raises(CapabilityError, match="unknown skill"):
        lock(("project",), env)
    make_plugin(tmp_path / "b" / "extra", agent=reviewer_file("Read, Bash", "extra-skill"))
    env = configure(tmp_path, dir_source(tmp_path / "b"))
    with pytest.raises(CapabilityError, match="unknown tool 'Bash'"):
        lock(("project",), env)


def test_content_that_diverges_from_the_lock_fails_at_startup(tmp_path: Path) -> None:
    root = make_plugin(tmp_path / "plugins" / "extra")
    env = configure(tmp_path, dir_source(tmp_path / "plugins"))
    with pytest.raises(CapabilityError, match="not in .*reviewer.lock.json"):
        catalog(env)
    lock(("project",), env)
    catalog(env)
    (root / "skills" / "extra-skill" / "SKILL.md").write_text(
        "---\nname: extra-skill\ndescription: changed\n---\nChanged.\n"
    )
    with pytest.raises(CapabilityError, match="content differs from the lock"):
        catalog(env)
    result = CliRunner().invoke(
        build_app(lambda: bootstrap(env), lambda s: lock(s, env)), ["plugins", "validate"]
    )
    assert result.exit_code == 2
    assert "content differs from the lock" in result.output
    assert "Traceback" not in result.output


def test_name_conflict_follows_precedence_and_is_listed(tmp_path: Path) -> None:
    make_plugin(
        tmp_path / "plugins" / "code-review",
        name="code-review",
        version="9.0.0",
        skills=("lead-reviewer", "security-review"),
    )
    make_plugin(tmp_path / "plugins" / "extra", skills=("security-review",))
    env = configure(tmp_path, dir_source(tmp_path / "plugins", "mine"))
    lock(("project",), env)
    loaded = catalog(env)
    assert [plugin.ref for plugin in loaded.plugins()] == ["code-review@9.0.0", "extra@1.0.0"]
    conflicts = {(item.kind, item.name): item for item in loaded.conflicts()}
    plugin = conflicts[("plugin", "code-review")]
    assert plugin.winner.startswith("project:mine")
    assert plugin.shadowed[0].startswith("builtin:builtin")
    assert conflicts[("skill", "security-review")].winner == "extra"
    assert loaded.select(()).skill("security-review").plugin == "extra"
    runner = CliRunner().invoke(
        build_app(lambda: bootstrap(env), lambda s: lock(s, env)), ["plugins", "list"]
    )
    assert "plugin code-review: project:mine" in runner.output


def test_versions_coexist_and_can_be_pinned_or_disabled(tmp_path: Path) -> None:
    make_plugin(tmp_path / "plugins" / "extra" / "1.0.0")
    make_plugin(tmp_path / "plugins" / "extra" / "1.1.0", version="1.1.0")
    env = configure(tmp_path, dir_source(tmp_path / "plugins"))
    lock(("project",), env)
    loaded = catalog(env)
    assert [p.ref for p in loaded.select(()).plugins] == ["code-review@1.0.0", "extra@1.1.0"]
    pinned = loaded.select(("extra@1.0.0",))
    assert [p.ref for p in pinned.plugins] == ["code-review@1.0.0", "extra@1.0.0"]
    with pytest.raises(CapabilityError, match="no version 2.0.0"):
        loaded.select(("extra@2.0.0",))
    (tmp_path / "project" / "reviewer.toml").write_text(
        dir_source(tmp_path / "plugins") + '[plugins]\ndisabled = ["extra"]\n'
    )
    loaded = catalog(env)
    assert [p.ref for p in loaded.select(()).plugins] == ["code-review@1.0.0"]
    with pytest.raises(CapabilityError, match="disabled"):
        loaded.select(("extra",))


def test_incompatible_plugin_fails(tmp_path: Path) -> None:
    make_plugin(tmp_path / "plugins" / "extra", requires=">=2.0.0")
    env = configure(tmp_path, dir_source(tmp_path / "plugins"))
    with pytest.raises(CapabilityError, match="requires reviewer >=2.0.0"):
        lock(("project",), env)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def test_git_source_is_pinned_to_a_tag_and_verified(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    make_plugin(remote / "plugins" / "extra")
    git(remote, "init", "-q", "-b", "main")
    git(remote, "-c", "user.email=t@x", "-c", "user.name=t", "add", ".")
    git(remote, "-c", "user.email=t@x", "-c", "user.name=t", "commit", "-q", "-m", "v1")
    git(remote, "tag", "v1")
    source = (
        f'[[sources]]\nname = "remote"\nkind = "git"\nurl = "{remote}"\nref = "v1"\n'
        'subdir = "plugins"\n'
    )
    env = configure(tmp_path, source)
    lock(("project",), env)
    assert [p.ref for p in catalog(env).plugins()][-1] == "extra@1.0.0"
    shutil.rmtree(tmp_path / "cache")
    (remote / "plugins" / "extra" / "skills" / "extra-skill" / "SKILL.md").write_text(
        "---\nname: extra-skill\ndescription: moved\n---\nMoved.\n"
    )
    git(remote, "-c", "user.email=t@x", "-c", "user.name=t", "commit", "-q", "-am", "moved")
    git(remote, "tag", "-f", "v1")
    with pytest.raises(CapabilityError, match="lock has"):
        catalog(env)
    env = configure(tmp_path, source.replace('ref = "v1"', 'ref = "main"'))
    with pytest.raises(CapabilityError, match="commit hash or a tag"):
        lock(("project",), env)


def test_package_source_via_entry_point(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "site" / "company_review"
    make_plugin(package, name="company")
    (package / "__init__.py").write_text("raise RuntimeError('plugins never run code')\n")
    monkeypatch.syspath_prepend(str(tmp_path / "site"))
    entry = importlib.metadata.EntryPoint(
        "company-review", "company_review", "agent_sample.review_plugins"
    )
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda group: [entry] if group == "agent_sample.review_plugins" else [],
    )
    source = '[[sources]]\nname = "company"\nkind = "package"\nentry_point = "company-review"\n'
    env = configure(tmp_path, source)
    lock(("project",), env)
    assert [p.ref for p in catalog(env).plugins()][-1] == "company@1.0.0"
    assert "company_review" not in sys.modules


def test_skills_can_be_restricted_per_request(tmp_path: Path) -> None:
    selected = catalog(isolated_env(tmp_path)).select((), ("security-review",))
    assert [skill.name for skill in selected.skills] == ["lead-reviewer", "security-review"]
    with pytest.raises(CapabilityError, match="unknown skill"):
        catalog(isolated_env(tmp_path)).select((), ("nope",))


def test_builtin_lock_ships_with_the_package_and_is_portable(tmp_path: Path) -> None:
    config, _ = load_settings(isolated_env(tmp_path))
    assert config.sources[0].lock_path == (BUILTIN_PLUGINS / "reviewer.lock.json").resolve()
    shipped = json.loads((BUILTIN_PLUGINS / "reviewer.lock.json").read_text())
    assert shipped["sources"]["builtin"]["location"] == "."
