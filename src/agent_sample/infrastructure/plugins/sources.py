"""Fontes de plugins declaradas em configuração, resolução (diretório, pacote, git) e lock.

Precedência: embutido → usuário → projeto (e, dentro de um arquivo, a ordem de declaração).
Cada arquivo de configuração tem um lock ao lado (`reviewer.lock.json`) com o que foi resolvido,
de onde, em qual versão e com qual hash. Conteúdo que diverge do lock falha a inicialização.
"""

import hashlib
import importlib.metadata
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from agent_sample.domain.model import CapabilityError
from agent_sample.domain.policy import Limits
from agent_sample.infrastructure.plugins.format import is_plugin

ENTRY_POINT_GROUP = "agent_sample.review_plugins"
LOCK_NAME = "reviewer.lock.json"
KINDS = ("dir", "package", "git")
COMMIT = re.compile(r"[0-9a-f]{40}")
DEFAULT_HOSTS = ("api.github.com",)


@dataclass(frozen=True, slots=True)
class SourceSpec:
    name: str
    kind: str
    location: str
    scope: str
    lock_path: Path
    ref: str = ""
    subdir: str = ""

    def describe(self) -> str:
        where = f"{self.location}@{self.ref}" if self.ref else self.location
        return f"{self.scope}:{self.name} ({self.kind} {where})"


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    spec: SourceSpec
    root: Path
    resolved: str
    plugin_roots: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class ReviewerConfig:
    sources: tuple[SourceSpec, ...]
    disabled: frozenset[str] = frozenset()
    limits: Limits = field(default_factory=Limits)
    allowed_hosts: tuple[str, ...] = DEFAULT_HOSTS
    files: tuple[Path, ...] = ()


def builtin_source(root: Path) -> SourceSpec:
    root = root.resolve()
    return SourceSpec("builtin", "dir", str(root), "builtin", root / LOCK_NAME)


def load_config(builtin: SourceSpec, user: Path | None, project: Path | None) -> ReviewerConfig:
    sources: list[SourceSpec] = [builtin]
    disabled: set[str] = set()
    limits: dict[str, Any] = {}
    hosts: tuple[str, ...] | None = None
    files: list[Path] = []
    for scope, path in (("user", user), ("project", project)):
        if path is None or not path.is_file():
            continue
        files.append(path)
        data = _toml(path)
        sources.extend(_sources(data.get("sources", []), scope, path))
        plugins = data.get("plugins", {})
        disabled.update(str(name) for name in plugins.get("disabled", []))
        limits.update(data.get("limits", {}))
        rest = data.get("pull_requests", {})
        if "allowed_hosts" in rest:
            hosts = tuple(str(host) for host in rest["allowed_hosts"])
    _unique_names(sources)
    return ReviewerConfig(
        sources=tuple(sources),
        disabled=frozenset(disabled),
        limits=_limits(limits),
        allowed_hosts=hosts if hosts is not None else DEFAULT_HOSTS,
        files=tuple(files),
    )


def _toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise CapabilityError(f"{path}: invalid TOML ({exc})") from exc


def _sources(raw: Any, scope: str, config: Path) -> list[SourceSpec]:
    if not isinstance(raw, list):
        raise CapabilityError(f"{config}: 'sources' must be an array of tables")
    specs: list[SourceSpec] = []
    for item in raw:
        name = str(item.get("name") or "")
        kind = str(item.get("kind") or "")
        if not name or kind not in KINDS:
            raise CapabilityError(f"{config}: each source needs a name and kind in {KINDS}")
        key = {"dir": "path", "package": "entry_point", "git": "url"}[kind]
        location = str(item.get(key) or "")
        if not location:
            raise CapabilityError(f"{config}: source {name} needs '{key}'")
        if kind == "dir":
            location = str((config.parent / location).resolve())
        ref = str(item.get("ref") or "")
        if kind == "git" and not ref:
            raise CapabilityError(f"{config}: git source {name} needs an immutable 'ref'")
        specs.append(
            SourceSpec(
                name,
                kind,
                location,
                scope,
                config.parent.resolve() / LOCK_NAME,
                ref,
                str(item.get("subdir") or ""),
            )
        )
    return specs


def _unique_names(sources: list[SourceSpec]) -> None:
    seen: set[str] = set()
    for spec in sources:
        if spec.name in seen:
            raise CapabilityError(f"source name declared twice: {spec.name}")
        seen.add(spec.name)


def _limits(values: dict[str, Any]) -> Limits:
    unknown = sorted(set(values) - {item.name for item in fields(Limits)})
    if unknown:
        raise CapabilityError(f"unknown limits: {', '.join(unknown)}")
    return Limits(
        **{
            key: float(value) if key == "timeout_seconds" else int(value)
            for key, value in values.items()
        }
    )


def resolve(spec: SourceSpec, cache: Path, locked_commit: str | None = None) -> ResolvedSource:
    if spec.kind == "dir":
        root, resolved = Path(spec.location), ""
        if not root.is_dir():
            raise CapabilityError(f"{spec.describe()}: directory not found")
    elif spec.kind == "package":
        root, resolved = _package(spec)
    else:
        root, resolved = _git(spec, cache, locked_commit)
    if spec.subdir:
        root = root / spec.subdir
    return ResolvedSource(spec, root, resolved, find_plugins(root))


def find_plugins(root: Path) -> tuple[Path, ...]:
    """O próprio diretório, ou filhos e netos (`<nome>/<versão>/`) que tenham manifesto."""
    if is_plugin(root):
        return (root,)
    found = [path for path in sorted(root.glob("*")) if path.is_dir() and is_plugin(path)]
    found += [path for path in sorted(root.glob("*/*")) if path.is_dir() and is_plugin(path)]
    return tuple(found)


def _package(spec: SourceSpec) -> tuple[Path, str]:
    """Pacote Python instalado que declara plugins por entry point. Nada do pacote é executado."""
    for entry in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        if entry.name != spec.location:
            continue
        found = importlib.util.find_spec(entry.value)
        if found is None or not found.submodule_search_locations:
            raise CapabilityError(f"{spec.describe()}: {entry.value} is not a package directory")
        version = entry.dist.version if entry.dist is not None else ""
        return Path(next(iter(found.submodule_search_locations))), version
    raise CapabilityError(f"{spec.describe()}: no entry point in group {ENTRY_POINT_GROUP}")


def _git(spec: SourceSpec, cache: Path, locked_commit: str | None) -> tuple[Path, str]:
    base = cache / hashlib.sha256(spec.location.encode()).hexdigest()[:16]
    if locked_commit and (base / locked_commit).is_dir():
        return base / locked_commit, locked_commit
    base.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="clone-", dir=base))
    try:
        _run_git(["clone", "--quiet", "--no-checkout", spec.location, str(work)], spec)
        commit = _commit(work, spec)
        if locked_commit and commit != locked_commit:
            raise CapabilityError(
                f"{spec.describe()}: ref now points to {commit[:12]}, lock has "
                f"{locked_commit[:12]}; run `reviewer plugins lock` if this is intended"
            )
        _run_git(["-C", str(work), "checkout", "--quiet", "--detach", commit], spec)
        target = base / commit
        if not target.exists():
            work.rename(target)
        return target, commit
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _commit(work: Path, spec: SourceSpec) -> str:
    if COMMIT.fullmatch(spec.ref):
        _run_git(["-C", str(work), "cat-file", "-e", f"{spec.ref}^{{commit}}"], spec)
        return spec.ref
    tag = _run_git(
        ["-C", str(work), "rev-parse", "--verify", "--quiet", f"refs/tags/{spec.ref}^{{commit}}"],
        spec,
        check=False,
    )
    if not tag:
        raise CapabilityError(
            f"{spec.describe()}: ref must be a full commit hash or a tag (branches move)"
        )
    return tag


def _run_git(args: list[str], spec: SourceSpec, check: bool = True) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1:] or ["git failed"]
        raise CapabilityError(f"{spec.describe()}: {detail[0]}")
    return result.stdout.strip() if result.returncode == 0 else ""


@dataclass(frozen=True, slots=True)
class LockEntry:
    kind: str
    location: str
    ref: str
    resolved: str
    plugins: dict[str, str]

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "location": self.location,
            "ref": self.ref,
            "resolved": self.resolved,
            "plugins": dict(sorted(self.plugins.items())),
        }


def read_lock(path: Path) -> dict[str, LockEntry]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
        return {
            name: LockEntry(
                entry["kind"],
                entry["location"],
                entry.get("ref", ""),
                entry.get("resolved", ""),
                dict(entry["plugins"]),
            )
            for name, entry in data["sources"].items()
        }
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        raise CapabilityError(f"{path}: invalid lock file") from exc


def write_lock(path: Path, entries: dict[str, LockEntry]) -> None:
    payload = {
        "lock_version": 1,
        "sources": {name: entries[name].as_json() for name in sorted(entries)},
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")


def lock_location(spec: SourceSpec) -> str:
    """O que o lock guarda como local: relativo ao lock para diretórios, para ser portável."""
    if spec.kind == "dir":
        try:
            return Path(spec.location).relative_to(spec.lock_path.parent).as_posix()
        except ValueError:
            return spec.location
    return spec.location


def verify(source: ResolvedSource, plugins: dict[str, str], entry: LockEntry | None) -> None:
    spec = source.spec
    if entry is None:
        raise CapabilityError(
            f"{spec.describe()}: not in {spec.lock_path}; run `reviewer plugins lock`"
        )
    expected = (spec.kind, lock_location(spec), spec.ref)
    if (entry.kind, entry.location, entry.ref) != expected:
        raise CapabilityError(
            f"{spec.describe()}: source changed since it was locked; run `reviewer plugins lock`"
        )
    if spec.kind != "dir" and entry.resolved != source.resolved:
        raise CapabilityError(
            f"{spec.describe()}: resolved {source.resolved or '?'} but lock has {entry.resolved}"
        )
    for ref in sorted(set(plugins) | set(entry.plugins)):
        if ref not in entry.plugins:
            raise CapabilityError(f"{spec.describe()}: plugin {ref} is not in the lock")
        if ref not in plugins:
            raise CapabilityError(f"{spec.describe()}: locked plugin {ref} is missing")
        if plugins[ref] != entry.plugins[ref]:
            raise CapabilityError(
                f"{spec.describe()}: plugin {ref} content differs from the lock "
                "(published versions are immutable; publish a new version instead)"
            )
