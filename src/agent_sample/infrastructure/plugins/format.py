"""Lê e valida um plugin no formato do ecossistema de agentes.

```
<plugin>/
  .claude-plugin/plugin.json      name, version, description, author, reviewer.requires
  skills/<skill>/SKILL.md         frontmatter name + description; corpo = instruções
  agents/<reviewer>.md            frontmatter name, description, tools, skills, languages, focus
```

Plugins não contêm código executável: tudo é lido como texto. O que o formato do ecossistema
tem e este revisor não usa é ignorado com aviso.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

from agent_sample.domain.capabilities import Plugin, Reviewer, Skill
from agent_sample.domain.model import CapabilityError
from agent_sample.domain.tools import TOOL_NAMES

MANIFEST = Path(".claude-plugin") / "plugin.json"
NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")
# Nomes de ferramentas comuns no ecossistema, mapeados para o catálogo do projeto.
TOOL_ALIASES = {
    "Read": "read_repo_file",
    "Grep": "search_code",
    "Glob": "list_repo_files",
    "LS": "list_repo_files",
}
IGNORED_DIRS = ("commands", "hooks", "scripts", "bin", "output-styles")
IGNORED_FILES = (".mcp.json", ".lsp.json")
IGNORED_KEYS = ("commands", "hooks", "mcpServers", "lspServers", "outputStyles", "agents", "skills")
IGNORED_AGENT_KEYS = ("model", "color", "permissionMode")


def is_plugin(root: Path) -> bool:
    return (root / MANIFEST).is_file()


def version_key(version: str) -> tuple[int, int, int]:
    matched = VERSION.fullmatch(version)
    if matched is None:
        raise CapabilityError(f"invalid version: {version} (use MAJOR.MINOR.PATCH)")
    return int(matched.group(1)), int(matched.group(2)), int(matched.group(3))


EXECUTABLE_SUFFIXES = (".py", ".sh", ".js", ".exe")
EXECUTABLE_MODE = 0o111


def digest(root: Path, *, strict_executables: bool = True) -> str:
    """sha256 do conteúdo do plugin: caminhos relativos e bytes, em ordem estável.

    Em fontes diretório e git (`strict_executables`), rejeita conteúdo executável (extensão
    ou bit de permissão) e symlinks que saem do root — o plugin é conteúdo, nunca código.
    """
    hasher = hashlib.sha256()
    resolved_root = root.resolve()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if strict_executables and path.is_symlink():
            target = path.resolve()
            if not target.is_relative_to(resolved_root):
                raise CapabilityError(f"{path}: symlink resolves outside the plugin root")
        relative = path.relative_to(root)
        if ".git" in relative.parts or "__pycache__" in relative.parts:
            continue
        if strict_executables and (
            path.suffix in EXECUTABLE_SUFFIXES or path.stat().st_mode & EXECUTABLE_MODE
        ):
            raise CapabilityError(f"{path}: plugins must not contain executable content")
        hasher.update(relative.as_posix().encode() + b"\0")
        hasher.update(path.read_bytes() + b"\0")
    return hasher.hexdigest()


def load_plugin(
    root: Path, source: str, reviewer_version: str, *, strict_executables: bool = True
) -> Plugin:
    manifest = _manifest(root)
    name = _required(manifest, "name", root / MANIFEST)
    if not NAME.fullmatch(name):
        raise CapabilityError(f"{root / MANIFEST}: invalid plugin name {name!r}")
    version = _required(manifest, "version", root / MANIFEST)
    version_key(version)
    _check_compatibility(manifest, reviewer_version, root / MANIFEST)
    warnings = _ignored(root, manifest)
    skills = tuple(
        _skill(path, name, version) for path in sorted((root / "skills").glob("*/SKILL.md"))
    )
    skill_names = {skill.name for skill in skills}
    reviewers: list[Reviewer] = []
    for path in sorted((root / "agents").glob("*.md")):
        reviewer, notes = _reviewer(path, name, skill_names)
        reviewers.append(reviewer)
        warnings.extend(notes)
    _unique([skill.name for skill in skills], "skill", root)
    _unique([reviewer.name for reviewer in reviewers], "reviewer", root)
    return Plugin(
        name=name,
        version=version,
        description=_required(manifest, "description", root / MANIFEST),
        author=_author(manifest.get("author")),
        source=source,
        digest=digest(root, strict_executables=strict_executables),
        skills=skills,
        reviewers=tuple(reviewers),
        warnings=tuple(warnings),
    )


def _manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST
    try:
        manifest = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise CapabilityError(f"{path}: plugin manifest is missing") from exc
    except json.JSONDecodeError as exc:
        raise CapabilityError(f"{path}: invalid JSON ({exc.msg})") from exc
    if not isinstance(manifest, dict):
        raise CapabilityError(f"{path}: manifest must be a JSON object")
    return manifest


def _required(data: dict[str, Any], key: str, where: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"{where}: '{key}' is required")
    return value.strip()


def _author(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return str(value or "")


def _check_compatibility(manifest: dict[str, Any], current: str, where: Path) -> None:
    section = manifest.get("reviewer") or {}
    requires = section.get("requires") if isinstance(section, dict) else None
    if not requires:
        return
    have = version_key(current)
    for clause in str(requires).split(","):
        matched = re.fullmatch(r"\s*(>=|<=|==|<|>)\s*(\d+\.\d+\.\d+)\s*", clause)
        if matched is None:
            raise CapabilityError(f"{where}: invalid reviewer.requires clause {clause!r}")
        operator, bound = matched.group(1), version_key(matched.group(2))
        ok = {
            ">=": have >= bound,
            "<=": have <= bound,
            "==": have == bound,
            "<": have < bound,
            ">": have > bound,
        }[operator]
        if not ok:
            raise CapabilityError(f"{where}: requires reviewer {requires}, this is {current}")


def _ignored(root: Path, manifest: dict[str, Any]) -> list[str]:
    warnings = [f"{key}: ignored (not supported)" for key in IGNORED_KEYS if key in manifest]
    warnings += [f"{d}/: ignored (not supported)" for d in IGNORED_DIRS if (root / d).exists()]
    warnings += [f"{f}: ignored (not supported)" for f in IGNORED_FILES if (root / f).exists()]
    for skill_dir in sorted((root / "skills").glob("*/scripts")):
        warnings.append(f"{skill_dir.relative_to(root)}/: ignored (plugins never run code)")
    return warnings


def frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text()
    if not text.startswith("---\n"):
        raise CapabilityError(f"{path}: must start with a '---' frontmatter block")
    end = text.find("\n---", 4)
    if end < 0:
        raise CapabilityError(f"{path}: frontmatter block is not closed")
    try:
        header = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as exc:
        raise CapabilityError(f"{path}: invalid frontmatter ({exc})") from exc
    if not isinstance(header, dict):
        raise CapabilityError(f"{path}: frontmatter must be a mapping")
    return header, text[end + 4 :].strip()


def _skill(path: Path, plugin: str, version: str) -> Skill:
    header, body = frontmatter(path)
    name = str(header.get("name") or "")
    if name != path.parent.name:
        raise CapabilityError(f"{path}: name {name!r} must match its folder {path.parent.name!r}")
    description = str(header.get("description") or "").strip()
    if not description or not body:
        raise CapabilityError(f"{path}: skill needs a description and a body")
    return Skill(
        name=name,
        plugin=plugin,
        version=version,
        description=description,
        body=body,
        digest=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _reviewer(path: Path, plugin: str, skills: set[str]) -> tuple[Reviewer, list[str]]:
    header, body = frontmatter(path)
    name = str(header.get("name") or "")
    if not NAME.fullmatch(name):
        raise CapabilityError(f"{path}: invalid reviewer name {name!r}")
    description = str(header.get("description") or "").strip()
    if not description or not body:
        raise CapabilityError(f"{path}: reviewer needs a description and instructions")
    tools = tuple(_tool(item, path) for item in _list(header.get("tools")))
    wanted = _list(header.get("skills"))
    missing = [skill for skill in wanted if skill not in skills]
    if missing:
        raise CapabilityError(f"{path}: references unknown skill(s) {', '.join(missing)}")
    notes = [f"agents/{path.name}: '{key}' ignored" for key in IGNORED_AGENT_KEYS if key in header]
    return (
        Reviewer(
            name=name,
            plugin=plugin,
            description=description,
            instructions=body,
            skills=tuple(wanted),
            tools=tuple(dict.fromkeys(tools)),
            languages=tuple(_list(header.get("languages"))),
            focus=tuple(_list(header.get("focus"))),
        ),
        notes,
    )


def _tool(name: str, where: Path) -> str:
    resolved = TOOL_ALIASES.get(name, name)
    if resolved not in TOOL_NAMES:
        raise CapabilityError(f"{where}: unknown tool {name!r} (catalog: {', '.join(TOOL_NAMES)})")
    return resolved


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise CapabilityError(f"expected a list or comma-separated string, got {value!r}")


def _unique(names: list[str], kind: str, root: Path) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise CapabilityError(f"{root}: duplicated {kind} {name!r}")
        seen.add(name)
