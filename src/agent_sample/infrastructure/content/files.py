import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path

from agent_sample.domain.content import AgentTask, PromptVersion, SkillVersion, unknown_placeholders
from agent_sample.domain.model import ContentError

VERSION = re.compile(r"v(\d+)")
KINDS = {"prompt": "prompts", "skill": "skills"}


class FileContentLibrary:
    """Prompts e skills em arquivos `<kind>/<nome>/<versão>.md`.

    `published.json` guarda o sha256 de cada versão publicada: uma versão publicada que mudar
    no disco é rejeitada na inicialização. Arquivos fora do manifesto são rascunhos: podem ser
    escolhidos explicitamente, mas nunca são o padrão.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._manifest_path = root / "published.json"
        self._manifest = self._read_manifest()
        self._prompts = {
            name: {version: self._prompt(name, version, path) for version, path in files.items()}
            for name, files in self._files("prompts").items()
        }
        self._skills = {
            name: {version: self._skill(name, version, path) for version, path in files.items()}
            for name, files in self._files("skills").items()
        }
        self._check_manifest_entries()

    def require(self, task: AgentTask) -> None:
        """Falha já na inicialização se a tarefa pedir conteúdo que não existe."""
        self.prompt(task.prompt)
        for skill in task.skills:
            self.skill(skill)

    def prompt(self, name: str, version: str | None = None) -> PromptVersion:
        return _pick("prompt", name, version, self._prompts)

    def skill(self, name: str, version: str | None = None) -> SkillVersion:
        return _pick("skill", name, version, self._skills)

    def prompts(self) -> tuple[PromptVersion, ...]:
        return tuple(item for versions in self._prompts.values() for item in versions.values())

    def skills(self) -> tuple[SkillVersion, ...]:
        return tuple(item for versions in self._skills.values() for item in versions.values())

    def publish(self, kind: str, name: str, version: str) -> str:
        if kind not in KINDS:
            raise ContentError(f"unknown content kind: {kind} (choose from prompt, skill)")
        store = self._prompts if kind == "prompt" else self._skills
        item = _pick(kind, name, version, store)
        if item.published:
            raise ContentError(f"{kind} {item.ref} is already published and cannot change")
        digest = _digest(self._path(KINDS[kind], name, version))
        self._manifest.setdefault(KINDS[kind], {}).setdefault(name, {})[version] = digest
        self._manifest_path.write_text(json.dumps(self._manifest, indent=2, sort_keys=True) + "\n")
        store[name][version] = replace(item, published=True)
        return digest

    def _read_manifest(self) -> dict[str, dict[str, dict[str, str]]]:
        if not self._manifest_path.exists():
            return {}
        try:
            manifest = json.loads(self._manifest_path.read_text())
        except json.JSONDecodeError as exc:
            raise ContentError(f"{self._manifest_path}: invalid JSON ({exc})") from exc
        if not isinstance(manifest, dict):
            raise ContentError(f"{self._manifest_path}: expected an object")
        return manifest

    def _files(self, kind: str) -> dict[str, dict[str, Path]]:
        found: dict[str, dict[str, Path]] = {}
        base = self._root / kind
        if not base.is_dir():
            return found
        for path in sorted(base.glob("*/*.md")):
            if not VERSION.fullmatch(path.stem):
                raise ContentError(f"{path}: version must look like v1, v2, ...")
            found.setdefault(path.parent.name, {})[path.stem] = path
        return found

    def _published(self, kind: str, name: str, version: str, path: Path) -> bool:
        expected = self._manifest.get(kind, {}).get(name, {}).get(version)
        if expected is None:
            return False
        if _digest(path) != expected:
            raise ContentError(
                f"{path}: published version changed; publish a new version instead of editing it"
            )
        return True

    def _prompt(self, name: str, version: str, path: Path) -> PromptVersion:
        template = path.read_text()
        unknown = unknown_placeholders(template)
        if unknown:
            raise ContentError(f"{path}: unknown placeholders {sorted(unknown)}")
        published = self._published("prompts", name, version, path)
        return PromptVersion(name, version, template, published)

    def _skill(self, name: str, version: str, path: Path) -> SkillVersion:
        header, body = _frontmatter(path)
        description = header.get("description", "")
        if not description or not body:
            raise ContentError(f"{path}: skill needs a 'description' in frontmatter and a body")
        published = self._published("skills", name, version, path)
        return SkillVersion(name, version, description, body, published)

    def _check_manifest_entries(self) -> None:
        for kind, names in self._manifest.items():
            for name, versions in names.items():
                for version in versions:
                    path = self._path(kind, name, version)
                    if not path.exists():
                        raise ContentError(f"{path}: listed in published.json but missing")

    def _path(self, kind: str, name: str, version: str) -> Path:
        return self._root / kind / name / f"{version}.md"


def _pick[T: (PromptVersion, SkillVersion)](
    kind: str, name: str, version: str | None, store: dict[str, dict[str, T]]
) -> T:
    versions = store.get(name)
    if not versions:
        raise ContentError(f"{kind} not found: {name} (available: {', '.join(store) or 'none'})")
    if version is None:
        published = [item for item in versions.values() if item.published]
        if not published:
            raise ContentError(f"{kind} {name} has no published version")
        return max(published, key=lambda item: _number(item.version))
    if version not in versions:
        available = ", ".join(sorted(versions, key=_number))
        raise ContentError(f"{kind} {name} has no version {version} (available: {available})")
    return versions[version]


def _number(version: str) -> int:
    matched = VERSION.fullmatch(version)
    return int(matched.group(1)) if matched else -1


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text()
    if not text.startswith("---\n"):
        raise ContentError(f"{path}: skill must start with a '---' frontmatter block")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ContentError(f"{path}: frontmatter block is not closed")
    header: dict[str, str] = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            raise ContentError(f"{path}: invalid frontmatter line: {line}")
        header[key.strip()] = value.strip()
    return header, text[end + 5 :].strip()
